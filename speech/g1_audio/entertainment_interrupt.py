"""A bounded listener owned by one interruptible story/joke PCM process."""

from __future__ import annotations

import json
import multiprocessing
import os
from pathlib import Path
from queue import Empty
import re
import signal
import subprocess
import tempfile
import time
from typing import Any

from g1_audio.g1_mic_recorder import record_g1_wav
from speech_client import SpeechClient


ASR_TIMEOUT_SECONDS = 4.0
STOP_GRACE_SECONDS = 12.0  # In-flight PlayStream and Stop each have a 3s RPC timeout.
MAX_RECEIPT_BYTES = 65536
_PUNCTUATION = re.compile(r"[\s，,。.!！?？、；;：:]+")
_COMMAND = re.compile(
    r"(?:(?:先|再|然后)?(?:停一下|停一停|暂停|别讲了|不要讲了|不用讲了|别说了|不要说了|"
    r"别念了|别播了|我不想听了|停止播放|停止播报|停止讲故事|停止讲笑话|"
    r"换一个(?:故事|笑话)?|换个(?:故事|笑话)))+"
)


def _compact(text: str) -> str:
    return _PUNCTUATION.sub("", text)


def parse_interrupt_command(text: str, narration: str) -> dict[str, str] | None:
    """Accept short directives, rejecting negation, reported speech and known echo."""
    compact = _compact(text.strip())
    if not compact or len(compact) > 32 or compact in _compact(narration):
        return None
    command = re.sub(r"^(?:(?:请|麻烦你|麻烦您|好了|好啦|行了|你|您))+", "", compact)
    command = re.sub(r"(?:(?:吧|呀|啊|好吗|行吗|可以吗|谢谢))+$", "", command)
    if command in {"不聊了", "结束聊天", "今天就聊到这里", "我想安静一会儿"}:
        return {"action": "end_session", "text": text}
    if not _COMMAND.fullmatch(command):
        return None
    return {"action": "replace" if "换" in command else "stop", "text": text}


def _listen_for_interrupt(base_url, headers, narration, audio_dir, rms, done, results):
    # A separate process allows cleanup to release UDP even during a stalled ASR call.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    client = SpeechClient(base_url=base_url, timeout=ASR_TIMEOUT_SECONDS)
    client.headers = headers
    try:
        while not done.is_set():
            with tempfile.NamedTemporaryFile(suffix=".wav", dir=audio_dir, delete=False) as wav:
                path = Path(wav.name)
            try:
                recording = record_g1_wav(
                    path, seconds=3.0, wait_for_speech=True, start_timeout=1.0,
                    silence_timeout=0.4, min_speech_seconds=0.2,
                    speech_rms_threshold=rms, cancel_event=done,
                )
                if done.is_set():
                    return
                if not recording.get("speech_detected"):
                    continue
                response = client.transcribe(path, language="zh")
                if done.is_set():
                    return
                text = response.get("text")
                command = parse_interrupt_command(text, narration) if isinstance(text, str) else None
                if command is not None:
                    results.put_nowait(command)
                    return
            finally:
                path.unlink(missing_ok=True)
    except Exception as error:
        if not done.is_set():
            results.put_nowait({"error": type(error).__name__})


def _start_listener(client, narration, audio_dir, rms):
    context = multiprocessing.get_context("spawn")
    done = context.Event()
    results = context.Queue(maxsize=1)
    process = context.Process(
        target=_listen_for_interrupt,
        args=(client.base_url, dict(client.headers), narration, str(audio_dir), rms, done, results),
    )
    try:
        process.start()
    except Exception:
        results.close()
        results.join_thread()
        raise
    return process, done, results


def _receipts(log) -> list[dict[str, Any]]:
    if os.fstat(log.fileno()).st_size > MAX_RECEIPT_BYTES:
        raise RuntimeError("g1_pcm_bridge_output_limit")
    # pread preserves the child's shared output offset.
    data = os.pread(log.fileno(), MAX_RECEIPT_BYTES, 0).decode("utf-8", errors="replace")
    receipts = []
    for line in data.splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict) and value.get("kind") == "g1_companion_pcm_bridge":
            receipts.append(value)
    return receipts


def _validate_ready(ready, audio_path):
    if (ready.get("wav_path") != audio_path or not isinstance(ready.get("app_name"), str)
            or not ready["app_name"].startswith("companion_pcm_")):
        raise RuntimeError("g1_pcm_bridge_ready_invalid")


def _stop_process(process, ready):
    if process.poll() is not None:
        return
    if ready:
        try:
            process.send_signal(signal.SIGUSR1)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=STOP_GRACE_SECONDS)
            return
        except subprocess.TimeoutExpired:
            pass
    process.terminate()
    try:
        process.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=1.0)


def play_interruptible_wav(
    bridge_path: str, audio_path: str, *, client: SpeechClient, narration: str,
    audio_dir: Path, speech_rms_threshold: int, timeout: float,
) -> dict[str, Any]:
    """Only return an accepted command after this exact stream successfully stops."""
    listener = done = results = monitor_dir = None
    ready = None
    pending = None
    listener_error = None
    signalled = False
    started = time.monotonic()
    deadline = started + timeout
    with tempfile.TemporaryFile() as log:
        process = subprocess.Popen(
            [bridge_path, "--confirm-g1-companion-pcm", "--allow-interrupt", audio_path],
            stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True,
        )
        try:
            while process.poll() is None:
                receipts = _receipts(log)
                if ready is None:
                    ready = next((row for row in receipts if row.get("status") == "ready"), None)
                    if ready is not None:
                        _validate_ready(ready, audio_path)
                        try:
                            monitor_dir = tempfile.TemporaryDirectory(prefix="interrupt-", dir=audio_dir)
                            listener, done, results = _start_listener(
                                client, narration, Path(monitor_dir.name), speech_rms_threshold,
                            )
                        except Exception as error:
                            listener_error = type(error).__name__
                    elif time.monotonic() - started > min(timeout, 10.0):
                        raise RuntimeError("g1_pcm_bridge_ready_timeout")
                if results is not None and not signalled and listener_error is None:
                    try:
                        command = results.get_nowait()
                    except Empty:
                        if listener.exitcode is not None:
                            try:
                                command = results.get(timeout=0.1)
                            except Empty:
                                command = {"error": "listener_exited_without_result"}
                        else:
                            command = None
                    if command is not None:
                        listener_error = command.get("error")
                        if listener_error:
                            done.set()
                        elif command.get("action") in {"stop", "replace", "end_session"}:
                            pending = command
                            try:
                                process.send_signal(signal.SIGUSR1)
                            except ProcessLookupError:
                                pass
                            signalled = True
                            deadline = time.monotonic() + STOP_GRACE_SECONDS
                        else:
                            listener_error = "listener_command_invalid"
                            done.set()
                if time.monotonic() > deadline:
                    raise RuntimeError("g1_pcm_bridge_timeout")
                time.sleep(0.02)
            rows = _receipts(log)
            if ready is None:
                ready = next((row for row in rows if row.get("status") == "ready"), None)
            if ready is not None:
                _validate_ready(ready, audio_path)
            final = next((row for row in reversed(rows) if row.get("status") in
                          {"completed", "interrupted", "failed"}), None)
            if (process.returncode != 0 or ready is None or final is None
                    or final.get("app_name") != ready.get("app_name")
                    or final.get("wav_path") != audio_path
                    or final.get("play_result") != 0 or final.get("stop_result") != 0
                    or final.get("status") == "failed"):
                raise RuntimeError("g1_pcm_bridge_play_or_stop_failed")
            if listener_error:
                final["interrupt_monitor_error"] = listener_error
            if final["status"] == "interrupted":
                if pending is None:
                    raise RuntimeError("g1_pcm_bridge_unexpected_interruption")
                final["interrupt"] = pending
            return final
        finally:
            if done is not None:
                done.set()
            try:
                _stop_process(process, ready is not None)
            finally:
                if listener is not None:
                    listener.join(timeout=0.75)
                    if listener.is_alive():
                        listener.terminate()
                        listener.join(timeout=1.0)
                    if listener.is_alive():
                        listener.kill()
                        listener.join(timeout=1.0)
                    if listener.is_alive():
                        raise RuntimeError("entertainment_listener_cleanup_failed")
                    results.close()
                    results.join_thread()
                if monitor_dir is not None:
                    monitor_dir.cleanup()
