#!/usr/bin/env python3
"""老人陪伴情绪确认动作的官方 ArmAction 执行器。

对话模块在老人明确肯定后写 `emotion_dialogue_motion_request`；本执行器消费该请求，
只调用官方 `G1ArmActionClient`（胸前挥手 25 / 鼓掌 17）。`--from-stdin` 在读到请求后
立即执行；`--from-jsonl` 读取已完成文件的最后一条 confirmed 请求。
需要张手时先启动官方 17/25，只读 `rt/lowstate` 等到手臂刚离开躯干（0.03 rad）后再按官方遥操同款
HandCmd 张开 Dex3；鼓掌仅在闭合时张手，挥手每次张手。禁止在垂臂静止时把拇指拉到 0。
张手配方为 `rt/dex3/{left,right}/cmd`、q 目标、kp=1.5、kd=0.2、100 Hz，张开斜坡 0.35 s，
张开后保持掌心打开直到当前手臂 delta ≤ 1.15 rad 且相对峰值回落 ≥ 0.40 rad（卡住最多 6.0 s），再用 1.2 s 收到重启后握拳。
`--close-hands` 同样只闭手、不发手臂命令。张手失败或手臂未离开则跳过 HandCmd，
不取消已开始的 ArmAction。任何机器人写入都需要 `--confirm-g1-companion-motion-executor`；
`--inspect` 只读报告手态。不发布手臂、腿或 lowcmd 命令。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, TextIO

DEX3_LEFT_STATE_TOPIC = "rt/dex3/left/state"
DEX3_RIGHT_STATE_TOPIC = "rt/dex3/right/state"
DEX3_LEFT_COMMAND_TOPIC = "rt/dex3/left/cmd"
DEX3_RIGHT_COMMAND_TOPIC = "rt/dex3/right/cmd"
HAND_MOTOR_COUNT = 7
FINGER_JOINT_INDICES = (3, 4, 5, 6)
CLOSED_FINGER_FLEXION_RAD = 0.8
OPEN_CONFIRM_FINGER_FLEXION_RAD = 0.5
OPEN_RAMP_SECONDS = 0.35
OPEN_HOLD_SECONDS = 0.15
OPEN_SETTLE_SECONDS = 0.15
OPEN_COMMAND_HZ = 100.0
OPEN_COMMAND_KP = 1.5
OPEN_COMMAND_KD = 0.2
OPEN_COMMAND_MOTOR_MODE_STATUS = 0x01
ACTION_EXECUTE_TIMEOUT_SECONDS = 12.0
CLOSE_RAMP_SECONDS = 1.2
CLOSE_SETTLE_SECONDS = 0.3
REST_FIST_CLOSE_TOLERANCE_RAD = 0.25
# 2026-09-12 操作者重启后垂臂实测；runs/elder-companion-hand-pose/post_restart_restore_target.json
REST_FIST_Q = {
    "left": (-0.0193, 0.9407, 1.589, -1.5577, -1.7234, -1.5479, -1.7233),
    "right": (-0.0164, -0.9956, -1.6559, 1.5582, 1.7161, 1.5167, 1.7163),
}
# Official Dex3 limits from unitree_sdk2 example/g1/dex3 and g1_dex3_command_core.hpp.
DEX3_Q_MIN = {
    "left": (-1.05, -0.724, 0.0, -1.57, -1.75, -1.57, -1.75),
    "right": (-1.05, -1.05, -1.75, 0.0, 0.0, 0.0, 0.0),
}
DEX3_Q_MAX = {
    "left": (1.05, 1.05, 1.75, 0.0, 0.0, 0.0, 0.0),
    "right": (1.05, 0.742, 0.0, 1.57, 1.75, 1.57, 1.75),
}
LOWSTATE_TOPIC = "rt/lowstate"
# G1 23DoF LowState 双臂：肩 pitch/roll 与肘。见官方关节顺序。
ARM_CLEARANCE_JOINT_INDICES = (15, 16, 18, 22, 23, 25)
ARM_CLEARANCE_DELTA_RAD = 0.03
ARM_CLEARANCE_TIMEOUT_SECONDS = 0.8
ARM_RETURN_MIN_PEAK_RAD = 0.25
ARM_RETURN_DROP_RAD = 0.40
ARM_RETURN_CLOSE_BELOW_RAD = 1.15
ARM_RETURN_HOLD_TIMEOUT_SECONDS = 6.0
ARM_STATE_SNAPSHOT_TIMEOUT_SECONDS = 0.2
DEFAULT_INTERFACE = "enp3s0"
SUPPORTED_ACTION_IDS = {17: "clap", 25: "face_wave"}
REQUEST_KIND = "emotion_dialogue_motion_request"
ZERO_HAND_Q = [0.0] * HAND_MOTOR_COUNT
_channel_factory_lock = threading.Lock()
_channel_factory_interface: str | None = None


class MotionExecutorError(RuntimeError):
    """Stable error code for the confirmed-motion executor boundary."""


def ensure_channel_factory(interface: str) -> None:
    """ChannelFactory is a process singleton; the first network interface wins."""
    global _channel_factory_interface
    if not isinstance(interface, str) or not interface.strip():
        raise MotionExecutorError("dds_interface_invalid")
    with _channel_factory_lock:
        if _channel_factory_interface is not None:
            if _channel_factory_interface != interface:
                raise MotionExecutorError("channel_factory_interface_locked")
            return
        from unitree_sdk2py.core.channel import ChannelFactoryInitialize

        ChannelFactoryInitialize(0, interface)
        _channel_factory_interface = interface


def finger_flexion_rad(hand_q: list[float]) -> float:
    """四根手指关节（下标 3..6）的平均绝对弯曲角，张开约为 0，实测闭合约 1.5。"""
    if len(hand_q) != HAND_MOTOR_COUNT or any(not math.isfinite(q) for q in hand_q):
        raise MotionExecutorError("hand_state_invalid")
    return sum(abs(hand_q[i]) for i in FINGER_JOINT_INDICES) / len(FINGER_JOINT_INDICES)


def hand_closed(flexion_rad: float) -> bool:
    return flexion_rad >= CLOSED_FINGER_FLEXION_RAD


def should_open_hands(action_id: int, flexion_left: float, flexion_right: float) -> bool:
    """挥手每次张手；鼓掌仅在任一侧已闭合时张手。张手必须发生在手臂离开之后。"""
    if action_id == 25:
        return True
    if action_id == 17:
        return hand_closed(flexion_left) or hand_closed(flexion_right)
    return False


def arm_clearance_delta(origin: list[float], current: list[float]) -> float:
    """Return the max absolute arm-joint change used as hip-clearance evidence."""
    best = 0.0
    for index in ARM_CLEARANCE_JOINT_INDICES:
        if index >= len(origin) or index >= len(current):
            continue
        before = origin[index]
        after = current[index]
        if math.isfinite(before) and math.isfinite(after):
            best = max(best, abs(after - before))
    return best


def wait_for_arm_clearance(
    *,
    snapshot: Callable[[], list[float] | None],
    is_running: Callable[[], bool],
    timeout_seconds: float = ARM_CLEARANCE_TIMEOUT_SECONDS,
    delta_rad: float = ARM_CLEARANCE_DELTA_RAD,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    origin: list[float] | None = None,
) -> dict[str, Any]:
    """Wait until arms leave the rest pose, or skip if the official action already ended."""
    if origin is None:
        origin = snapshot()
    if origin is None:
        return {"cleared": False, "reason": "arm_state_unavailable", "max_delta": 0.0}
    deadline = monotonic() + max(0.0, timeout_seconds)
    best = 0.0
    while monotonic() < deadline:
        if not is_running():
            return {
                "cleared": False,
                "reason": "action_finished",
                "max_delta": round(best, 4),
            }
        current = snapshot()
        if current is not None:
            best = max(best, arm_clearance_delta(origin, current))
            if best >= delta_rad:
                return {"cleared": True, "reason": "arm_moved", "max_delta": round(best, 4)}
        sleep(0.02)
    return {"cleared": False, "reason": "timeout", "max_delta": round(best, 4)}


def wait_for_arm_return(
    *,
    snapshot: Callable[[], list[float] | None],
    is_running: Callable[[], bool],
    origin: list[float] | None,
    timeout_seconds: float = ARM_RETURN_HOLD_TIMEOUT_SECONDS,
    min_peak_rad: float = ARM_RETURN_MIN_PEAK_RAD,
    drop_rad: float = ARM_RETURN_DROP_RAD,
    close_below_rad: float = ARM_RETURN_CLOSE_BELOW_RAD,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Keep palms open until arms leave clap height and drop, then close before they hang."""
    if origin is None:
        return {
            "returning": False,
            "reason": "arm_state_unavailable",
            "peak": 0.0,
            "max_delta": 0.0,
        }
    start = monotonic()
    deadline = start + max(0.0, timeout_seconds)
    peak = 0.0
    latest = 0.0
    while monotonic() <= deadline:
        if not is_running():
            return {
                "returning": False,
                "reason": "action_finished",
                "peak": round(peak, 4),
                "max_delta": round(latest, 4),
            }
        current = snapshot()
        if current is not None:
            latest = arm_clearance_delta(origin, current)
            if latest > peak:
                peak = latest
            if (
                peak >= min_peak_rad
                and (peak - latest) >= drop_rad
                and latest <= close_below_rad
            ):
                return {
                    "returning": True,
                    "reason": "arm_returning",
                    "peak": round(peak, 4),
                    "max_delta": round(latest, 4),
                }
        sleep(0.02)
    return {
        "returning": True,
        "reason": "hold_timeout",
        "peak": round(peak, 4),
        "max_delta": round(latest, 4),
    }


def clip_dex3_q(hand: str, values: list[float]) -> list[float]:
    if hand not in DEX3_Q_MIN or len(values) != HAND_MOTOR_COUNT:
        raise MotionExecutorError("hand_state_invalid")
    mins = DEX3_Q_MIN[hand]
    maxs = DEX3_Q_MAX[hand]
    return [min(maxs[i], max(mins[i], values[i])) for i in range(HAND_MOTOR_COUNT)]


def rest_fist_targets(hand: str, current_q: list[float]) -> list[float]:
    """Return the post-restart rest fist, clipped to official Dex3 limits."""
    if len(current_q) != HAND_MOTOR_COUNT or any(not math.isfinite(q) for q in current_q):
        raise MotionExecutorError("hand_state_invalid")
    if hand not in REST_FIST_Q:
        raise MotionExecutorError("hand_state_invalid")
    return clip_dex3_q(hand, [float(q) for q in REST_FIST_Q[hand]])


def close_ramp_targets(
    hand: str,
    current_q: list[float],
    elapsed_seconds: float,
    ramp_seconds: float = CLOSE_RAMP_SECONDS,
) -> list[float]:
    start = clip_dex3_q(hand, current_q)
    goal = rest_fist_targets(hand, current_q)
    if ramp_seconds <= 0.0:
        return goal
    scale = min(1.0, max(0.0, elapsed_seconds / ramp_seconds))
    return clip_dex3_q(
        hand,
        [origin + (target - origin) * scale for origin, target in zip(start, goal)],
    )


def open_ramp_targets(
    current_q: list[float],
    elapsed_seconds: float,
    ramp_seconds: float = OPEN_RAMP_SECONDS,
) -> list[float]:
    """从当前关节角线性渐进到全零（官方控制器初始目标即张开态）。"""
    if len(current_q) != HAND_MOTOR_COUNT or any(not math.isfinite(q) for q in current_q):
        raise MotionExecutorError("hand_state_invalid")
    if ramp_seconds <= 0.0:
        return list(ZERO_HAND_Q)
    scale = min(1.0, max(0.0, elapsed_seconds / ramp_seconds))
    return [q * (1.0 - scale) for q in current_q]


def open_fingers_preserving_thumbs_targets(
    current_q: list[float], elapsed_seconds: float, ramp_seconds: float = OPEN_RAMP_SECONDS
) -> list[float]:
    """Open only fingers 3..6; keep the three thumb joints at their measured pose."""
    if len(current_q) != HAND_MOTOR_COUNT or any(not math.isfinite(q) for q in current_q):
        raise MotionExecutorError("hand_state_invalid")
    scale = 1.0 if ramp_seconds <= 0.0 else min(1.0, max(0.0, elapsed_seconds / ramp_seconds))
    targets = list(current_q)
    for index in FINGER_JOINT_INDICES:
        targets[index] *= 1.0 - scale
    return targets


def confirmed_action_from_line(line: str) -> int | None:
    """Parse one JSONL line into a supported confirmed official action ID."""
    text = line.strip()
    if not text:
        return None
    try:
        row = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(row, dict):
        return None
    if row.get("kind") != REQUEST_KIND or row.get("status") != "confirmed":
        return None
    action_id = row.get("action_id")
    if (
        isinstance(action_id, int)
        and not isinstance(action_id, bool)
        and action_id in SUPPORTED_ACTION_IDS
    ):
        return action_id
    return None


def confirmed_action_from_jsonl(path: Path) -> int | None:
    """取 JSONL 中最后一条已确认动作请求的官方动作 ID。"""
    latest: int | None = None
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            action_id = confirmed_action_from_line(line)
            if action_id is not None:
                latest = action_id
    return latest


def first_confirmed_action_from_stream(
    stream: TextIO,
    *,
    on_first: Callable[[int], None] | None = None,
) -> int | None:
    """Read JSONL until EOF. Invoke on_first with the first confirmed ID, then keep draining."""
    first: int | None = None
    for line in stream:
        action_id = confirmed_action_from_line(line)
        if action_id is None:
            continue
        if first is None:
            first = action_id
            if on_first is not None:
                on_first(action_id)
    return first


def _emit(output: Callable[[dict[str, Any]], None], row: dict[str, Any]) -> None:
    output(row)


def describe_motion_console(row: dict[str, Any]) -> str | None:
    kind = row.get("kind")
    if kind == "emotion_motion_hand_state":
        return (
            f"[动作] 手态 {row.get('phase')} 左弯曲={row.get('flexion_left')} "
            f"右弯曲={row.get('flexion_right')} 闭合左={row.get('closed_left')} "
            f"闭合右={row.get('closed_right')}"
        )
    if kind == "emotion_motion_open_command":
        return (
            f"[动作] 张开双手 ramp={row.get('ramp_seconds')}s "
            f"kp={row.get('kp')} kd={row.get('kd')}"
        )
    if kind == "emotion_motion_arm_clearance":
        return (
            f"[动作] 手臂离开 cleared={row.get('cleared')} "
            f"原因={row.get('reason')} 最大变化={row.get('max_delta')}"
        )
    if kind == "emotion_motion_arm_return":
        return (
            f"[动作] 手臂回落 returning={row.get('returning')} "
            f"原因={row.get('reason')} 峰值={row.get('peak')} 当前={row.get('max_delta')}"
        )
    if kind == "emotion_motion_close_command":
        return (
            f"[动作] 闭合到重启握拳 ramp={row.get('ramp_seconds')}s "
            f"kp={row.get('kp')} kd={row.get('kd')}，不发手臂命令"
        )
    if kind == "emotion_motion_open_skipped":
        return f"[动作] 跳过张手 原因={row.get('reason')}，官方动作继续"
    if kind == "emotion_motion_close_skipped":
        return f"[动作] 跳过闭合 原因={row.get('reason')}"
    if kind == "emotion_motion_execute":
        status = row.get("status")
        if status == "not_requested":
            return "[动作] 未收到已确认请求，不发令"
        if status == "hands_not_open":
            return "[动作] 张手未确认，官方动作继续"
        name = row.get("action_name") or ""
        name_part = f" {name}" if name else ""
        return (
            f"[动作] 执行 官方ID={row.get('action_id')}{name_part} "
            f"状态={status} rpc={row.get('rpc_code')}"
        )
    if kind == "emotion_motion_summary":
        if row.get("error_code"):
            return f"[动作] 失败 {row.get('error_code')}"
        return (
            f"[动作] 摘要 官方ID={row.get('action_id')} "
            f"已发令={row.get('physical_actions_emitted')} 原因={row.get('reason')}"
        )
    return None


def _write_stream(text: str, stream: TextIO) -> None:
    try:
        print(text, file=stream, flush=True)
    except BrokenPipeError:
        closer = getattr(stream, "close", None)
        if closer is None:
            return
        try:
            closer()
        except OSError:
            return


def write_motion_output(
    row: dict[str, Any],
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    jsonl_output: Path | None = None,
) -> None:
    if stdout is None:
        stdout = sys.stdout
    if stderr is None:
        stderr = sys.stderr
    line = json.dumps(row, ensure_ascii=False, separators=(",", ":"))
    _write_stream(line, stdout)
    text = describe_motion_console(row)
    if text:
        _write_stream(text, stderr)
    if jsonl_output is not None:
        with jsonl_output.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


class Dex3HandMonitor:
    """只读订阅两只 Dex3 的 HandState。"""

    def __init__(self, interface: str = DEFAULT_INTERFACE) -> None:
        ensure_channel_factory(interface)
        from unitree_sdk2py.core.channel import ChannelSubscriber
        from unitree_sdk2py.idl.unitree_hg.msg.dds_ import HandState_

        self._states: dict[str, list[float]] = {}
        self._state_lock = threading.Lock()
        self._subscribers = []
        for hand, topic in (
            ("left", DEX3_LEFT_STATE_TOPIC),
            ("right", DEX3_RIGHT_STATE_TOPIC),
        ):
            subscriber = ChannelSubscriber(topic, HandState_)
            subscriber.Init(self._make_handler(hand))
            self._subscribers.append(subscriber)

    def _make_handler(self, hand: str) -> Callable[[Any], None]:
        def handler(message: Any) -> None:
            motors = message.motor_state
            if len(motors) != HAND_MOTOR_COUNT:
                return
            values = [float(motor.q) for motor in motors]
            with self._state_lock:
                self._states[hand] = values

        return handler

    def wait_for_state(self, timeout_seconds: float) -> dict[str, list[float]]:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            with self._state_lock:
                if "left" in self._states and "right" in self._states:
                    return {hand: list(values) for hand, values in self._states.items()}
            time.sleep(0.02)
        raise MotionExecutorError("hand_state_unavailable")


class LowStateArmMonitor:
    """只读订阅 rt/lowstate，供手臂离开躯干判定。不发布命令。"""

    def __init__(self, interface: str = DEFAULT_INTERFACE) -> None:
        ensure_channel_factory(interface)
        from unitree_sdk2py.core.channel import ChannelSubscriber
        from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowState_

        self._q: list[float] | None = None
        self._lock = threading.Lock()
        self._subscriber = ChannelSubscriber(LOWSTATE_TOPIC, LowState_)
        self._subscriber.Init(self._handler)

    def _handler(self, message: Any) -> None:
        motors = getattr(message, "motor_state", ())
        values = [float(motor.q) for motor in motors]
        with self._lock:
            self._q = values

    def snapshot(self, timeout_seconds: float) -> list[float] | None:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() <= deadline:
            with self._lock:
                if self._q is not None:
                    return list(self._q)
            time.sleep(0.02)
        return None


class Dex3HandOpener:
    """按官方遥操同款配方发布 HandCmd 张开目标。"""

    def __init__(self, interface: str = DEFAULT_INTERFACE) -> None:
        ensure_channel_factory(interface)
        from unitree_sdk2py.core.channel import ChannelPublisher
        from unitree_sdk2py.idl.default import unitree_hg_msg_dds__HandCmd_
        from unitree_sdk2py.idl.unitree_hg.msg.dds_ import HandCmd_

        self._default_cmd = unitree_hg_msg_dds__HandCmd_
        self._publishers = {
            "left": ChannelPublisher(DEX3_LEFT_COMMAND_TOPIC, HandCmd_),
            "right": ChannelPublisher(DEX3_RIGHT_COMMAND_TOPIC, HandCmd_),
        }
        for publisher in self._publishers.values():
            publisher.Init()
        self._hold_stop = threading.Event()
        self._hold_thread: threading.Thread | None = None

    def _build_message(self, q_targets: list[float]) -> Any:
        message = self._default_cmd()
        for motor_id in range(HAND_MOTOR_COUNT):
            command = message.motor_cmd[motor_id]
            command.mode = motor_id | (OPEN_COMMAND_MOTOR_MODE_STATUS << 4)
            command.q = float(q_targets[motor_id])
            command.dq = 0.0
            command.tau = 0.0
            command.kp = OPEN_COMMAND_KP
            command.kd = OPEN_COMMAND_KD
        return message

    def publish_open_targets(
        self, left_q: list[float] | None, right_q: list[float] | None
    ) -> None:
        results = []
        if left_q is not None:
            results.append(self._publishers["left"].Write(self._build_message(left_q)))
        if right_q is not None:
            results.append(self._publishers["right"].Write(self._build_message(right_q)))
        if not results or any(result is False for result in results):
            raise MotionExecutorError("hand_command_publish_failed")

    def start_hold_open(
        self,
        left_q: list[float] | None = ZERO_HAND_Q,
        right_q: list[float] | None = ZERO_HAND_Q,
    ) -> None:
        if self._hold_thread is not None:
            return
        left_targets = None if left_q is None else list(left_q)
        right_targets = None if right_q is None else list(right_q)
        self._hold_stop.clear()
        period = 1.0 / OPEN_COMMAND_HZ

        def loop() -> None:
            while not self._hold_stop.is_set():
                self.publish_open_targets(left_targets, right_targets)
                self._hold_stop.wait(period)

        self._hold_thread = threading.Thread(
            target=loop, name="dex3-hold-open", daemon=True
        )
        self._hold_thread.start()

    def stop_hold_open(self, *, close_publishers: bool = True) -> None:
        self._hold_stop.set()
        if self._hold_thread is not None:
            self._hold_thread.join(timeout=1.0)
            self._hold_thread = None
        if close_publishers:
            self.close_publishers()

    def close_publishers(self) -> None:
        for publisher in self._publishers.values():
            publisher.Close()


class OfficialArmAction:
    """官方 G1ArmActionClient 薄封装。"""

    def __init__(self, interface: str = DEFAULT_INTERFACE) -> None:
        ensure_channel_factory(interface)
        from unitree_sdk2py.g1.arm.g1_arm_action_client import G1ArmActionClient

        self._client = G1ArmActionClient()
        self._client.Init()
        self._client.SetTimeout(ACTION_EXECUTE_TIMEOUT_SECONDS)

    def execute(self, action_id: int) -> int:
        return int(self._client.ExecuteAction(action_id))


def run_open_hands(
    monitor: Dex3HandMonitor,
    opener: Dex3HandOpener,
    initial_state: dict[str, list[float]],
    output: Callable[[dict[str, Any]], None],
    *,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    ramp_seconds: float = OPEN_RAMP_SECONDS,
    hold_seconds: float = OPEN_HOLD_SECONDS,
    settle_seconds: float = OPEN_SETTLE_SECONDS,
    continue_open: Callable[[], bool] | None = None,
    target_factory: Callable[[list[float], float, float], list[float]] = open_ramp_targets,
    preserve_thumbs: bool = False,
    command_hands: tuple[str, ...] = ("left", "right"),
) -> dict[str, list[float]]:
    """按官方增益线性渐进张开指定 Dex3 手，返回张开后的实测状态。"""
    if continue_open is None:
        continue_open = lambda: True
    command_left = "left" in command_hands
    command_right = "right" in command_hands
    if not command_left and not command_right:
        raise MotionExecutorError("hand_command_target_missing")
    _emit(
        output,
        {
            "kind": "emotion_motion_open_command",
            "ramp_seconds": ramp_seconds,
            "hold_seconds": hold_seconds,
            "command_hz": OPEN_COMMAND_HZ,
            "kp": OPEN_COMMAND_KP,
            "kd": OPEN_COMMAND_KD,
            "thumbs_preserved": preserve_thumbs,
            "commanded_hands": list(command_hands),
        },
    )
    start = monotonic()
    period = 1.0 / OPEN_COMMAND_HZ
    deadline = start + ramp_seconds + hold_seconds
    while continue_open():
        elapsed = monotonic() - start
        opener.publish_open_targets(
            target_factory(initial_state["left"], elapsed, ramp_seconds) if command_left else None,
            target_factory(initial_state["right"], elapsed, ramp_seconds) if command_right else None,
        )
        if elapsed >= ramp_seconds + hold_seconds or monotonic() >= deadline:
            break
        sleep(period)
    if settle_seconds > 0.0:
        left_targets = (
            target_factory(initial_state["left"], ramp_seconds, ramp_seconds)
            if command_left
            else None
        )
        right_targets = (
            target_factory(initial_state["right"], ramp_seconds, ramp_seconds)
            if command_right
            else None
        )
        settle_deadline = monotonic() + settle_seconds
        while continue_open() and monotonic() < settle_deadline:
            opener.publish_open_targets(left_targets, right_targets)
            sleep(period)
    return monitor.wait_for_state(2.0)


def run_close_hands(
    monitor: Dex3HandMonitor,
    opener: Dex3HandOpener,
    initial_state: dict[str, list[float]],
    output: Callable[[dict[str, Any]], None],
    *,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    ramp_seconds: float = CLOSE_RAMP_SECONDS,
    settle_seconds: float = CLOSE_SETTLE_SECONDS,
    command_hands: tuple[str, ...] = ("left", "right"),
) -> dict[str, list[float]]:
    """Ramp the selected Dex3 hands to the post-restart rest fist. Do not move arms."""
    command_left = "left" in command_hands
    command_right = "right" in command_hands
    if not command_left and not command_right:
        raise MotionExecutorError("hand_command_target_missing")
    _emit(
        output,
        {
            "kind": "emotion_motion_close_command",
            "ramp_seconds": ramp_seconds,
            "settle_seconds": settle_seconds,
            "command_hz": OPEN_COMMAND_HZ,
            "kp": OPEN_COMMAND_KP,
            "kd": OPEN_COMMAND_KD,
            "restore": "post_restart_fist",
            "q_left": list(REST_FIST_Q["left"]) if command_left else None,
            "q_right": list(REST_FIST_Q["right"]) if command_right else None,
            "commanded_hands": list(command_hands),
        },
    )
    start = monotonic()
    period = 1.0 / OPEN_COMMAND_HZ
    deadline = start + ramp_seconds
    final_left = rest_fist_targets("left", initial_state["left"]) if command_left else None
    final_right = rest_fist_targets("right", initial_state["right"]) if command_right else None
    while True:
        elapsed = monotonic() - start
        opener.publish_open_targets(
            close_ramp_targets("left", initial_state["left"], elapsed, ramp_seconds)
            if command_left
            else None,
            close_ramp_targets("right", initial_state["right"], elapsed, ramp_seconds)
            if command_right
            else None,
        )
        if elapsed >= ramp_seconds or monotonic() >= deadline:
            break
        sleep(period)
    if settle_seconds > 0.0:
        settle_deadline = monotonic() + settle_seconds
        while monotonic() < settle_deadline:
            opener.publish_open_targets(final_left, final_right)
            sleep(period)
    return monitor.wait_for_state(2.0)


def _hands_need_close(
    state: dict[str, list[float]], command_hands: tuple[str, ...] = ("left", "right")
) -> bool:
    """True unless the selected hands are already near the post-restart rest fist."""
    for hand in command_hands:
        current = state[hand]
        target = rest_fist_targets(hand, current)
        if any(
            abs(current_q - target_q) > REST_FIST_CLOSE_TOLERANCE_RAD
            for current_q, target_q in zip(current, target)
        ):
            return True
    return False


def close_hands_at_rest(
    monitor: Dex3HandMonitor,
    opener: Dex3HandOpener,
    output: Callable[[dict[str, Any]], None],
    *,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    ramp_seconds: float = CLOSE_RAMP_SECONDS,
    settle_seconds: float = CLOSE_SETTLE_SECONDS,
    command_hands: tuple[str, ...] = ("left", "right"),
) -> dict[str, list[float]] | None:
    state = monitor.wait_for_state(2.0)
    if not _hands_need_close(state, command_hands):
        return None
    closed = run_close_hands(
        monitor,
        opener,
        state,
        output,
        sleep=sleep,
        monotonic=monotonic,
        ramp_seconds=ramp_seconds,
        settle_seconds=settle_seconds,
        command_hands=command_hands,
    )
    _emit(
        output,
        {
            "kind": "emotion_motion_hand_state",
            "phase": "after_close",
            "flexion_left": round(finger_flexion_rad(closed["left"]), 4),
            "flexion_right": round(finger_flexion_rad(closed["right"]), 4),
            "closed_left": hand_closed(finger_flexion_rad(closed["left"])),
            "closed_right": hand_closed(finger_flexion_rad(closed["right"])),
        },
    )
    return closed


def run_executor(
    args: argparse.Namespace,
    *,
    monitor_factory: Callable[[], Dex3HandMonitor],
    opener_factory: Callable[[], Dex3HandOpener],
    action_factory: Callable[[], OfficialArmAction],
    output: Callable[[dict[str, Any]], None],
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    ramp_seconds: float = OPEN_RAMP_SECONDS,
    hold_seconds: float = OPEN_HOLD_SECONDS,
    settle_seconds: float = OPEN_SETTLE_SECONDS,
    close_ramp_seconds: float = CLOSE_RAMP_SECONDS,
    stream: TextIO | None = None,
    arm_monitor_factory: Callable[[], Any] | None = None,
    clearance_wait: Callable[[Callable[[], bool]], dict[str, Any]] | None = None,
    return_wait: Callable[[Callable[[], bool]], dict[str, Any]] | None = None,
    clearance_timeout_seconds: float = ARM_CLEARANCE_TIMEOUT_SECONDS,
    clearance_delta_rad: float = ARM_CLEARANCE_DELTA_RAD,
    return_hold_timeout_seconds: float = ARM_RETURN_HOLD_TIMEOUT_SECONDS,
) -> int:
    if args.inspect:
        monitor = monitor_factory()
        state = monitor.wait_for_state(args.state_timeout_ms / 1000.0)
        _emit(
            output,
            {
                "kind": "emotion_motion_hand_state",
                "phase": "inspect",
                "flexion_left": round(finger_flexion_rad(state["left"]), 4),
                "flexion_right": round(finger_flexion_rad(state["right"]), 4),
                "closed_left": hand_closed(finger_flexion_rad(state["left"])),
                "closed_right": hand_closed(finger_flexion_rad(state["right"])),
                "q_left": [round(q, 4) for q in state["left"]],
                "q_right": [round(q, 4) for q in state["right"]],
            },
        )
        return 0

    if getattr(args, "close_hands", False):
        monitor = monitor_factory()
        opener = opener_factory()
        try:
            state = monitor.wait_for_state(args.state_timeout_ms / 1000.0)
            _emit(
                output,
                {
                    "kind": "emotion_motion_hand_state",
                    "phase": "before_close",
                    "flexion_left": round(finger_flexion_rad(state["left"]), 4),
                    "flexion_right": round(finger_flexion_rad(state["right"]), 4),
                    "closed_left": hand_closed(finger_flexion_rad(state["left"])),
                    "closed_right": hand_closed(finger_flexion_rad(state["right"])),
                },
            )
            if not _hands_need_close(state):
                _emit(
                    output,
                    {
                        "kind": "emotion_motion_summary",
                        "physical_actions_emitted": False,
                        "reason": "already_closed",
                    },
                )
                return 0
            closed = run_close_hands(
                monitor,
                opener,
                state,
                output,
                sleep=sleep,
                monotonic=monotonic,
                ramp_seconds=close_ramp_seconds,
                settle_seconds=settle_seconds,
            )
            _emit(
                output,
                {
                    "kind": "emotion_motion_hand_state",
                    "phase": "after_close",
                    "flexion_left": round(finger_flexion_rad(closed["left"]), 4),
                    "flexion_right": round(finger_flexion_rad(closed["right"]), 4),
                    "closed_left": hand_closed(finger_flexion_rad(closed["left"])),
                    "closed_right": hand_closed(finger_flexion_rad(closed["right"])),
                },
            )
            _emit(
                output,
                {
                    "kind": "emotion_motion_summary",
                    "physical_actions_emitted": True,
                    "reason": "hands_closed",
                },
            )
            return 0
        finally:
            opener.stop_hold_open()

    execute_kwargs = {
        "args": args,
        "monitor_factory": monitor_factory,
        "opener_factory": opener_factory,
        "action_factory": action_factory,
        "output": output,
        "sleep": sleep,
        "monotonic": monotonic,
        "ramp_seconds": ramp_seconds,
        "hold_seconds": hold_seconds,
        "settle_seconds": settle_seconds,
        "close_ramp_seconds": close_ramp_seconds,
        "arm_monitor_factory": arm_monitor_factory,
        "clearance_wait": clearance_wait,
        "return_wait": return_wait,
        "clearance_timeout_seconds": clearance_timeout_seconds,
        "clearance_delta_rad": clearance_delta_rad,
        "return_hold_timeout_seconds": return_hold_timeout_seconds,
    }
    if getattr(args, "from_stdin", False):
        return _run_executor_from_stream(stream if stream is not None else sys.stdin, **execute_kwargs)

    action_id = args.action_id
    if action_id is None and args.from_jsonl is not None:
        action_id = confirmed_action_from_jsonl(Path(args.from_jsonl))
    return execute_confirmed_action(action_id, **execute_kwargs)


def _run_executor_from_stream(stream: TextIO, **execute_kwargs: Any) -> int:
    holder: dict[str, Any] = {"code": 0, "thread": None, "error": None}

    def on_first(action_id: int) -> None:
        def worker() -> None:
            try:
                holder["code"] = execute_confirmed_action(action_id, **execute_kwargs)
            except Exception as error:
                holder["error"] = error

        thread = threading.Thread(target=worker, name="g1-companion-arm-action")
        holder["thread"] = thread
        thread.start()

    first_confirmed_action_from_stream(stream, on_first=on_first)
    thread = holder["thread"]
    if thread is None:
        return execute_confirmed_action(None, **execute_kwargs)
    thread.join()
    if holder["error"] is not None:
        raise holder["error"]
    return int(holder["code"])


def execute_confirmed_action(
    action_id: int | None,
    *,
    args: argparse.Namespace,
    monitor_factory: Callable[[], Dex3HandMonitor],
    opener_factory: Callable[[], Dex3HandOpener],
    action_factory: Callable[[], OfficialArmAction],
    output: Callable[[dict[str, Any]], None],
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    ramp_seconds: float = OPEN_RAMP_SECONDS,
    hold_seconds: float = OPEN_HOLD_SECONDS,
    settle_seconds: float = OPEN_SETTLE_SECONDS,
    close_ramp_seconds: float = CLOSE_RAMP_SECONDS,
    arm_monitor_factory: Callable[[], Any] | None = None,
    clearance_wait: Callable[[Callable[[], bool]], dict[str, Any]] | None = None,
    return_wait: Callable[[Callable[[], bool]], dict[str, Any]] | None = None,
    clearance_timeout_seconds: float = ARM_CLEARANCE_TIMEOUT_SECONDS,
    clearance_delta_rad: float = ARM_CLEARANCE_DELTA_RAD,
    return_hold_timeout_seconds: float = ARM_RETURN_HOLD_TIMEOUT_SECONDS,
) -> int:
    if action_id not in SUPPORTED_ACTION_IDS:
        _emit(
            output,
            {
                "kind": "emotion_motion_execute",
                "action_id": action_id,
                "status": "not_requested",
            },
        )
        return 0

    monitor = monitor_factory()
    state = monitor.wait_for_state(args.state_timeout_ms / 1000.0)
    flexion_left = finger_flexion_rad(state["left"])
    flexion_right = finger_flexion_rad(state["right"])
    _emit(
        output,
        {
            "kind": "emotion_motion_hand_state",
            "phase": "before_action",
            "flexion_left": round(flexion_left, 4),
            "flexion_right": round(flexion_right, 4),
            "closed_left": hand_closed(flexion_left),
            "closed_right": hand_closed(flexion_right),
        },
    )

    need_open = should_open_hands(action_id, flexion_left, flexion_right)
    if not need_open:
        rpc_code = action_factory().execute(action_id)
        rest_opener = opener_factory()
        try:
            close_hands_at_rest(
                monitor,
                rest_opener,
                output,
                sleep=sleep,
                monotonic=monotonic,
                ramp_seconds=close_ramp_seconds,
                settle_seconds=settle_seconds,
            )
        finally:
            rest_opener.stop_hold_open()
        return _emit_action_result(output, action_id, rpc_code)

    wait_clearance = clearance_wait
    wait_return = return_wait
    origin: list[float] | None = None
    arm_monitor: Any | None = None
    if wait_clearance is None:
        arm_monitor = (
            arm_monitor_factory()
            if arm_monitor_factory is not None
            else LowStateArmMonitor(args.interface)
        )
        origin = arm_monitor.snapshot(ARM_STATE_SNAPSHOT_TIMEOUT_SECONDS)

        def wait_clearance(is_running: Callable[[], bool]) -> dict[str, Any]:
            if origin is None:
                return {
                    "cleared": False,
                    "reason": "arm_state_unavailable",
                    "max_delta": 0.0,
                }
            return wait_for_arm_clearance(
                snapshot=lambda: arm_monitor.snapshot(ARM_STATE_SNAPSHOT_TIMEOUT_SECONDS),
                is_running=is_running,
                origin=origin,
                timeout_seconds=clearance_timeout_seconds,
                delta_rad=clearance_delta_rad,
                sleep=sleep,
                monotonic=monotonic,
            )

    # Init the official client before the 0.8s clearance clock; the worker
    # only runs the blocking ExecuteAction RPC.
    action_client = action_factory()
    rpc_holder: dict[str, Any] = {"code": None, "error": None}

    def _run_official_action() -> None:
        try:
            rpc_holder["code"] = action_client.execute(action_id)
        except Exception as error:
            rpc_holder["error"] = error

    action_thread = threading.Thread(
        target=_run_official_action,
        name="g1-companion-arm-action-rpc",
        daemon=False,
    )
    action_thread.start()

    def action_still_running() -> bool:
        return action_thread.is_alive()

    opener: Dex3HandOpener | None = None
    try:
        clearance = wait_clearance(action_still_running)
        _emit(
            output,
            {
                "kind": "emotion_motion_arm_clearance",
                "cleared": bool(clearance.get("cleared")),
                "reason": clearance.get("reason"),
                "max_delta": clearance.get("max_delta"),
            },
        )

        running = action_still_running()
        if not clearance.get("cleared") or not running:
            skip_reason = (
                "action_finished"
                if not running
                else str(clearance.get("reason") or "not_cleared")
            )
            _emit(
                output,
                {
                    "kind": "emotion_motion_open_skipped",
                    "reason": skip_reason,
                },
            )
        else:
            try:
                opener = opener_factory()
                opened = run_open_hands(
                    monitor,
                    opener,
                    state,
                    output,
                    sleep=sleep,
                    monotonic=monotonic,
                    ramp_seconds=ramp_seconds,
                    hold_seconds=hold_seconds,
                    settle_seconds=settle_seconds,
                    continue_open=action_still_running,
                )
                opened_left = finger_flexion_rad(opened["left"])
                opened_right = finger_flexion_rad(opened["right"])
                _emit(
                    output,
                    {
                        "kind": "emotion_motion_hand_state",
                        "phase": "after_open",
                        "flexion_left": round(opened_left, 4),
                        "flexion_right": round(opened_right, 4),
                        "closed_left": hand_closed(opened_left),
                        "closed_right": hand_closed(opened_right),
                    },
                )
                if not action_still_running():
                    _emit(
                        output,
                        {
                            "kind": "emotion_motion_open_skipped",
                            "reason": "action_finished_during_open",
                        },
                    )
                elif opened_left >= OPEN_CONFIRM_FINGER_FLEXION_RAD or (
                    opened_right >= OPEN_CONFIRM_FINGER_FLEXION_RAD
                ):
                    _emit(
                        output,
                        {
                            "kind": "emotion_motion_execute",
                            "action_id": action_id,
                            "status": "hands_not_open",
                        },
                    )
                else:
                    opener.start_hold_open()
                    if wait_return is not None:
                        returning = wait_return(action_still_running)
                    elif origin is not None and arm_monitor is not None:
                        returning = wait_for_arm_return(
                            snapshot=lambda: arm_monitor.snapshot(
                                ARM_STATE_SNAPSHOT_TIMEOUT_SECONDS
                            ),
                            is_running=action_still_running,
                            origin=origin,
                            timeout_seconds=return_hold_timeout_seconds,
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
            except (MotionExecutorError, OSError) as error:
                _emit(
                    output,
                    {
                        "kind": "emotion_motion_open_skipped",
                        "reason": str(error),
                    },
                )
    finally:
        if opener is not None:
            opener.stop_hold_open(close_publishers=False)
            try:
                close_hands_at_rest(
                    monitor,
                    opener,
                    output,
                    sleep=sleep,
                    monotonic=monotonic,
                    ramp_seconds=close_ramp_seconds,
                    settle_seconds=settle_seconds,
                )
            except (MotionExecutorError, OSError) as error:
                _emit(
                    output,
                    {
                        "kind": "emotion_motion_close_skipped",
                        "reason": str(error),
                    },
                )
            opener.close_publishers()
        action_thread.join()

    if rpc_holder["error"] is not None:
        raise rpc_holder["error"]
    if rpc_holder["code"] is None:
        raise MotionExecutorError("arm_action_rpc_missing")
    rpc_code = int(rpc_holder["code"])
    return _emit_action_result(output, action_id, rpc_code)


def _emit_action_result(
    output: Callable[[dict[str, Any]], None],
    action_id: int,
    rpc_code: int,
) -> int:
    _emit(
        output,
        {
            "kind": "emotion_motion_execute",
            "action_id": action_id,
            "action_name": SUPPORTED_ACTION_IDS[action_id],
            "status": "executed" if rpc_code == 0 else "rpc_failed",
            "rpc_code": rpc_code,
        },
    )
    _emit(
        output,
        {
            "kind": "emotion_motion_summary",
            "action_id": action_id,
            "physical_actions_emitted": rpc_code == 0,
            "reason": "action_accepted" if rpc_code == 0 else "rpc_failed",
        },
    )
    return 0 if rpc_code == 0 else 70


def parse_arguments(arguments: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inspect", action="store_true", help="只读报告双手弯曲状态")
    parser.add_argument("--action-id", type=int, choices=sorted(SUPPORTED_ACTION_IDS))
    parser.add_argument("--from-jsonl", type=Path, help="从对话 JSONL 取最后一条已确认动作请求")
    parser.add_argument(
        "--from-stdin",
        action="store_true",
        help="从对话 JSONL 流读取；第一条已确认请求立即执行，并继续排空 stdin",
    )
    parser.add_argument(
        "--close-hands",
        action="store_true",
        help="只把 Dex3 收到重启后垂臂握拳，手臂保持不动（必需确认）",
    )
    parser.add_argument(
        "--confirm-g1-companion-motion-executor",
        action="store_true",
        help="确认本次写入 Dex3 或官方动作（必需，任何机器人写入的硬门）",
    )
    parser.add_argument("--jsonl-output", type=Path, help="JSONL 记录输出路径（追加）")
    parser.add_argument("--interface", default=DEFAULT_INTERFACE, help="DDS 网卡")
    parser.add_argument("--state-timeout-ms", type=float, default=2000.0)
    args = parser.parse_args(arguments)
    source_count = sum(
        (
            args.action_id is not None,
            args.from_jsonl is not None,
            bool(args.from_stdin),
            bool(args.close_hands),
        )
    )
    has_request_source = source_count > 0
    if source_count > 1 or args.inspect == has_request_source:
        parser.error("choose exactly one of --inspect or an action source")
    if not args.interface or not str(args.interface).strip():
        parser.error("invalid interface")
    if has_request_source and not args.confirm_g1_companion_motion_executor:
        parser.exit(64, "robot motion requires --confirm-g1-companion-motion-executor\n")
    if not (0.0 < args.state_timeout_ms <= 10_000.0):
        parser.error("invalid state timeout")
    return args


def main(arguments: list[str]) -> int:
    args = parse_arguments(arguments)

    def output(row: dict[str, Any]) -> None:
        write_motion_output(row, jsonl_output=args.jsonl_output)

    try:
        return run_executor(
            args,
            monitor_factory=lambda: Dex3HandMonitor(args.interface),
            opener_factory=lambda: Dex3HandOpener(args.interface),
            action_factory=lambda: OfficialArmAction(args.interface),
            arm_monitor_factory=lambda: LowStateArmMonitor(args.interface),
            output=output,
        )
    except (MotionExecutorError, OSError) as error:
        write_motion_output(
            {
                "kind": "emotion_motion_summary",
                "error_code": str(error),
                "physical_actions_emitted": False,
            },
            stdout=sys.stderr,
            stderr=sys.stderr,
            jsonl_output=args.jsonl_output,
        )
        return 70


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except BrokenPipeError:
        raise SystemExit(0)
