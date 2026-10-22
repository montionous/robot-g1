"""Safe, shared adapter for the G1 companion head LED script.

The LED implementation itself lives in ``scripts/g1_companion_led_test.sh`` on
the robot host.  Speech scenes use this module only at interaction boundaries;
it never imports a robot SDK or sends DDS commands itself.

Physical LED writes are opt-in.  The default ``dry-run`` mode records the
semantic request, while ``execute`` additionally requires the explicit
``--confirm-g1-led-demo`` command-line confirmation.
"""

from __future__ import annotations

import os
import math
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable


REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_LED_SCRIPT = Path(
    os.environ.get(
        "G1_LED_SCRIPT",
        str(REPO_ROOT / "scripts" / "g1_companion_led_test.sh"),
    )
)


def _seconds_from_environment(name: str, default: float) -> float:
    """Read a positive timeout override without making startup fragile."""

    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) and value > 0 else default


# The separately owned wrapper runs an SDK check and CMake on every call.  A
# two-second deadline is too short even when its final LED effect is one-shot.
# Speech execution remains non-blocking because commands run on a worker.
DEFAULT_COMMAND_TIMEOUT = _seconds_from_environment(
    "G1_LED_COMMAND_TIMEOUT", 30.0
)
MEDIA_LED_COMMAND_TIMEOUT = _seconds_from_environment(
    "G1_MEDIA_LED_COMMAND_TIMEOUT", 1140.0
)

INTERRUPT_GRACE_SECONDS = _seconds_from_environment(
    "G1_LED_INTERRUPT_GRACE_SECONDS", 0.75
)
TERMINATE_GRACE_SECONDS = _seconds_from_environment(
    "G1_LED_TERMINATE_GRACE_SECONDS", 0.75
)


class _LedRequestCancelled(Exception):
    """Raised internally after a newer LED state supersedes a running one."""


# These numbers are maintained by the separately owned G1 LED script.  The
# speech layer deliberately uses a small set of stable interaction semantics
# rather than scene-specific numeric literals.
LED_EVENTS: dict[str, dict[str, Any]] = {
    "listening": {
        "effect": 25,
        "label": "正在倾听（高亮青色深呼吸）",
    },
    "processing": {
        "effect": 18,
        "label": "正在处理（处理中脉冲）",
    },
    "confirmation": {
        "effect": 20,
        "label": "等待明确确认（双次回应）",
    },
    "acknowledged": {
        "effect": 19,
        "label": "已接受或已回应（单次回应）",
    },
    "retry": {
        "effect": 14,
        "label": "未识别或需要重试（柔和眨眼）",
    },
    "farewell": {
        "effect": 22,
        "label": "场景结束（告别渐出）",
    },
    "media_music": {
        "effect": 12,
        "label": "音乐播放（琥珀色呼吸）",
        "media": True,
    },
    "media_news": {
        "effect": 10,
        "label": "新闻播放（暖白色呼吸）",
        "media": True,
    },
    "media_opera": {
        "effect": 6,
        "label": "戏曲播放（紫色稳亮）",
        "media": True,
    },
    "off": {
        "effect": 0,
        "label": "熄灭",
    },
}


class RobotLedClient:
    """Translate scene-level LED events into the robot-host script command.

    ``off`` does not invoke the script.  ``dry-run`` prints the request only.
    ``execute`` uses one background worker, so a slow ROS or hardware command
    cannot delay ASR/TTS.  The externally owned wrapper builds before every
    invocation and can keep a dynamic effect alive.  Each invocation therefore
    gets its own process group: a newer state interrupts the old group, and a
    deadline cleans up the wrapper and all of its pipeline children.  Any
    unavailable script or command failure is returned as status data and never
    raises into a speech scene.
    """

    MODES = frozenset({"off", "dry-run", "execute"})

    def __init__(
        self,
        *,
        mode: str = "dry-run",
        confirm_writes: bool = False,
        script_path: Path | str | None = None,
        command_timeout: float = DEFAULT_COMMAND_TIMEOUT,
        runner: Callable[..., Any] | None = None,
    ) -> None:
        normalized_mode = str(mode).strip().lower()
        if normalized_mode not in self.MODES:
            raise ValueError(
                "robot LED mode must be off, dry-run, or execute"
            )

        self.mode = normalized_mode
        self.confirm_writes = bool(confirm_writes)
        self.script_path = Path(
            script_path if script_path is not None else DEFAULT_LED_SCRIPT
        )
        self.command_timeout = float(command_timeout)
        if not math.isfinite(self.command_timeout) or self.command_timeout <= 0:
            raise ValueError("robot LED command timeout must be finite and positive")
        # ``runner`` is intentionally retained for deterministic unit tests
        # and existing callers.  Real executions use the process-group runner
        # below; subprocess.run(timeout=...) only kills the shell wrapper and
        # can leave its CMake or LED pipeline children behind.
        self._runner = runner
        self._last_effect: int | None = None
        self._last_requested_at = 0.0
        self._request_lock = threading.Lock()
        self._pending_request: dict[str, Any] | None = None
        self._worker: threading.Thread | None = None
        self._idle = threading.Event()
        self._idle.set()
        self._last_execution: dict[str, Any] | None = None
        self._active_cancel: threading.Event | None = None
        self._active_effect: int | None = None
        self._active_process: subprocess.Popen[str] | None = None
        self._closed = False

    @staticmethod
    def available_events() -> tuple[str, ...]:
        return tuple(LED_EVENTS)

    def _command_for(self, effect: int, *, media: bool = False) -> list[str]:
        command = [
            "bash",
            str(self.script_path),
            "--confirm-g1-led-demo",
            str(effect),
        ]
        if media:
            command.append("--media")
        return command

    def preview(
        self,
        event: str,
        *,
        source: str | None = None,
    ) -> dict[str, Any]:
        spec = LED_EVENTS.get(str(event).strip().lower())
        if spec is None:
            raise ValueError(f"unknown robot LED event: {event}")

        effect = int(spec["effect"])
        media = bool(spec.get("media"))
        request = {
            "event": str(event).strip().lower(),
            "effect": effect,
            "label": spec["label"],
            "source": str(source).strip() if source else "scene",
            "command": self._command_for(effect, media=media),
            "physical_led_writes": False,
        }
        if media:
            request["timeout_seconds"] = MEDIA_LED_COMMAND_TIMEOUT
        return request

    @staticmethod
    def _print_request(request: dict[str, Any]) -> None:
        print(
            "灯光请求: "
            f"{request['event']} "
            f"(效果 {request['effect']}，{request['label']}) "
            f"source={request['source']}",
            flush=True,
        )

    @staticmethod
    def _output_text(value: Any) -> str:
        if isinstance(value, bytes):
            return value.decode(errors="replace")
        return str(value or "")

    @staticmethod
    def _signal_process_group(
        process: subprocess.Popen[str], signal_number: int
    ) -> None:
        """Signal a wrapper and its CMake/LED pipeline, never this process."""

        try:
            # start_new_session=True makes process.pid the group's PGID.
            # Do this even after the shell wrapper exits: a background build
            # child can still retain stdout and keep communicate() blocked.
            os.killpg(process.pid, signal_number)
        except (ProcessLookupError, PermissionError):
            return
        except OSError:
            # The fallback still protects the direct wrapper on unusual hosts.
            try:
                process.send_signal(signal_number)
            except (OSError, ProcessLookupError):
                return

    def _stop_process_group(self, process: subprocess.Popen[str]) -> str:
        """Give the LED binary a cleanup interrupt, then guarantee reaping."""

        for signal_number, grace in (
            (signal.SIGINT, INTERRUPT_GRACE_SECONDS),
            (signal.SIGTERM, TERMINATE_GRACE_SECONDS),
        ):
            self._signal_process_group(process, signal_number)
            try:
                output, _ = process.communicate(timeout=grace)
                return self._output_text(output)
            except subprocess.TimeoutExpired:
                continue

        self._signal_process_group(process, signal.SIGKILL)
        output, _ = process.communicate()
        return self._output_text(output)

    def _run_process_group(
        self,
        command: list[str],
        cancel: threading.Event,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Run the external wrapper with cancellation-safe child cleanup."""

        process = subprocess.Popen(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        with self._request_lock:
            self._active_process = process

        actual_timeout = self.command_timeout if timeout is None else float(timeout)
        deadline = time.monotonic() + actual_timeout
        try:
            while True:
                if cancel.is_set():
                    self._stop_process_group(process)
                    raise _LedRequestCancelled()

                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    output = self._stop_process_group(process)
                    raise subprocess.TimeoutExpired(
                        command,
                        actual_timeout,
                        output=output,
                    )

                try:
                    output, _ = process.communicate(
                        timeout=min(0.1, remaining)
                    )
                    return subprocess.CompletedProcess(
                        command,
                        int(process.returncode or 0),
                        self._output_text(output),
                    )
                except subprocess.TimeoutExpired:
                    # Re-enter communicate so its internal reader continues
                    # draining build output while we check cancellation.
                    continue
        finally:
            with self._request_lock:
                if self._active_process is process:
                    self._active_process = None

    def _execute_request(
        self,
        request: dict[str, Any],
        cancel: threading.Event,
    ) -> dict[str, Any]:
        """Run one already-authorized command on the LED worker thread."""

        effect = int(request["effect"])

        try:
            if self._runner is None:
                if "timeout_seconds" in request:
                    result = self._run_process_group(
                        request["command"], cancel, timeout=request["timeout_seconds"]
                    )
                else:
                    result = self._run_process_group(request["command"], cancel)
            else:
                result = self._runner(
                    request["command"],
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    timeout=request.get("timeout_seconds", self.command_timeout),
                    check=False,
                )
        except _LedRequestCancelled:
            print(
                "灯光已切换: 新状态已取消上一条 LED 脚本进程组",
                flush=True,
            )
            return {
                "status": "cancelled",
                "event": request["event"],
                "effect": effect,
            }
        except subprocess.TimeoutExpired:
            print(
                "灯光执行失败: LED 脚本超时，已清理其进程组",
                flush=True,
            )
            return {
                "status": "timeout",
                "event": request["event"],
                "effect": effect,
            }
        except (OSError, ValueError) as error:
            print(f"灯光执行失败: {error!r}", flush=True)
            return {
                "status": "executor_error",
                "event": request["event"],
                "effect": effect,
                "error": repr(error),
            }
        except Exception as error:
            # The externally owned script runner must never bring down an
            # elder-facing speech flow, including when a test or wrapper
            # supplies a custom runner.
            print(f"灯光执行失败: {error!r}", flush=True)
            return {
                "status": "executor_error",
                "event": request["event"],
                "effect": effect,
                "error": repr(error),
            }

        output = self._output_text(getattr(result, "stdout", "")).strip()
        if output:
            for line in output.splitlines():
                print(f"灯光执行器: {line}", flush=True)

        returncode = int(getattr(result, "returncode", 1))
        status = "completed" if returncode == 0 else "failed"
        print(
            "灯光完成: "
            f"{request['event']} status={status} returncode={returncode}",
            flush=True,
        )
        return {
            "status": status,
            "event": request["event"],
            "effect": effect,
            "returncode": returncode,
        }

    def _run_pending_requests(self) -> None:
        """Run requests serially; coalesce and preempt obsolete LED effects."""

        while True:
            with self._request_lock:
                request = self._pending_request
                self._pending_request = None

                if request is not None:
                    cancel = threading.Event()
                    self._active_cancel = cancel
                    self._active_effect = int(request["effect"])
                else:
                    cancel = None

            if request is None:
                with self._request_lock:
                    # A new caller may have arrived after the first lock was
                    # released.  If so, continue with that request instead of
                    # ending the worker.
                    if self._pending_request is not None:
                        continue
                    self._worker = None
                    self._idle.set()
                    return

            result = self._execute_request(request, cancel)
            with self._request_lock:
                self._last_execution = result
                if self._active_cancel is cancel:
                    self._active_cancel = None
                    self._active_effect = None

    def wait_for_idle(self, timeout: float | None = None) -> bool:
        """Test/support hook; scenes never wait for LED hardware."""

        return self._idle.wait(timeout)

    def close(self, timeout: float = 2.0) -> bool:
        """Explicitly cancel a live wrapper and reject later LED requests.

        The script's own comment says Ctrl+C is its cleanup path.  Scenes do
        not call this automatically: keeping the worker non-daemon lets a
        final farewell effect finish (or hit its finite command timeout)
        before interpreter shutdown.
        """

        with self._request_lock:
            self._closed = True
            self._pending_request = None
            cancel = self._active_cancel
            worker = self._worker
            if cancel is not None:
                cancel.set()

        if (
            worker is not None
            and worker.is_alive()
            and worker is not threading.current_thread()
        ):
            worker.join(max(0.0, float(timeout)))
        return self._idle.is_set()

    @property
    def last_execution(self) -> dict[str, Any] | None:
        with self._request_lock:
            if self._last_execution is None:
                return None
            return dict(self._last_execution)

    def show(
        self,
        event: str,
        *,
        source: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """Request one semantic LED transition without affecting scene flow."""

        try:
            request = self.preview(event, source=source)
        except ValueError as error:
            print(f"灯光跳过: {error}", flush=True)
            return {"status": "unknown_event", "event": str(event)}

        effect = int(request["effect"])
        now = time.monotonic()

        if self.mode == "off":
            return {
                "status": "off",
                "event": request["event"],
                "effect": effect,
            }

        # A rolling ASR loop can request the same visual state more than once
        # in one short interval.  Suppressing only near duplicates preserves
        # state changes while keeping the script from being launched repeatedly.
        if (
            not force
            and self._last_effect == effect
            and now - self._last_requested_at < 0.75
        ):
            return {
                "status": "deduplicated",
                "event": request["event"],
                "effect": effect,
            }

        self._last_effect = effect
        self._last_requested_at = now
        self._print_request(request)

        if self.mode == "dry-run":
            print("灯光模式: dry-run，未向 G1 写入", flush=True)
            return {"status": "dry_run", **request}

        if not self.confirm_writes:
            print("灯光跳过: 未确认 G1 灯光写入", flush=True)
            return {
                "status": "confirmation_required",
                "event": request["event"],
                "effect": effect,
            }

        if not self.script_path.is_file():
            print(
                "灯光跳过: 未找到 G1 LED 脚本: "
                f"{self.script_path}",
                flush=True,
            )
            return {
                "status": "missing_script",
                "event": request["event"],
                "effect": effect,
                "script_path": str(self.script_path),
            }

        with self._request_lock:
            if self._closed:
                print("灯光跳过: 灯光客户端已关闭", flush=True)
                return {
                    "status": "closed",
                    "event": request["event"],
                    "effect": effect,
                }

            active_cancel = self._active_cancel
            if (
                not force
                and active_cancel is not None
                and self._active_effect == effect
            ):
                return {
                    "status": "active",
                    "event": request["event"],
                    "effect": effect,
                }

            # If the current command is slow, a later state such as farewell
            # supersedes an obsolete listening/processing effect instead of
            # creating an unbounded queue.  The real process-group runner sees
            # this cancellation within 100ms and cleans its wrapper children.
            self._pending_request = request
            self._idle.clear()

            if active_cancel is not None:
                active_cancel.set()

            worker = self._worker
            if worker is None or not worker.is_alive():
                worker = threading.Thread(
                    target=self._run_pending_requests,
                    name="g1-led-effect",
                    # Keep the process alive through a final farewell request.
                    # The process-group runner gives the external wrapper a
                    # finite deadline, so this cannot leave an orphaned CMake
                    # or LED process behind at interpreter shutdown.
                    daemon=False,
                )
                self._worker = worker
                worker.start()

        return {
            "status": "started",
            **request,
        }


def add_robot_led_arguments(parser: Any) -> None:
    """Add the shared, explicit opt-in CLI arguments to a scene parser."""

    parser.add_argument(
        "--robot-leds",
        choices=("off", "dry-run", "execute"),
        default="dry-run",
        help="机器人头灯模式；默认 dry-run，不向 G1 写入",
    )
    parser.add_argument(
        "--confirm-g1-led-demo",
        action="store_true",
        help=(
            "确认允许执行 G1 头灯脚本；"
            "仅与 --robot-leds execute 一起使用"
        ),
    )


def validate_robot_led_arguments(parser: Any, args: Any) -> None:
    """Keep the execute confirmation contract uniform across every scene."""

    if args.robot_leds == "execute" and not args.confirm_g1_led_demo:
        parser.error(
            "--robot-leds execute requires --confirm-g1-led-demo"
        )
    if args.confirm_g1_led_demo and args.robot_leds != "execute":
        parser.error(
            "--confirm-g1-led-demo requires --robot-leds execute"
        )
