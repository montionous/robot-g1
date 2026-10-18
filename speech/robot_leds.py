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
    "off": {
        "effect": 0,
        "label": "熄灭",
    },
}


class RobotLedClient:
    """Translate scene-level LED events into the robot-host script command.

    ``off`` does not invoke the script.  ``dry-run`` prints the request only.
    ``execute`` uses one background worker, so a slow ROS or hardware command
    cannot delay ASR/TTS.  Requests remain ordered and, while a command is in
    progress, only the newest pending effect is retained.  Any unavailable
    script or command failure is returned as status data and never raises into
    a speech scene.
    """

    MODES = frozenset({"off", "dry-run", "execute"})

    def __init__(
        self,
        *,
        mode: str = "dry-run",
        confirm_writes: bool = False,
        script_path: Path | str | None = None,
        command_timeout: float = 2.0,
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
        self._runner = runner or subprocess.run
        self._last_effect: int | None = None
        self._last_requested_at = 0.0
        self._request_lock = threading.Lock()
        self._pending_request: dict[str, Any] | None = None
        self._worker: threading.Thread | None = None
        self._idle = threading.Event()
        self._idle.set()
        self._last_execution: dict[str, Any] | None = None

    @staticmethod
    def available_events() -> tuple[str, ...]:
        return tuple(LED_EVENTS)

    def _command_for(self, effect: int) -> list[str]:
        return [
            "bash",
            str(self.script_path),
            "--confirm-g1-led-demo",
            str(effect),
        ]

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
        return {
            "event": str(event).strip().lower(),
            "effect": effect,
            "label": spec["label"],
            "source": str(source).strip() if source else "scene",
            "command": self._command_for(effect),
            "physical_led_writes": False,
        }

    @staticmethod
    def _print_request(request: dict[str, Any]) -> None:
        print(
            "灯光请求: "
            f"{request['event']} "
            f"(效果 {request['effect']}，{request['label']}) "
            f"source={request['source']}",
            flush=True,
        )

    def _execute_request(
        self,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        """Run one already-authorized command on the LED worker thread."""

        effect = int(request["effect"])

        try:
            result = self._runner(
                request["command"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=self.command_timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            print("灯光执行失败: LED 脚本超时", flush=True)
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

        output = str(getattr(result, "stdout", "") or "").strip()
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
        """Run requests serially; coalesce updates that arrive while busy."""

        while True:
            with self._request_lock:
                request = self._pending_request
                self._pending_request = None

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

            result = self._execute_request(request)
            with self._request_lock:
                self._last_execution = result

    def wait_for_idle(self, timeout: float | None = None) -> bool:
        """Test/support hook; scenes never wait for LED hardware."""

        return self._idle.wait(timeout)

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
            # If the current command is slow, a later state such as farewell
            # supersedes an obsolete listening/processing effect instead of
            # creating an unbounded queue.
            self._pending_request = request
            self._idle.clear()

            worker = self._worker
            if worker is None or not worker.is_alive():
                worker = threading.Thread(
                    target=self._run_pending_requests,
                    name="g1-led-effect",
                    daemon=True,
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
