from __future__ import annotations

import socket
import struct
import threading
import time
import wave
from collections import deque
from pathlib import Path

from .g1_mic_recorder import (
    CHANNELS,
    GROUP_IP,
    PORT,
    SAMPLE_RATE,
    SAMPLE_WIDTH,
    detect_interface_ip,
)


BYTE_RATE = (
    SAMPLE_RATE
    * CHANNELS
    * SAMPLE_WIDTH
)


class G1ContinuousRecorder:
    """
    G1 麦克风持续接收器。

    socket 从 start() 到 stop() 始终保持，
    ASR 是否运行不会中断 UDP 收音。
    """

    def __init__(
        self,
        *,
        interface_ip=None,
        buffer_seconds=12.0,
    ):
        self.interface_ip = (
            interface_ip
            or detect_interface_ip()
        )

        self.buffer_seconds = float(
            buffer_seconds
        )

        self.max_bytes = int(
            BYTE_RATE
            * self.buffer_seconds
        )

        self._chunks = deque()
        self._bytes = 0

        self._lock = threading.Lock()

        self._running = False
        self._thread = None
        self._sock = None

        self.started_monotonic = None


    def _open_socket(self):
        sock = socket.socket(
            socket.AF_INET,
            socket.SOCK_DGRAM,
            socket.IPPROTO_UDP,
        )

        sock.setsockopt(
            socket.SOL_SOCKET,
            socket.SO_REUSEADDR,
            1,
        )

        sock.setsockopt(
            socket.SOL_SOCKET,
            socket.SO_RCVBUF,
            1024 * 1024,
        )

        sock.bind(
            (
                "",
                PORT,
            )
        )

        membership = struct.pack(
            "4s4s",
            socket.inet_aton(
                GROUP_IP
            ),
            socket.inet_aton(
                self.interface_ip
            ),
        )

        sock.setsockopt(
            socket.IPPROTO_IP,
            socket.IP_ADD_MEMBERSHIP,
            membership,
        )

        sock.settimeout(
            0.5
        )

        return sock, membership


    def start(self):
        if self._running:
            return

        sock, membership = (
            self._open_socket()
        )

        self._sock = sock
        self._membership = membership

        self._running = True
        self.started_monotonic = (
            time.monotonic()
        )

        self._thread = threading.Thread(
            target=self._receive_loop,
            name="g1-continuous-mic",
            daemon=True,
        )

        self._thread.start()


    def _receive_loop(self):
        while self._running:

            try:
                data, _address = (
                    self._sock.recvfrom(
                        65535
                    )
                )

            except socket.timeout:
                continue

            except OSError:
                if self._running:
                    raise
                break

            if not data:
                continue

            # PCM16 必须保持偶数字节。
            if len(data) % 2:
                data = data[:-1]

            if not data:
                continue

            with self._lock:

                self._chunks.append(
                    data
                )

                self._bytes += len(
                    data
                )

                while (
                    self._bytes
                    > self.max_bytes
                    and self._chunks
                ):
                    old = (
                        self._chunks
                        .popleft()
                    )

                    self._bytes -= len(
                        old
                    )


    def snapshot_pcm(
        self,
        *,
        seconds=3.5,
    ):
        wanted = int(
            BYTE_RATE
            * float(seconds)
        )

        with self._lock:
            pcm = b"".join(
                self._chunks
            )

        if len(pcm) > wanted:
            pcm = pcm[-wanted:]

        if len(pcm) % 2:
            pcm = pcm[:-1]

        return pcm


    def write_snapshot(
        self,
        output_path,
        *,
        seconds=3.5,
    ):
        pcm = self.snapshot_pcm(
            seconds=seconds
        )

        if not pcm:
            raise RuntimeError(
                "持续麦克风暂时没有收到PCM"
            )

        path = Path(
            output_path
        )

        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with wave.open(
            str(path),
            "wb",
        ) as wav:
            wav.setnchannels(
                CHANNELS
            )

            wav.setsampwidth(
                SAMPLE_WIDTH
            )

            wav.setframerate(
                SAMPLE_RATE
            )

            wav.writeframes(
                pcm
            )

        return {
            "path":
                str(path.resolve()),

            "pcm_bytes":
                len(pcm),

            "audio_seconds":
                len(pcm)
                / BYTE_RATE,
        }


    def stop(self):
        self._running = False

        if self._sock is not None:

            try:
                self._sock.setsockopt(
                    socket.IPPROTO_IP,
                    socket.IP_DROP_MEMBERSHIP,
                    self._membership,
                )

            except OSError:
                pass

            try:
                self._sock.close()
            except OSError:
                pass

            self._sock = None

        if (
            self._thread is not None
            and self._thread.is_alive()
        ):
            self._thread.join(
                timeout=1.0
            )

        self._thread = None


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
