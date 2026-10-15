#!/usr/bin/env python3

from __future__ import annotations

import argparse
import audioop
import math
import socket
import struct
import time
import wave
from collections import Counter, deque
from pathlib import Path
from threading import Event


# G1 本机/计算单元可访问地址
ROBOT_IP = "192.168.123.164"

# Unitree G1 麦克风多播
GROUP_IP = "239.168.123.161"
PORT = 5555

# 官方音频格式
SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2


class G1MicError(RuntimeError):
    pass


def detect_interface_ip(
    target_ip: str = ROBOT_IP,
) -> str:
    """
    找出中间主机访问机器人时使用的本地 IPv4 地址。

    注意：
    target_ip 只是用来选择网卡，
    不是要求麦克风 UDP 包必须从这个 IP 发出。
    """

    sock = socket.socket(
        socket.AF_INET,
        socket.SOCK_DGRAM,
    )

    try:
        sock.connect(
            (
                target_ip,
                9,
            )
        )

        local_ip = (
            sock.getsockname()[0]
        )

    finally:
        sock.close()

    if not local_ip:
        raise G1MicError(
            "无法确定连接 G1 使用的本地 IP"
        )

    return local_ip


def record_g1_wav(
    output_path,
    *,
    seconds: float = 5.0,
    interface_ip: str | None = None,
    wait_for_speech: bool = False,
    start_timeout: float = 12.0,
    silence_timeout: float = 1.8,
    speech_rms_threshold: int = 450,
    pre_roll_seconds: float = 0.35,
    min_speech_seconds: float = 0.8,
    cancel_event: Event | None = None,
) -> dict:

    for name, value, maximum in (
        ("seconds", seconds, 60.0), ("start_timeout", start_timeout, 60.0),
        ("silence_timeout", silence_timeout, 10.0),
    ):
        if not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= maximum:
            raise ValueError(f"{name} must be finite and in (0, {maximum}]")
    if not isinstance(speech_rms_threshold, int) or not 1 <= speech_rms_threshold <= 32767:
        raise ValueError("speech_rms_threshold must be an integer in [1, 32767]")
    if not math.isfinite(pre_roll_seconds) or not 0 <= pre_roll_seconds <= 2:
        raise ValueError("pre_roll_seconds must be in [0, 2]")
    if not math.isfinite(min_speech_seconds) or not 0 <= min_speech_seconds <= 60:
        raise ValueError("min_speech_seconds must be in [0, 60]")

    output_path = Path(
        output_path
    )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if interface_ip is None:
        interface_ip = (
            detect_interface_ip()
        )

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

    try:
        sock.bind(
            (
                "",
                PORT,
            )
        )

    except OSError as exc:
        sock.close()

        raise G1MicError(
            f"绑定 UDP {PORT} 失败: {exc}"
        ) from exc


    membership = struct.pack(
        "4s4s",
        socket.inet_aton(
            GROUP_IP
        ),
        socket.inet_aton(
            interface_ip
        ),
    )

    try:
        sock.setsockopt(
            socket.IPPROTO_IP,
            socket.IP_ADD_MEMBERSHIP,
            membership,
        )

    except OSError as exc:
        sock.close()

        raise G1MicError(
            "加入麦克风多播失败: "
            f"group={GROUP_IP}, "
            f"interface={interface_ip}, "
            f"error={exc}"
        ) from exc


    sock.settimeout(
        0.5
    )

    pcm = bytearray()

    packet_count = 0
    packet_sizes = Counter()
    packet_sources = Counter()

    speech_detected = (
        not wait_for_speech
    )

    speech_started_at = None
    speech_start_rms = None

    waiting_started_at = (
        time.monotonic()
    )

    fixed_started_at = (
        waiting_started_at
    )

    silence_started_at = None
    last_voice_at = None
    last_packet_at = None
    endpoint_reason = "max_duration"
    max_pcm_bytes = int(SAMPLE_RATE * SAMPLE_WIDTH * CHANNELS * (seconds + pre_roll_seconds + 1))

    # G1 常见一个包约 0.16 秒。
    # 不依赖固定包尺寸，
    # 这里保留至少约 0.35 秒的开口前音频。
    pre_roll = deque()

    pre_roll_bytes = 0

    max_pre_roll_bytes = int(
        SAMPLE_RATE
        * CHANNELS
        * SAMPLE_WIDTH
        * max(
            0.0,
            pre_roll_seconds,
        )
    )

    vad_pending = bytearray()
    vad_frame_bytes = SAMPLE_RATE * SAMPLE_WIDTH * CHANNELS // 50  # 20 ms
    consecutive_voice_frames = 0

    try:

        while True:

            if cancel_event is not None and cancel_event.is_set():
                endpoint_reason = "cancelled"
                break

            now = time.monotonic()


            # ---------------------------------------------
            # 旧模式：从调用开始固定录 seconds 秒
            # ---------------------------------------------

            if not wait_for_speech:

                if (
                    now
                    - fixed_started_at
                    >= seconds
                ):
                    break


            # ---------------------------------------------
            # 新模式：先等老人开口
            # ---------------------------------------------

            elif not speech_detected:

                if (
                    now
                    - waiting_started_at
                    >= start_timeout
                ):
                    endpoint_reason = "start_timeout"
                    break


            # ---------------------------------------------
            # 已经开口：从检测到语音后才开始计时
            # ---------------------------------------------

            else:

                if (
                    speech_started_at
                    is not None
                    and now
                    - speech_started_at
                    >= seconds
                ):
                    break


            try:
                data, address = (
                    sock.recvfrom(
                        65535
                    )
                )

            except socket.timeout:
                if last_packet_at is not None and time.monotonic() - last_packet_at >= 2.0:
                    raise G1MicError("G1 microphone stream stopped for 2 seconds")
                continue


            if not data:
                continue

            last_packet_at = time.monotonic()
            if len(pcm) + len(data) > max_pcm_bytes:
                raise G1MicError("G1 microphone PCM exceeded the bounded recording size")


            packet_sources[
                address[0]
            ] += 1

            packet_sizes[
                len(data)
            ] += 1

            packet_count += 1


            # PCM16 必须偶数字节。
            frame = (
                data[:-1]
                if len(data) % 2
                else data
            )

            if not frame:
                continue


            # ---------------------------------------------
            # 旧固定时长模式
            # ---------------------------------------------

            if not wait_for_speech:

                pcm.extend(
                    frame
                )

                continue


            # ---------------------------------------------
            # 简单语音活动检测 VAD
            # ---------------------------------------------

            rms = audioop.rms(
                frame,
                SAMPLE_WIDTH,
            )


            if not speech_detected:

                # 始终保存一小段开口前音频，
                # 避免检测到声音时把第一个字吃掉。
                pre_roll.append(
                    frame
                )

                pre_roll_bytes += (
                    len(frame)
                )

                while (
                    pre_roll
                    and pre_roll_bytes
                    > max_pre_roll_bytes
                ):

                    removed = (
                        pre_roll.popleft()
                    )

                    pre_roll_bytes -= (
                        len(removed)
                    )


                # 按音频时长而非 UDP 包数判断：60 ms 连续声音即可保留短“好”。
                # ponytail: RMS 仍会被持续噪声触发；现场验证不合格时换神经 VAD。
                vad_pending.extend(frame)
                voiced = False
                processed_bytes = len(vad_pending) // vad_frame_bytes * vad_frame_bytes
                for offset in range(0, processed_bytes, vad_frame_bytes):
                    level = audioop.rms(vad_pending[offset:offset + vad_frame_bytes], SAMPLE_WIDTH)
                    consecutive_voice_frames = consecutive_voice_frames + 1 if level >= speech_rms_threshold else 0
                    if consecutive_voice_frames >= 3:
                        voiced = True
                        break
                del vad_pending[:processed_bytes]

                if voiced:

                    speech_detected = True

                    speech_started_at = (
                        time.monotonic()
                    )

                    speech_start_rms = rms
                    last_voice_at = speech_started_at

                    for buffered in pre_roll:
                        pcm.extend(
                            buffered
                        )

                    pre_roll.clear()
                    pre_roll_bytes = 0

                    silence_started_at = None


                continue


            # ---------------------------------------------
            # 老人已经开始说话
            # ---------------------------------------------

            pcm.extend(
                frame
            )


            # 使用略低于启动阈值的结束阈值，
            # 避免声音边缘频繁切换。
            silence_rms_threshold = max(
                180,
                int(
                    speech_rms_threshold
                    * 0.65
                ),
            )


            if (
                rms
                < silence_rms_threshold
            ):

                if silence_started_at is None:

                    silence_started_at = (
                        time.monotonic()
                    )

            else:

                silence_started_at = None
                last_voice_at = time.monotonic()


            spoken_seconds = (
                time.monotonic()
                - speech_started_at
            )


            # 只有已经真正说了一小段后，
            # 才允许静音自动结束。
            if (
                spoken_seconds
                >= min_speech_seconds
                and silence_started_at
                is not None
                and (
                    time.monotonic()
                    - silence_started_at
                    >= silence_timeout
                )
            ):

                endpoint_reason = "silence"
                break


    finally:

        try:
            sock.setsockopt(
                socket.IPPROTO_IP,
                socket.IP_DROP_MEMBERSHIP,
                membership,
            )

        except OSError:
            pass

        sock.close()

    finished_at = time.monotonic()
    if not packet_count and endpoint_reason != "cancelled":
        raise G1MicError("No G1 microphone UDP packets received; silence cannot be inferred")


    # 等待阶段没检测到语音时，
    # 保存最后一点环境声供诊断，
    # 但上层不会送去 ASR。
    if (
        wait_for_speech
        and not speech_detected
        and pre_roll
    ):

        for buffered in pre_roll:
            pcm.extend(
                buffered
            )


    if (
        not pcm
        and not wait_for_speech
    ):

        raise G1MicError(
            "没有收到 G1 麦克风 UDP 数据。"
            f" interface={interface_ip},"
            f" multicast={GROUP_IP}:{PORT}。"
            " 如果 tcpdump 也看不到 5555 数据，"
            "则重点检查 G1 Wake-up Conversation Mode。"
        )


    if len(pcm) % 2:
        pcm = pcm[:-1]


    with wave.open(
        str(output_path),
        "wb",
    ) as wav_file:

        wav_file.setnchannels(
            CHANNELS
        )

        wav_file.setsampwidth(
            SAMPLE_WIDTH
        )

        wav_file.setframerate(
            SAMPLE_RATE
        )

        wav_file.writeframes(
            pcm
        )


    audio_seconds = (
        len(pcm)
        / (
            SAMPLE_RATE
            * CHANNELS
            * SAMPLE_WIDTH
        )
    )


    return {
        "endpoint_reason": endpoint_reason,
        "recording_wall_ms": (finished_at - waiting_started_at) * 1000,
        "speech_start_offset_ms": None if speech_started_at is None else (speech_started_at - waiting_started_at) * 1000,
        "speech_end_monotonic": last_voice_at,
        "speech_end_estimated": last_voice_at is not None,
        "endpoint_delay_ms": None if last_voice_at is None else (finished_at - last_voice_at) * 1000,
        "ok":
            True,

        "path":
            str(
                output_path.resolve()
            ),

        "interface_ip":
            interface_ip,

        "robot_ip":
            ROBOT_IP,

        "multicast":
            f"{GROUP_IP}:{PORT}",

        "packet_count":
            packet_count,

        "packet_sources":
            dict(
                packet_sources
            ),

        "packet_sizes":
            dict(
                packet_sizes
            ),

        "pcm_bytes":
            len(pcm),

        "audio_seconds":
            round(
                audio_seconds,
                3,
            ),

        "sample_rate":
            SAMPLE_RATE,

        "channels":
            CHANNELS,

        "sample_width":
            SAMPLE_WIDTH,

        "wait_for_speech":
            wait_for_speech,

        "speech_detected":
            speech_detected,

        "speech_start_rms":
            speech_start_rms,

        "speech_rms_threshold":
            speech_rms_threshold,
    }


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--output",
        default="/tmp/g1_mic_test.wav",
    )

    parser.add_argument(
        "--seconds",
        type=float,
        default=5.0,
    )

    parser.add_argument(
        "--interface-ip",
        default=None,
        help=(
            "中间主机连接 G1 网络的本地IP；"
            "默认自动检测"
        ),
    )

    args = parser.parse_args()

    interface_ip = (
        args.interface_ip
        or detect_interface_ip()
    )

    print(
        "G1 robot IP:",
        ROBOT_IP,
    )

    print(
        "Local interface IP:",
        interface_ip,
    )

    print(
        "Microphone multicast:",
        f"{GROUP_IP}:{PORT}",
    )

    print()

    print(
        f"正在录制 {args.seconds:.1f} 秒..."
    )

    result = record_g1_wav(
        args.output,
        seconds=args.seconds,
        interface_ip=
            interface_ip,
    )

    print()
    print("录音成功")

    for key, value in result.items():
        print(
            f"{key}: {value}"
        )


if __name__ == "__main__":
    main()
