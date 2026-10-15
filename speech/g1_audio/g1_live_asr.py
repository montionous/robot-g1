from __future__ import annotations

import queue
import threading
import time
from pathlib import Path

from .g1_continuous_recorder import (
    G1ContinuousRecorder,
)


class G1RollingASR:
    """
    G1持续麦克风 + 高重叠完整窗口ASR。

    设计：
        麦克风只打开一次，持续接收PCM。

        默认：
            window = 4.5 秒
            hop    = 0.5 秒

        即：

            0.0 ~ 4.5
            0.5 ~ 5.0
            1.0 ~ 5.5
            1.5 ~ 6.0
            ...

    多个窗口共享同一个持续麦克风流，
    不会真的启动多个麦克风录音器。

    ASR worker 独立处理窗口，
    不会阻塞麦克风接收。
    """

    def __init__(
        self,
        speech,
        *,
        window_seconds=4.5,
        hop_seconds=0.5,
        worker_count=2,
        buffer_seconds=12.0,
        interface_ip=None,
        runtime_dir="/tmp/g1_live_asr",
    ):
        self.speech = speech

        self.window_seconds = float(
            window_seconds
        )

        self.hop_seconds = float(
            hop_seconds
        )

        self.worker_count = max(
            1,
            int(worker_count),
        )

        self.runtime_dir = Path(
            runtime_dir
        )

        self.runtime_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.recorder = (
            G1ContinuousRecorder(
                interface_ip=interface_ip,
                buffer_seconds=max(
                    buffer_seconds,
                    self.window_seconds + 4.0,
                ),
            )
        )

        # 窗口队列不无限增长。
        #
        # 两个worker处理速度约能覆盖
        # 0.5秒一个窗口。
        #
        # 如果极端情况下ASR变慢，
        # 优先保留新窗口，丢弃过旧窗口，
        # 不允许实时系统越积越慢。
        self._snapshot_queue = queue.Queue(
            maxsize=6
        )

        self._result_queue = queue.Queue(
            maxsize=50
        )

        self._running = False

        self._snapshot_thread = None

        self._asr_threads = []

        self._sequence = 0

        self._dedup_lock = threading.Lock()

        self._recent_texts = {}


    @staticmethod
    def _normalize_text(
        text,
    ):
        return (
            str(text or "")
            .strip()
            .lower()
            .replace(" ", "")
        )


    def start(self):
        if self._running:
            return

        self._running = True

        self.recorder.start()

        self._snapshot_thread = (
            threading.Thread(
                target=self._snapshot_loop,
                name="g1-live-snapshot",
                daemon=True,
            )
        )

        self._snapshot_thread.start()

        self._asr_threads = []

        for worker_index in range(
            self.worker_count
        ):

            thread = threading.Thread(
                target=self._asr_loop,
                args=(worker_index,),
                name=(
                    "g1-live-asr-"
                    f"{worker_index + 1}"
                ),
                daemon=True,
            )

            thread.start()

            self._asr_threads.append(
                thread
            )


    def _discard_oldest_snapshot(
        self,
    ):
        try:
            item = (
                self._snapshot_queue
                .get_nowait()
            )

        except queue.Empty:
            return

        path = item.get(
            "path"
        )

        if path:

            try:
                Path(path).unlink(
                    missing_ok=True
                )

            except Exception:
                pass


    def _snapshot_loop(self):
        # 和原4.5秒版本保持一致：
        # 第一轮必须先积满一个完整窗口。
        warmup_deadline = (
            time.monotonic()
            + self.window_seconds
        )

        while (
            self._running
            and time.monotonic()
            < warmup_deadline
        ):
            time.sleep(
                0.05
            )

        next_snapshot = (
            time.monotonic()
        )

        while self._running:

            now = time.monotonic()

            if now < next_snapshot:

                time.sleep(
                    min(
                        0.05,
                        next_snapshot - now,
                    )
                )

                continue

            self._sequence += 1

            sequence = self._sequence

            path = (
                self.runtime_dir
                / (
                    "snapshot_"
                    f"{sequence:08d}"
                    ".wav"
                )
            )

            try:
                info = (
                    self.recorder
                    .write_snapshot(
                        path,
                        seconds=
                            self.window_seconds,
                    )
                )

                # 理论上warmup以后都会是完整窗口。
                # 如果UDP暂时缺包导致太短，
                # 就不送ASR。
                if (
                    info["audio_seconds"]
                    < (
                        self.window_seconds
                        * 0.80
                    )
                ):

                    path.unlink(
                        missing_ok=True
                    )

                else:

                    item = {
                        "sequence":
                            sequence,

                        "path":
                            str(path),

                        "created_monotonic":
                            time.monotonic(),

                        "audio_seconds":
                            info[
                                "audio_seconds"
                            ],
                    }

                    if (
                        self._snapshot_queue
                        .full()
                    ):
                        self._discard_oldest_snapshot()

                    try:
                        self._snapshot_queue.put_nowait(
                            item
                        )

                    except queue.Full:

                        try:
                            path.unlink(
                                missing_ok=True
                            )
                        except Exception:
                            pass

            except Exception as exc:

                self._emit(
                    {
                        "kind":
                            "snapshot_error",

                        "error":
                            repr(exc),
                    }
                )

            # 固定按hop推进，
            # 不把当前处理耗时累计进去。
            next_snapshot += (
                self.hop_seconds
            )

            # 如果机器发生明显卡顿，
            # 不补发大量历史snapshot，
            # 直接回到实时位置。
            if (
                time.monotonic()
                - next_snapshot
                > self.hop_seconds * 2
            ):
                next_snapshot = (
                    time.monotonic()
                    + self.hop_seconds
                )


    def _is_recent_duplicate(
        self,
        text,
    ):
        normalized = (
            self._normalize_text(
                text
            )
        )

        if not normalized:
            return True

        now = time.monotonic()

        with self._dedup_lock:

            # 这里只做很短时间的日志去重，
            # 不承担业务层的“意图去重”。
            #
            # Showcase真正的重复保护仍由
            # 状态机负责。
            last = self._recent_texts.get(
                normalized
            )

            self._recent_texts[
                normalized
            ] = now

            # 顺手清理旧项。
            expired = [
                key
                for key, timestamp
                in self._recent_texts.items()
                if now - timestamp > 5.0
            ]

            for key in expired:
                self._recent_texts.pop(
                    key,
                    None,
                )

        if last is None:
            return False

        return (
            now - last
            < 1.0
        )


    def _asr_loop(
        self,
        worker_index,
    ):
        while self._running:

            try:
                item = (
                    self._snapshot_queue
                    .get(
                        timeout=0.2
                    )
                )

            except queue.Empty:
                continue

            path = Path(
                item["path"]
            )

            sequence = item[
                "sequence"
            ]

            queue_ms = (
                time.monotonic()
                - item[
                    "created_monotonic"
                ]
            ) * 1000

            started = (
                time.perf_counter()
            )

            try:
                result = (
                    self.speech
                    .transcribe(
                        path
                    )
                )

                asr_ms = (
                    time.perf_counter()
                    - started
                ) * 1000

                text = str(
                    result.get(
                        "text",
                        "",
                    )
                ).strip()

                if not text:
                    continue

                if (
                    self._is_recent_duplicate(
                        text
                    )
                ):
                    continue

                self._emit(
                    {
                        "kind":
                            "transcript",

                        "text":
                            text,

                        "normalized_text":
                            self._normalize_text(
                                text
                            ),

                        "asr_ms":
                            asr_ms,

                        "queue_ms":
                            queue_ms,

                        "total_ms":
                            queue_ms
                            + asr_ms,

                        "sequence":
                            sequence,

                        "worker":
                            worker_index + 1,

                        "audio_seconds":
                            item.get(
                                "audio_seconds"
                            ),

                        "audio_path":
                            str(path),

                        # ASR结果完成、准备进入业务主循环的时刻。
                        "ready_monotonic":
                            time.monotonic(),
                    }
                )

            except Exception as exc:

                self._emit(
                    {
                        "kind":
                            "asr_error",

                        "sequence":
                            sequence,

                        "worker":
                            worker_index + 1,

                        "error":
                            repr(exc),
                    }
                )

            finally:

                try:
                    path.unlink(
                        missing_ok=True
                    )

                except Exception:
                    pass


    def _emit(
        self,
        event,
    ):
        try:
            self._result_queue.put_nowait(
                event
            )

        except queue.Full:

            try:
                self._result_queue.get_nowait()

            except queue.Empty:
                pass

            try:
                self._result_queue.put_nowait(
                    event
                )

            except queue.Full:
                pass


    def get_event(
        self,
        *,
        timeout=0.5,
    ):
        try:
            return (
                self._result_queue
                .get(
                    timeout=timeout
                )
            )

        except queue.Empty:
            return None


    def stop(self):
        self._running = False

        self.recorder.stop()

        if (
            self._snapshot_thread
            is not None
            and
            self._snapshot_thread.is_alive()
        ):
            self._snapshot_thread.join(
                timeout=2.0
            )

        self._snapshot_thread = None

        for thread in (
            self._asr_threads
        ):

            if thread.is_alive():

                thread.join(
                    timeout=2.0
                )

        self._asr_threads = []

        # 清理还没处理的snapshot。
        while True:

            try:
                item = (
                    self._snapshot_queue
                    .get_nowait()
                )

            except queue.Empty:
                break

            try:
                Path(
                    item["path"]
                ).unlink(
                    missing_ok=True
                )

            except Exception:
                pass

        # 清理异常退出留下的临时文件。
        for path in (
            self.runtime_dir
            .glob("snapshot_*.wav")
        ):

            try:
                path.unlink()

            except Exception:
                pass


    def __enter__(self):
        self.start()

        return self


    def __exit__(
        self,
        exc_type,
        exc,
        tb,
    ):
        self.stop()
