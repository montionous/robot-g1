#!/usr/bin/env python3
"""陪伴倾听邀请的官方自定义 ArmAction 执行器。

只消费 `emotion_dialogue_custom_action_request`，白名单动作名 `open_palm_invite`。
官方 Python `G1ArmActionClient.ExecuteAction` 目前只有 int 重载；本执行器按 C++
`ExecuteAction(string)` 调用自定义示教 API 7108。7108 立即返回后，只读 `rt/lowstate`
手臂先离身 ≥ 0.135 rad 但保持闭手，伸到邀请位 ≥ 0.25 rad 后才缓慢张开右侧 Dex3 的四个指节，三路拇指保持实测姿态；
回程实际开始或录制动作结束才闭手。不取消已开始的示教，也不调用 `StopCustomAction`。
任何写入都需要 `--confirm-g1-companion-listen-invite-executor`。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
import time
from pathlib import Path
from typing import Any, Callable, TextIO


DEFAULT_INTERFACE = "enp3s0"
REQUEST_KIND = "emotion_dialogue_custom_action_request"
WHITELISTED_ACTION_NAMES = frozenset({"open_palm_invite"})
# Official C++: unitree/robot/g1/arm/g1_arm_action_api.hpp
ROBOT_API_ID_ARM_ACTION_EXECUTE_CUSTOM_ACTION = 7108
APP_INVITE_DURATION_SECONDS = 12.8
INVITE_CLEARANCE_TIMEOUT_SECONDS = 3.0
# 0.1268 rad 曾在手臂贴近躯干时触发；0.135 只作为已离身的闭手安全边界。
INVITE_FINGER_OPEN_DELTA_RAD = 0.135
INVITE_FINGER_OPEN_POSITION_DELTA_RAD = 0.25
INVITE_OPEN_POSITION_TIMEOUT_SECONDS = 6.0
INVITE_OPEN_RAMP_SECONDS = 0.8
_MOTION_MODULE: Any | None = None


class CustomActionExecutorError(RuntimeError):
    """Stable error code for the listen-invite custom-action boundary."""


def load_motion_executor() -> Any:
    """Load the wave/clap executor so invite reuses its Dex3 open/close recipe."""
    global _MOTION_MODULE
    if _MOTION_MODULE is not None:
        return _MOTION_MODULE
    path = Path(__file__).resolve().with_name("g1_elder_companion_motion_executor.py")
    spec = importlib.util.spec_from_file_location("g1_elder_companion_motion_executor", path)
    if spec is None or spec.loader is None:
        raise CustomActionExecutorError("motion_executor_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _MOTION_MODULE = module
    return module


def confirmed_custom_action_from_line(line: str) -> str | None:
    """Return the whitelist action name from one confirmed JSONL request row."""
    try:
        row = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(row, dict):
        return None
    if row.get("kind") != REQUEST_KIND or row.get("status") != "confirmed":
        return None
    action_name = row.get("action_name")
    if isinstance(action_name, str) and action_name in WHITELISTED_ACTION_NAMES:
        return action_name
    return None


class OfficialCustomArmAction:
    """官方 G1ArmActionClient 自定义示教动作薄封装。"""

    def __init__(self, interface: str = DEFAULT_INTERFACE) -> None:
        motion = load_motion_executor()
        motion.ensure_channel_factory(interface)
        from unitree_sdk2py.g1.arm.g1_arm_action_client import G1ArmActionClient

        self._client = G1ArmActionClient()
        self._client.Init()
        self._client._RegistApi(ROBOT_API_ID_ARM_ACTION_EXECUTE_CUSTOM_ACTION, 0)

    def execute_custom(self, action_name: str) -> int:
        if not isinstance(action_name, str) or action_name not in WHITELISTED_ACTION_NAMES:
            raise CustomActionExecutorError("action_name_not_whitelisted")
        parameter = json.dumps({"action_name": action_name}, ensure_ascii=False)
        code, _data = self._client._Call(ROBOT_API_ID_ARM_ACTION_EXECUTE_CUSTOM_ACTION, parameter)
        return int(code)


def _emit(output: Callable[[dict[str, Any]], None], row: dict[str, Any]) -> None:
    output(row)


def overlay_open_hands(
    *,
    output: Callable[[dict[str, Any]], None],
    monitor_factory: Callable[[], Any],
    opener_factory: Callable[[], Any],
    arm_monitor_factory: Callable[[], Any] | None = None,
    clearance_wait: Callable[[Callable[[], bool]], dict[str, Any]] | None = None,
    return_wait: Callable[[Callable[[], bool]], dict[str, Any]] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    play_seconds: float = APP_INVITE_DURATION_SECONDS,
    clearance_timeout_seconds: float = INVITE_CLEARANCE_TIMEOUT_SECONDS,
    ramp_seconds: float | None = None,
    hold_seconds: float | None = None,
    settle_seconds: float | None = None,
    close_ramp_seconds: float | None = None,
) -> None:
    """Open only the right fingers after the recorded invite reaches its outward pose."""
    motion = load_motion_executor()
    if ramp_seconds is None:
        ramp_seconds = INVITE_OPEN_RAMP_SECONDS
    if hold_seconds is None:
        hold_seconds = motion.OPEN_HOLD_SECONDS
    if settle_seconds is None:
        settle_seconds = motion.OPEN_SETTLE_SECONDS
    if close_ramp_seconds is None:
        close_ramp_seconds = motion.CLOSE_RAMP_SECONDS
    started = monotonic()

    def is_running() -> bool:
        return monotonic() < started + max(0.0, play_seconds)

    origin: list[float] | None = None
    arm_monitor: Any | None = None
    wait_clearance = clearance_wait
    wait_invite_pose = clearance_wait
    if wait_clearance is None:
        if arm_monitor_factory is None:
            _emit(output, {"kind": "emotion_motion_open_skipped", "reason": "arm_monitor_missing"})
            return
        arm_monitor = arm_monitor_factory()
        origin = arm_monitor.snapshot(motion.ARM_STATE_SNAPSHOT_TIMEOUT_SECONDS)

        def wait_clearance(running: Callable[[], bool]) -> dict[str, Any]:
            if origin is None:
                return {"cleared": False, "reason": "arm_state_unavailable", "max_delta": 0.0}
            return motion.wait_for_arm_clearance(
                snapshot=lambda: arm_monitor.snapshot(motion.ARM_STATE_SNAPSHOT_TIMEOUT_SECONDS),
                is_running=running,
                origin=origin,
                timeout_seconds=clearance_timeout_seconds,
                delta_rad=INVITE_FINGER_OPEN_DELTA_RAD,
                sleep=sleep,
                monotonic=monotonic,
            )

        def wait_invite_pose(running: Callable[[], bool]) -> dict[str, Any]:
            if origin is None:
                return {"cleared": False, "reason": "arm_state_unavailable", "max_delta": 0.0}
            return motion.wait_for_arm_clearance(
                snapshot=lambda: arm_monitor.snapshot(motion.ARM_STATE_SNAPSHOT_TIMEOUT_SECONDS),
                is_running=running,
                origin=origin,
                timeout_seconds=min(
                    INVITE_OPEN_POSITION_TIMEOUT_SECONDS,
                    max(0.0, started + max(0.0, play_seconds) - monotonic()),
                ),
                delta_rad=INVITE_FINGER_OPEN_POSITION_DELTA_RAD,
                sleep=sleep,
                monotonic=monotonic,
            )

    clearance = wait_clearance(is_running)
    raw_delta = clearance.get("max_delta")
    extended = (
        bool(clearance.get("cleared"))
        and isinstance(raw_delta, (int, float))
        and math.isfinite(raw_delta)
        and raw_delta >= INVITE_FINGER_OPEN_DELTA_RAD
    )
    reason = clearance.get("reason")
    if (
        isinstance(raw_delta, (int, float))
        and math.isfinite(raw_delta)
        and 0.0 < raw_delta < INVITE_FINGER_OPEN_DELTA_RAD
    ):
        reason = "arm_not_extended"
    _emit(
        output,
        {
            "kind": "emotion_motion_arm_clearance",
            "cleared": extended,
            "reason": reason,
            "max_delta": raw_delta,
            "required_delta": INVITE_FINGER_OPEN_DELTA_RAD,
        },
    )
    if not extended or not is_running():
        skip_reason = "action_finished" if not is_running() else str(reason or "not_cleared")
        _emit(output, {"kind": "emotion_motion_open_skipped", "reason": skip_reason})
        return

    if wait_invite_pose is None:
        _emit(output, {"kind": "emotion_motion_open_skipped", "reason": "invite_pose_wait_missing"})
        return
    invite_pose = wait_invite_pose(is_running)
    raw_invite_delta = invite_pose.get("max_delta")
    invitation_ready = (
        bool(invite_pose.get("cleared"))
        and isinstance(raw_invite_delta, (int, float))
        and math.isfinite(raw_invite_delta)
        and raw_invite_delta >= INVITE_FINGER_OPEN_POSITION_DELTA_RAD
    )
    invite_reason = invite_pose.get("reason")
    if (
        isinstance(raw_invite_delta, (int, float))
        and math.isfinite(raw_invite_delta)
        and 0.0 < raw_invite_delta < INVITE_FINGER_OPEN_POSITION_DELTA_RAD
    ):
        invite_reason = "invite_pose_not_reached"
    _emit(
        output,
        {
            "kind": "emotion_motion_hand_open_clearance",
            "cleared": invitation_ready,
            "reason": invite_reason,
            "max_delta": raw_invite_delta,
            "required_delta": INVITE_FINGER_OPEN_POSITION_DELTA_RAD,
        },
    )
    if not invitation_ready or not is_running():
        skip_reason = "action_finished" if not is_running() else str(invite_reason or "not_cleared")
        _emit(output, {"kind": "emotion_motion_open_skipped", "reason": skip_reason})
        return

    monitor = None
    opener = None
    try:
        monitor = monitor_factory()
        opener = opener_factory()
        state = monitor.wait_for_state(2.0)
        opened = motion.run_open_hands(
            monitor,
            opener,
            state,
            output,
            sleep=sleep,
            monotonic=monotonic,
            ramp_seconds=ramp_seconds,
            hold_seconds=hold_seconds,
            settle_seconds=settle_seconds,
            continue_open=is_running,
            target_factory=motion.open_fingers_preserving_thumbs_targets,
            preserve_thumbs=True,
            command_hands=("right",),
        )
        opened_right = motion.finger_flexion_rad(opened["right"])
        right_targets = motion.open_fingers_preserving_thumbs_targets(
            state["right"], ramp_seconds, ramp_seconds
        )
        _emit(
            output,
            {
                "kind": "emotion_motion_hand_state",
                "phase": "after_open",
                "flexion_left": round(motion.finger_flexion_rad(opened["left"]), 4),
                "flexion_right": round(opened_right, 4),
                "closed_left": motion.hand_closed(motion.finger_flexion_rad(opened["left"])),
                "closed_right": motion.hand_closed(opened_right),
                "commanded_hands": ["right"],
            },
        )
        if opened_right >= motion.OPEN_CONFIRM_FINGER_FLEXION_RAD:
            _emit(
                output,
                {
                    "kind": "emotion_motion_open_feedback_pending",
                    "reason": "hands_not_open",
                },
            )
        opener.start_hold_open(None, right_targets)
        if return_wait is not None:
            returning = return_wait(is_running)
        elif origin is not None and arm_monitor is not None:
            returning = motion.wait_for_arm_return(
                snapshot=lambda: arm_monitor.snapshot(motion.ARM_STATE_SNAPSHOT_TIMEOUT_SECONDS),
                is_running=is_running,
                origin=origin,
                timeout_seconds=max(0.0, started + max(0.0, play_seconds) - monotonic()),
                sleep=sleep,
                monotonic=monotonic,
            )
        else:
            returning = {
                "returning": True,
                "reason": "no_arm_monitor",
                "peak": 0.0,
                "max_delta": 0.0,
            }
        _emit(
            output,
            {
                "kind": "emotion_motion_arm_return",
                "returning": bool(returning.get("returning")),
                "reason": returning.get("reason"),
                "peak": returning.get("peak"),
                "max_delta": returning.get("max_delta"),
            },
        )
    except (CustomActionExecutorError, motion.MotionExecutorError, OSError) as error:
        _emit(output, {"kind": "emotion_motion_open_skipped", "reason": str(error)})
    finally:
        if opener is None:
            return
        opener.stop_hold_open(close_publishers=False)
        try:
            if monitor is not None:
                motion.close_hands_at_rest(
                    monitor,
                    opener,
                    output,
                    sleep=sleep,
                    monotonic=monotonic,
                    ramp_seconds=close_ramp_seconds,
                    settle_seconds=settle_seconds,
                    command_hands=("right",),
                )
        except (motion.MotionExecutorError, OSError) as error:
            _emit(output, {"kind": "emotion_motion_close_skipped", "reason": str(error)})
        opener.close_publishers()


def write_custom_action_output(
    row: dict[str, Any],
    *,
    stdout: TextIO | None = None,
    jsonl_output: Path | None = None,
) -> None:
    if stdout is None:
        stdout = sys.stdout
    line = json.dumps(row, ensure_ascii=False, separators=(",", ":"))
    print(line, file=stdout, flush=True)
    if jsonl_output is not None:
        with jsonl_output.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def run_executor(
    args: argparse.Namespace,
    *,
    action_factory: Callable[[], Any],
    output: Callable[[dict[str, Any]], None],
    stream: TextIO | None = None,
    monitor_factory: Callable[[], Any] | None = None,
    opener_factory: Callable[[], Any] | None = None,
    arm_monitor_factory: Callable[[], Any] | None = None,
    clearance_wait: Callable[[Callable[[], bool]], dict[str, Any]] | None = None,
    return_wait: Callable[[Callable[[], bool]], dict[str, Any]] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    play_seconds: float = APP_INVITE_DURATION_SECONDS,
    ramp_seconds: float | None = None,
    hold_seconds: float | None = None,
    settle_seconds: float | None = None,
    close_ramp_seconds: float | None = None,
) -> int:
    source = stream if stream is not None else sys.stdin
    executed = False
    rpc_code = 0
    for raw in source:
        action_name = confirmed_custom_action_from_line(raw)
        if action_name is None or executed:
            continue
        action = action_factory()
        rpc_code = int(action.execute_custom(action_name))
        executed = True
        _emit(
            output,
            {
                "kind": "emotion_custom_action_execute",
                "action_name": action_name,
                "status": "accepted" if rpc_code == 0 else "rpc_failed",
                "rpc_code": rpc_code,
                "physical_actions_emitted": rpc_code == 0,
            },
        )
        if rpc_code == 0 and monitor_factory is not None and opener_factory is not None:
            overlay_open_hands(
                output=output,
                monitor_factory=monitor_factory,
                opener_factory=opener_factory,
                arm_monitor_factory=arm_monitor_factory,
                clearance_wait=clearance_wait,
                return_wait=return_wait,
                sleep=sleep,
                monotonic=monotonic,
                play_seconds=play_seconds,
                ramp_seconds=ramp_seconds,
                hold_seconds=hold_seconds,
                settle_seconds=settle_seconds,
                close_ramp_seconds=close_ramp_seconds,
            )
        elif rpc_code == 0:
            _emit(
                output,
                {
                    "kind": "emotion_motion_open_skipped",
                    "reason": "hands_overlay_not_configured",
                },
            )
        _emit(
            output,
            {
                "kind": "emotion_custom_action_summary",
                "action_name": action_name,
                "status": "accepted" if rpc_code == 0 else "rpc_failed",
                "rpc_code": rpc_code,
                "physical_actions_emitted": rpc_code == 0,
            },
        )
    if not executed:
        _emit(
            output,
            {
                "kind": "emotion_custom_action_summary",
                "status": "not_requested",
                "physical_actions_emitted": False,
            },
        )
        return 0
    return 0 if rpc_code == 0 else 70


def parse_arguments(arguments: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--from-stdin",
        action="store_true",
        help="从对话 JSONL 流读取；第一条白名单请求立即执行，后续重复请求忽略",
    )
    parser.add_argument(
        "--confirm-g1-companion-listen-invite-executor",
        action="store_true",
        help="确认本次调用官方自定义 ArmAction；手臂伸出后仅张四指、保持拇指（必需）",
    )
    parser.add_argument("--jsonl-output", type=Path, help="JSONL 记录输出路径（追加）")
    parser.add_argument("--interface", default=DEFAULT_INTERFACE, help="DDS 网卡")
    args = parser.parse_args(arguments)
    if not args.from_stdin:
        parser.error("--from-stdin is required")
    if not args.interface or not str(args.interface).strip():
        parser.error("invalid interface")
    if not args.confirm_g1_companion_listen_invite_executor:
        parser.exit(64, "listen invite requires --confirm-g1-companion-listen-invite-executor\n")
    return args


def main(arguments: list[str]) -> int:
    args = parse_arguments(arguments)
    motion = load_motion_executor()

    def output(row: dict[str, Any]) -> None:
        write_custom_action_output(row, jsonl_output=args.jsonl_output)

    try:
        return run_executor(
            args,
            action_factory=lambda: OfficialCustomArmAction(args.interface),
            monitor_factory=lambda: motion.Dex3HandMonitor(args.interface),
            opener_factory=lambda: motion.Dex3HandOpener(args.interface),
            arm_monitor_factory=lambda: motion.LowStateArmMonitor(args.interface),
            output=output,
        )
    except (CustomActionExecutorError, OSError) as error:
        write_custom_action_output(
            {
                "kind": "emotion_custom_action_summary",
                "status": "executor_error",
                "error_code": str(error),
                "physical_actions_emitted": False,
            },
            stdout=sys.stderr,
            jsonl_output=args.jsonl_output,
        )
        return 70


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
