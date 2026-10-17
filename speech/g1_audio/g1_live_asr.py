from __future__ import annotations

import io
import queue
import shutil
import tempfile
import threading
import time
import wave
from dataclasses import dataclass
from pathlib import Path

from .g1_continuous_recorder import (
    BYTE_RATE,
    G1ContinuousRecorder,
)
from .g1_mic_recorder import (
    CHANNELS,
    SAMPLE_RATE,
    SAMPLE_WIDTH,
)
from .g1_vad import analyze_pcm16


@dataclass(frozen=True)
class WindowSpec:
    """One scheduled view over the shared continuous PCM buffer."""

    due_seconds: float
    duration_seconds: float
    phase: str


def build_startup_plan(
    *,
    window_seconds: float = 4.5,
    hop_seconds: float = 0.5,
    startup_from_seconds: float | None = None,
) -> tuple[WindowSpec, ...]:
    """Build progressive startup windows followed by the first full window.

    startup_from_seconds=None preserves the historical behaviour: wait for one
    full window before the first ASR request. A value such as 2.0 produces 2.0,
    2.5, ..., 4.0 second bootstrap windows and one 4.5 second steady window.
    It never opens another microphone socket.
    """

    window = float(window_seconds)
    hop = float(hop_seconds)

    if window <= 0:
        raise ValueError("window_seconds must be greater than zero")

    if hop <= 0:
        raise ValueError("hop_seconds must be greater than zero")

    if startup_from_seconds is None:
        return (
            WindowSpec(
                due_seconds=window,
                duration_seconds=window,
                phase="steady",
            ),
        )

    startup = float(startup_from_seconds)

    if not 0 < startup <= window:
        raise ValueError(
            "startup_from_seconds must be in (0, window_seconds]"
        )

    specs = []
    due = startup

    while due < window - 1e-9:
        specs.append(
            WindowSpec(
                due_seconds=due,
                duration_seconds=due,
                phase="bootstrap",
            )
        )
        due = round(due + hop, 9)

    specs.append(
        WindowSpec(
            due_seconds=window,
            duration_seconds=window,
            phase="steady",
        )
    )

    return tuple(specs)


def pcm_to_wav_bytes(
    pcm: bytes,
) -> bytes:
    """Wrap PCM16 data in a WAV container without creating a snapshot file."""

    data = bytes(pcm)

    if len(data) % SAMPLE_WIDTH:
        data = data[:-(len(data) % SAMPLE_WIDTH)]

    buffer = io.BytesIO()

    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(CHANNELS)
        wav.setsampwidth(SAMPLE_WIDTH)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(data)

    return buffer.getvalue()


class G1RollingASR:
    """Single G1 microphone stream with overlapping, bounded ASR windows.

    The recorder stays open for the life of this object. Startup windows read
    from the same in-memory PCM ring buffer, so a 2.0/2.5/.../4.5 second
    startup plan is not equivalent to opening multiple recorders.

    ASR work items carry WAV bytes. SpeechClient.transcribe_bytes keeps normal
    operation file-free; a small private temporary directory is used only for
    legacy clients that expose transcribe(path) but not the bytes API.
    """

    def __init__(
        self,
        speech,
        *,
        window_seconds=4.5,
        hop_seconds=0.5,
        startup_min_window_seconds=None,
        worker_count=2,
        buffer_seconds=12.0,
        interface_ip=None,
        runtime_dir="/tmp/g1_live_asr",
        speech_rms_threshold=450,
        min_consecutive_voice_frames=3,
        min_voiced_seconds=0.12,
        recorder=None,
    ):
        self.speech = speech
        self.window_seconds = float(window_seconds)
        self.hop_seconds = float(hop_seconds)

        if self.window_seconds <= 0:
            raise ValueError("window_seconds must be greater than zero")

        if self.hop_seconds <= 0:
            raise ValueError("hop_seconds must be greater than zero")

        if startup_min_window_seconds is None:
            self.startup_min_window_seconds = None
        else:
            self.startup_min_window_seconds = float(
                startup_min_window_seconds
            )

            if not 0 < self.startup_min_window_seconds <= self.window_seconds:
                raise ValueError(
                    "startup_min_window_seconds must be in "
                    "(0, window_seconds]"
                )

        self.worker_count = max(1, int(worker_count))
        self.runtime_dir = Path(runtime_dir)

        if speech_rms_threshold is None:
            self.speech_rms_threshold = None
        elif (
            not isinstance(speech_rms_threshold, int)
            or not 1 <= speech_rms_threshold <= 32767
        ):
            raise ValueError(
                "speech_rms_threshold must be None or an integer in [1, 32767]"
            )
        else:
            self.speech_rms_threshold = speech_rms_threshold

        if (
            not isinstance(min_consecutive_voice_frames, int)
            or min_consecutive_voice_frames < 1
        ):
            raise ValueError("min_consecutive_voice_frames must be at least 1")

        if min_voiced_seconds < 0:
            raise ValueError("min_voiced_seconds must not be negative")

        self.min_consecutive_voice_frames = min_consecutive_voice_frames
        self.min_voiced_seconds = float(min_voiced_seconds)

        self.recorder = recorder or G1ContinuousRecorder(
            interface_ip=interface_ip,
            buffer_seconds=max(
                buffer_seconds,
                self.window_seconds + 4.0,
            ),
        )

        # Keep latency bounded if cloud ASR becomes slower than new windows.
        self._snapshot_queue = queue.Queue(maxsize=6)
        self._result_queue = queue.Queue(maxsize=50)
        self._running = False
        self._snapshot_thread = None
        self._asr_threads = []
        self._started_monotonic = None
        self._session_dir = None
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

    def _ensure_session_dir(self):
        if self._session_dir is not None:
            return self._session_dir

        self.runtime_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._session_dir = Path(
            tempfile.mkdtemp(
                prefix="g1-live-asr-",
                dir=self.runtime_dir,
            )
        )

        return self._session_dir

    def _cleanup_session_dir(self):
        if self._session_dir is None:
            return

        shutil.rmtree(
            self._session_dir,
            ignore_errors=True,
        )
        self._session_dir = None

    def start(self):
        if self._running:
            return

        if any(thread.is_alive() for thread in self._asr_threads):
            raise RuntimeError("previous G1RollingASR workers have not stopped")

        self._asr_threads = []
        self._ensure_session_dir()

        try:
            self.recorder.start()
        except Exception:
            self._cleanup_session_dir()
            raise

        self._running = True
        self._started_monotonic = time.monotonic()

        self._snapshot_thread = threading.Thread(
            target=self._snapshot_loop,
            name="g1-live-snapshot",
            daemon=True,
        )
        self._snapshot_thread.start()

        for worker_index in range(self.worker_count):
            thread = threading.Thread(
                target=self._asr_loop,
                args=(worker_index,),
                name=f"g1-live-asr-{worker_index + 1}",
                daemon=True,
            )
            thread.start()
            self._asr_threads.append(thread)

    def _discard_oldest_snapshot(self):
        try:
            self._snapshot_queue.get_nowait()
        except queue.Empty:
            return

    def _disabled_vad_metadata(
        self,
        *,
        audio_seconds,
    ):
        return {
            "enabled": False,
            "speech_detected": None,
            "reason": "disabled",
            "audio_seconds": audio_seconds,
        }

    def _capture_window(
        self,
        spec: WindowSpec,
        *,
        captured_monotonic=None,
    ):
        """Capture one scheduled window and enqueue it when it passes VAD.

        It returns the queued item for deterministic offline tests, or None
        when PCM is incomplete or the VAD rejects it.
        """

        pcm = self.recorder.snapshot_pcm(
            seconds=spec.duration_seconds,
        )

        if len(pcm) % SAMPLE_WIDTH:
            pcm = pcm[:-(len(pcm) % SAMPLE_WIDTH)]

        audio_seconds = len(pcm) / BYTE_RATE

        if audio_seconds < spec.duration_seconds * 0.80:
            return None

        if self.speech_rms_threshold is None:
            vad = self._disabled_vad_metadata(
                audio_seconds=audio_seconds,
            )
        else:
            vad = analyze_pcm16(
                pcm,
                threshold_rms=self.speech_rms_threshold,
                min_consecutive_frames=self.min_consecutive_voice_frames,
            )

            if not vad["speech_detected"]:
                return None

            if vad["voiced_seconds"] < self.min_voiced_seconds:
                return None

        self._sequence += 1
        now = captured_monotonic or time.monotonic()

        item = {
            "sequence": self._sequence,
            "audio_data": pcm_to_wav_bytes(pcm),
            "created_monotonic": now,
            "captured_monotonic": now,
            "audio_seconds": audio_seconds,
            "window_seconds": spec.duration_seconds,
            "phase": spec.phase,
            "vad": vad,
        }

        if self._snapshot_queue.full():
            self._discard_oldest_snapshot()

        try:
            self._snapshot_queue.put_nowait(item)
        except queue.Full:
            return None

        return item

    def _snapshot_loop(self):
        started = self._started_monotonic or time.monotonic()
        plan = list(
            build_startup_plan(
                window_seconds=self.window_seconds,
                hop_seconds=self.hop_seconds,
                startup_from_seconds=self.startup_min_window_seconds,
            )
        )
        spec = plan.pop(0)

        while self._running:
            due_monotonic = started + spec.due_seconds
            now = time.monotonic()

            if now < due_monotonic:
                time.sleep(
                    min(
                        0.05,
                        due_monotonic - now,
                    )
                )
                continue

            try:
                self._capture_window(
                    spec,
                    captured_monotonic=now,
                )
            except Exception as exc:
                self._emit(
                    {
                        "kind": "snapshot_error",
                        "error": repr(exc),
                    }
                )

            if plan:
                spec = plan.pop(0)
            else:
                spec = WindowSpec(
                    due_seconds=spec.due_seconds + self.hop_seconds,
                    duration_seconds=self.window_seconds,
                    phase="steady",
                )

            # Do not catch up by flooding old windows after a long stall.
            current = time.monotonic()
            next_due_monotonic = started + spec.due_seconds

            if current - next_due_monotonic > self.hop_seconds * 2:
                elapsed = current - started
                next_due = elapsed + self.hop_seconds

                if next_due < self.window_seconds:
                    spec = WindowSpec(
                        due_seconds=next_due,
                        duration_seconds=next_due,
                        phase="bootstrap",
                    )
                else:
                    spec = WindowSpec(
                        due_seconds=next_due,
                        duration_seconds=self.window_seconds,
                        phase="steady",
                    )
                plan.clear()

    def _is_recent_duplicate(
        self,
        text,
        *,
        phase,
    ):
        normalized = self._normalize_text(text)

        if not normalized:
            return True

        # A bootstrap preview must not suppress the first full-window result.
        key = (phase, normalized)
        now = time.monotonic()

        with self._dedup_lock:
            last = self._recent_texts.get(key)
            self._recent_texts[key] = now

            expired = [
                recent_key
                for recent_key, timestamp in self._recent_texts.items()
                if now - timestamp > 5.0
            ]

            for recent_key in expired:
                self._recent_texts.pop(recent_key, None)

        return last is not None and now - last < 1.0

    def _transcribe_item(
        self,
        item,
    ):
        transcribe_bytes = getattr(
            self.speech,
            "transcribe_bytes",
            None,
        )

        if callable(transcribe_bytes):
            return (
                transcribe_bytes(
                    item["audio_data"],
                    filename=(
                        "g1_live_"
                        f"{item['sequence']:08d}.wav"
                    ),
                ),
                "bytes",
            )

        session_dir = self._ensure_session_dir()

        with tempfile.NamedTemporaryFile(
            prefix="snapshot-",
            suffix=".wav",
            dir=session_dir,
            delete=False,
        ) as output:
            output.write(item["audio_data"])
            path = Path(output.name)

        try:
            return self.speech.transcribe(path), "path_fallback"
        finally:
            path.unlink(missing_ok=True)

    def _asr_loop(
        self,
        worker_index,
    ):
        while self._running:
            try:
                item = self._snapshot_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            if not self._running:
                continue

            sequence = item["sequence"]
            queue_ms = (
                time.monotonic()
                - item["created_monotonic"]
            ) * 1000
            started = time.perf_counter()

            try:
                result, transport = self._transcribe_item(item)
                asr_ms = (time.perf_counter() - started) * 1000
                text = str(result.get("text", "")).strip()

                if not text or not self._running:
                    continue

                phase = item.get("phase", "steady")

                if self._is_recent_duplicate(
                    text,
                    phase=phase,
                ):
                    continue

                self._emit(
                    {
                        "kind": "transcript",
                        "text": text,
                        "normalized_text": self._normalize_text(text),
                        "asr_ms": asr_ms,
                        "queue_ms": queue_ms,
                        "total_ms": queue_ms + asr_ms,
                        "sequence": sequence,
                        "worker": worker_index + 1,
                        "audio_seconds": item.get("audio_seconds"),
                        "window_seconds": item.get("window_seconds"),
                        "phase": phase,
                        "is_preview": phase == "bootstrap",
                        "vad": item.get("vad"),
                        "audio_transport": transport,
                        # Bytes are released after this call. Keep the legacy
                        # key explicit rather than pointing logs at a dead path.
                        "audio_path": None,
                        "capture_end_monotonic": item.get(
                            "captured_monotonic"
                        ),
                        "ready_monotonic": time.monotonic(),
                    }
                )
            except Exception as exc:
                if self._running:
                    self._emit(
                        {
                            "kind": "asr_error",
                            "sequence": sequence,
                            "worker": worker_index + 1,
                            "error": repr(exc),
                        }
                    )

    def _emit(
        self,
        event,
    ):
        try:
            self._result_queue.put_nowait(event)
        except queue.Full:
            try:
                self._result_queue.get_nowait()
            except queue.Empty:
                pass

            try:
                self._result_queue.put_nowait(event)
            except queue.Full:
                pass

    def get_event(
        self,
        *,
        timeout=0.5,
    ):
        try:
            return self._result_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def stop(self):
        self._running = False

        try:
            self.recorder.stop()
        finally:
            if (
                self._snapshot_thread is not None
                and self._snapshot_thread.is_alive()
            ):
                self._snapshot_thread.join(timeout=2.0)

            self._snapshot_thread = None

        alive_threads = []

        for thread in self._asr_threads:
            if thread.is_alive():
                thread.join(timeout=2.0)

            if thread.is_alive():
                alive_threads.append(thread)

        self._asr_threads = alive_threads

        while True:
            try:
                self._snapshot_queue.get_nowait()
            except queue.Empty:
                break

        # Do not remove a compatibility file while a still-running worker may
        # be reading it. A normal stop has no live workers and removes the
        # complete per-instance directory.
        if not self._asr_threads:
            self._cleanup_session_dir()

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
