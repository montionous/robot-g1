"""Bounded, append-only journal for one elder companion session.

The journal is deliberately independent from the dialogue stdout contract.  It
uses only the standard library so a recording failure can be reported without
changing speech or robot control.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any, Callable, Iterator, TextIO
import uuid


SCHEMA_VERSION = "care_session_record_v1"
MAX_LINE_BYTES = 64 * 1024
MAX_FILE_BYTES = 8 * 1024 * 1024
TERMINAL_RESERVE_BYTES = 2 * MAX_LINE_BYTES
MAX_ELDERLY_ID = 2**63 - 1
RECORD_KINDS = frozenset(
    {"session_start", "console", "receipt", "session_end", "recording_gap"}
)
END_STATUSES = frozenset(
    {"completed", "no_event", "failed", "interrupted", "incomplete"}
)


class RecordingError(RuntimeError):
    """A journal setup or append operation failed."""


def validate_elderly_id(value: Any) -> int:
    """Return a canonical ID or raise a concise validation error."""
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError("elderly_id must be a positive decimal integer")
    text = str(value)
    if not text.isdecimal() or not text:
        raise ValueError("elderly_id must be a positive decimal integer")
    number = int(text)
    if not 1 <= number <= MAX_ELDERLY_ID:
        raise ValueError("elderly_id must be between 1 and 2^63-1")
    return number


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


_CURRENT: ContextVar["CompanionRecorder | None"] = ContextVar(
    "care_companion_recorder", default=None
)


@contextmanager
def recording_context(recorder: "CompanionRecorder | None") -> Iterator[None]:
    token = _CURRENT.set(recorder)
    try:
        yield
    finally:
        _CURRENT.reset(token)


def record_console(payload: dict[str, Any]) -> bool:
    recorder = _CURRENT.get()
    return recorder.record("console", payload) if recorder is not None else False


def record_receipt(payload: dict[str, Any]) -> bool:
    recorder = _CURRENT.get()
    return recorder.record("receipt", payload) if recorder is not None else False


def current_recorder() -> "CompanionRecorder | None":
    return _CURRENT.get()


def _record_metadata(value: Any, keys: tuple[str, ...]) -> dict[str, Any]:
    """Copy small JSON metadata without retaining transient audio paths."""
    if not isinstance(value, dict):
        return {}
    return {key: value[key] for key in keys if key in value}


def record_asr(
    scene: str,
    text: str,
    *,
    source: str = "listen",
    result: Any = None,
) -> bool:
    """Keep the elder's recognized text in the private journal only."""
    payload: dict[str, Any] = {
        "kind": "companion_interaction_asr",
        "scene": scene,
        "source": source,
        "text": text,
    }
    payload.update(
        _record_metadata(
            result,
            (
                "asr_ms",
                "asr_wall_ms",
                "total_ms",
                "queue_ms",
                "ready_monotonic",
                "emotion",
                "emotion_zh",
                "recording",
                "speech_detected",
            ),
        )
    )
    return record_console(payload)


def _playback_observation(result: Any) -> str:
    """Describe the returned software fact without claiming audible sound."""
    if not isinstance(result, dict):
        return "unknown"
    status = result.get("status")
    if isinstance(status, str) and status:
        return status
    play_result = result.get("play_result")
    if isinstance(play_result, (int, float)) and not isinstance(play_result, bool):
        return f"play_result:{play_result}"
    return "returned"


def record_speech_request(
    scene: str,
    text: str,
    *,
    source: str = "speak",
) -> bool:
    """Record the text before a TTS/playback call is attempted."""
    return record_console(
        {
            "kind": "companion_interaction_speech",
            "scene": scene,
            "source": source,
            "text": text,
            "delivery_status": "requested",
        }
    )


def record_speech_receipt(
    scene: str,
    text: str,
    *,
    result: Any = None,
    source: str = "speak",
    error: BaseException | None = None,
) -> bool:
    """Record the returned software fact without claiming audible sound."""
    receipt: dict[str, Any] = {
        "kind": "companion_interaction_speech_receipt",
        "scene": scene,
        "source": source,
        "text_characters": len(text),
        "playback_status": _playback_observation(result),
        "playback_observation": "software_return",
        "physical_heard": "unknown",
    }
    if isinstance(result, dict):
        receipt["result"] = result
    if error is not None:
        receipt["error"] = repr(error)
    return record_receipt(receipt)


def recording_mark_interrupted(error: str = "keyboard_interrupt") -> None:
    recorder = _CURRENT.get()
    if recorder is not None:
        recorder.mark_interrupted(error)


def recording_mark_failed(error: BaseException | str) -> None:
    recorder = _CURRENT.get()
    if recorder is not None:
        recorder.mark_failed(str(error)[:2000])


def _recording_summary(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return result
    return {}


def run_recorded_scene(
    runner: Callable[[], Any],
    *,
    record_log: Path | str | None,
    elderly_id: int | str,
    record_mode: str,
    source_scene: str,
    scene: str = "dialogue",
    stderr: TextIO | None = None,
) -> Any:
    """Run one scenario under a bounded recorder, preserving old exceptions."""
    recorder: CompanionRecorder | None = None
    if record_log is not None:
        try:
            recorder = open_recorder(
                record_log,
                elderly_id=elderly_id,
                mode=record_mode,
                scene=scene,
                source_scene=source_scene,
                stderr=stderr,
            )
        except (RecordingError, OSError, ValueError) as error:
            stream = stderr or sys.stderr
            print(
                f"care_session_recording_disabled: {error}",
                file=stream,
                flush=True,
            )

    status = "failed"
    error_text: str | None = None
    result: Any = None
    try:
        with recording_context(recorder):
            result = runner()
        status = "completed"
        return result
    except KeyboardInterrupt:
        status = "interrupted"
        error_text = "keyboard_interrupt"
        if recorder is not None:
            recorder.mark_interrupted(error_text)
        raise
    except BaseException as error:
        status = "failed"
        error_text = str(error) or error.__class__.__name__
        raise
    finally:
        if recorder is not None:
            recorder.finish(
                status,
                _recording_summary(result),
                error=error_text,
            )


class CompanionRecorder:
    """Write one independent journal and retain a visible incomplete state."""

    def __init__(
        self,
        path: Path | str,
        *,
        elderly_id: int | str,
        mode: str = "live",
        stderr: TextIO | None = None,
        session_id: str | None = None,
    ) -> None:
        number = validate_elderly_id(elderly_id)
        if mode not in {"live", "replay"}:
            raise ValueError("record mode must be live or replay")
        self.path = Path(path)
        self.elderly_id = str(number)
        self.mode = mode
        self.session_id = session_id or uuid.uuid4().hex
        if len(self.session_id) != 32 or any(
            character not in "0123456789abcdef" for character in self.session_id
        ):
            raise ValueError("session_id must be uuidhex")
        self.stderr = stderr or sys.stderr
        self._stream: TextIO | None = None
        self._size = 0
        self._seq = 0
        self._closed = False
        self._terminal_written = False
        self._failed = False
        self._gap_written = False
        self._forced_status: str | None = None
        self._forced_error: str | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            self._stream = os.fdopen(descriptor, "w", encoding="utf-8", newline="")
        except (OSError, UnicodeError, ValueError, AttributeError) as error:
            raise RecordingError(f"cannot create recording journal {self.path}: {error}") from error

    @property
    def incomplete(self) -> bool:
        return self._failed or self._gap_written or not self._terminal_written

    @property
    def sequence(self) -> int:
        return self._seq

    def _warn(self, message: str) -> None:
        print(f"care_session_recording_error: {message}", file=self.stderr, flush=True)

    def _envelope(self, kind: str, payload: dict[str, Any]) -> bytes:
        if kind not in RECORD_KINDS:
            raise RecordingError(f"record kind invalid: {kind}")
        if not isinstance(payload, dict):
            raise RecordingError("record payload must be an object")
        envelope = {
            "schema_version": SCHEMA_VERSION,
            "record_id": uuid.uuid4().hex,
            "session_id": self.session_id,
            "elderly_id": self.elderly_id,
            "seq": self._seq + 1,
            "recorded_at": _utc_now(),
            "mode": self.mode,
            "kind": kind,
            "payload": payload,
        }
        try:
            encoded = (
                json.dumps(
                    envelope,
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=(",", ":"),
                )
                + "\n"
            ).encode("utf-8")
        except (TypeError, ValueError, UnicodeError, RecursionError) as error:
            raise RecordingError(f"record encoding failed: {error}") from error
        if len(encoded) > MAX_LINE_BYTES:
            raise RecordingError(f"record line exceeds {MAX_LINE_BYTES} bytes")
        return encoded

    def _write_line(self, encoded: bytes, *, terminal: bool = False) -> None:
        if self._stream is None or self._closed:
            raise RecordingError("recording journal is closed")
        limit = MAX_FILE_BYTES if terminal else MAX_FILE_BYTES - TERMINAL_RESERVE_BYTES
        if self._size + len(encoded) > limit:
            raise RecordingError(f"recording journal exceeds {MAX_FILE_BYTES} bytes")
        try:
            self._stream.write(encoded.decode("utf-8"))
            self._stream.flush()
            os.fsync(self._stream.fileno())
        except (OSError, UnicodeError, ValueError, AttributeError) as error:
            raise RecordingError(f"recording journal write failed: {error}") from error
        self._size += len(encoded)
        self._seq += 1

    def _write_best_effort(self, kind: str, payload: dict[str, Any], *, terminal: bool = False) -> bool:
        try:
            encoded = self._envelope(kind, payload)
            self._write_line(encoded, terminal=terminal)
            return True
        except RecordingError as error:
            self._warn(str(error))
            return False

    def start(self, scene: str, *, source_scene: str | None = None) -> bool:
        if self._seq or self._closed:
            raise RecordingError("session_start must be the first journal record")
        if scene not in {"dialogue", "motion"}:
            raise ValueError("session scene must be dialogue or motion")
        payload: dict[str, Any] = {"scene": scene}
        if source_scene:
            payload["source_scene"] = source_scene
        return self.record("session_start", payload)

    def _gap(self, source_kind: str, error: str) -> None:
        if self._gap_written or self._closed:
            return
        self._gap_written = self._write_best_effort(
            "recording_gap",
            {"source_kind": source_kind, "error": error},
            terminal=True,
        )

    def record(self, kind: str, payload: dict[str, Any]) -> bool:
        if self._closed or self._terminal_written or self._failed:
            return False
        try:
            encoded = self._envelope(kind, payload)
            self._write_line(encoded)
            return True
        except RecordingError as error:
            self._failed = True
            self._warn(str(error))
            self._gap(kind, str(error))
            return False

    def finish(
        self,
        status: str,
        summary: dict[str, Any] | None = None,
        *,
        error: str | None = None,
    ) -> bool:
        if self._closed or self._terminal_written:
            return False
        if status not in END_STATUSES:
            raise ValueError(f"session end status invalid: {status}")
        if self._forced_status is not None:
            status = self._forced_status
            if error is None:
                error = self._forced_error
        if self._failed or self._gap_written:
            status = "incomplete"
        payload: dict[str, Any] = {"status": status, "summary": summary or {}}
        if error:
            payload["error"] = error
        ok = self._write_best_effort("session_end", payload, terminal=True)
        if ok:
            self._terminal_written = True
        else:
            self._failed = True
        self.close()
        return ok

    def mark_interrupted(self, error: str = "keyboard_interrupt") -> None:
        if self._terminal_written or self._closed:
            return
        self._forced_status = "interrupted"
        self._forced_error = error

    def mark_failed(self, error: str) -> None:
        if self._terminal_written or self._closed:
            return
        self._forced_status = 'failed'
        self._forced_error = error
        self.record('receipt', {'kind':'scene_error','status':'failed','error':error})

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        stream, self._stream = self._stream, None
        if stream is None:
            return
        try:
            stream.flush()
            os.fsync(stream.fileno())
        except (OSError, ValueError, AttributeError) as error:
            self._warn(f"recording journal close failed: {error}")
        finally:
            try:
                stream.close()
            except (OSError, ValueError, AttributeError) as error:
                self._warn(f"recording journal close failed: {error}")


def open_recorder(
    path: Path | str,
    *,
    elderly_id: int | str,
    mode: str,
    scene: str,
    source_scene: str | None = None,
    stderr: TextIO | None = None,
) -> CompanionRecorder:
    recorder = CompanionRecorder(path, elderly_id=elderly_id, mode=mode, stderr=stderr)
    recorder.start(scene, source_scene=source_scene)
    return recorder
