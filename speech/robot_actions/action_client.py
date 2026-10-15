#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any


REPO_ROOT = (
    Path(__file__)
    .resolve()
    .parents[2]
)

DEFAULT_TV_PYTHON = os.getenv(
    "G1_ACTION_PYTHON",
    "/home/user/miniconda3/envs/tv/bin/python",
)

DEFAULT_INTERFACE = os.getenv(
    "G1_ACTION_INTERFACE",
    "enp3s0",
)

MOTION_EXECUTOR = (
    REPO_ROOT
    / "scripts"
    / "g1_elder_companion_motion_executor.py"
)

CUSTOM_EXECUTOR = (
    REPO_ROOT
    / "scripts"
    / "g1_elder_companion_custom_action_executor.py"
)


ACTION_SPECS = {
    # 社交语义动作
    "greeting": {
        "executor": "motion",
        "action_id": 25,
        "motion_id": "greeting_wave_once",
        "label": "挥手问候",
    },

    "goodbye": {
        "executor": "motion",
        "action_id": 25,
        "motion_id": "goodbye_wave_once",
        "label": "挥手告别",
    },

    "present": {
        "executor": "custom",
        "action_name": "open_palm_invite",
        "sequence": "present_once",
        "label": "掌心邀请",
    },

    "acknowledge": {
        "executor": "custom",
        "action_name": "open_palm_invite",
        "sequence": "acknowledge_once",
        "label": "抬手确认",
    },

    "celebrate": {
        "executor": "motion",
        "action_id": 17,
        "motion_id": "celebrate_once",
        "label": "鼓掌",
    },
}


class RobotActionClient:
    """
    各业务场景统一使用的 G1 动作入口。

    默认 enabled=False：
    只生成和打印动作请求，不启动任何 G1 executor。

    真机写入需要同时满足：
      enabled=True
      confirm_writes=True

    实际机器人命令仍全部由仓库现有 executor 发出，
    本模块本身不直接调用 Unitree SDK，也不写 DDS topic。
    """

    def __init__(
        self,
        *,
        enabled: bool = False,
        mode: str | None = None,
        confirm_writes: bool = False,
        interface: str = DEFAULT_INTERFACE,
        tv_python: str = DEFAULT_TV_PYTHON,
        executor_timeout: float = 30.0,
    ):
        if mode is None:
            self.mode = (
                "execute"
                if enabled
                else "dry-run"
            )
        else:
            self.mode = (
                str(mode)
                .strip()
                .lower()
            )

        if self.mode not in {
            "off",
            "dry-run",
            "execute",
        }:
            raise ValueError(
                "robot action mode must be "
                "off, dry-run, or execute"
            )

        self.enabled = (
            self.mode == "execute"
        )

        self.confirm_writes = bool(
            confirm_writes
        )

        self.interface = str(
            interface
        ).strip()

        self.tv_python = str(
            tv_python
        ).strip()

        self.executor_timeout = float(
            executor_timeout
        )

        self._motion_lock = (
            threading.Lock()
        )

        self._thread = None

    @property
    def busy(self) -> bool:
        return (
            self._motion_lock.locked()
        )

    @staticmethod
    def available_actions():
        return tuple(
            ACTION_SPECS.keys()
        )

    def _build_request(
        self,
        action_name: str,
        *,
        source: str | None = None,
    ) -> dict[str, Any]:

        spec = ACTION_SPECS.get(
            action_name
        )

        if spec is None:
            raise ValueError(
                f"unknown robot action: "
                f"{action_name}"
            )

        event_id = (
            "scene-motion-"
            f"{time.time_ns()}"
        )

        source_text = (
            str(source).strip()
            if source
            else "scene"
        )

        if (
            spec["executor"]
            == "motion"
        ):
            return {
                "kind":
                    "emotion_dialogue_motion_request",

                "event_id":
                    event_id,

                "round_no":
                    0,

                "motion_id":
                    spec["motion_id"],

                "action_id":
                    spec["action_id"],

                "trigger":
                    source_text,

                "status":
                    "confirmed",

                "execution":
                    "intent_only",

                "physical_actions_emitted":
                    False,
            }

        return {
            "kind":
                "emotion_dialogue_custom_action_request",

            "event_id":
                event_id,

            "status":
                "confirmed",

            "action_name":
                spec["action_name"],

            "sequence":
                spec["sequence"],

            "trigger":
                source_text,

            "physical_actions_emitted":
                False,
        }

    def preview(
        self,
        action_name: str,
        *,
        source: str | None = None,
    ):
        return self._build_request(
            action_name,
            source=source,
        )

    def _command_for(
        self,
        action_name: str,
    ):
        spec = ACTION_SPECS[
            action_name
        ]

        if (
            spec["executor"]
            == "motion"
        ):
            return [
                self.tv_python,
                str(
                    MOTION_EXECUTOR
                ),
                "--from-stdin",
                "--confirm-g1-companion-motion-executor",
                "--interface",
                self.interface,
            ]

        return [
            self.tv_python,
            str(
                CUSTOM_EXECUTOR
            ),
            "--from-stdin",
            "--confirm-g1-companion-listen-invite-executor",
            "--interface",
            self.interface,
        ]

    @staticmethod
    def _print_request(
        action_name,
        request,
    ):
        label = (
            ACTION_SPECS[
                action_name
            ]["label"]
        )

        print(
            (
                f"动作请求: "
                f"{action_name} "
                f"({label})"
            ),
            flush=True,
        )

        print(
            "动作JSON: "
            + json.dumps(
                request,
                ensure_ascii=False,
                separators=(
                    ",",
                    ":",
                ),
            ),
            flush=True,
        )

    def _execute(
        self,
        action_name: str,
        request: dict[str, Any],
    ) -> dict[str, Any]:

        command = (
            self._command_for(
                action_name
            )
        )

        payload = (
            json.dumps(
                request,
                ensure_ascii=False,
                separators=(
                    ",",
                    ":",
                ),
            )
            + "\n"
        )

        try:
            result = (
                subprocess.run(
                    command,
                    input=payload,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    timeout=
                        self.executor_timeout,
                    check=False,
                )
            )

        except subprocess.TimeoutExpired:
            print(
                (
                    "动作执行失败: "
                    f"{action_name} "
                    "executor timeout"
                ),
                flush=True,
            )

            return {
                "status":
                    "timeout",

                "action":
                    action_name,
            }

        except (
            OSError,
            ValueError,
        ) as exc:
            print(
                (
                    "动作执行失败: "
                    f"{action_name} "
                    f"{exc!r}"
                ),
                flush=True,
            )

            return {
                "status":
                    "executor_error",

                "action":
                    action_name,

                "error":
                    repr(
                        exc
                    ),
            }

        output = (
            result.stdout
            or ""
        ).strip()

        if output:
            for line in (
                output.splitlines()
            ):
                print(
                    "动作执行器: "
                    + line,
                    flush=True,
                )

        status = (
            "completed"
            if result.returncode == 0
            else "failed"
        )

        print(
            (
                f"动作完成: "
                f"{action_name} "
                f"status={status} "
                f"returncode="
                f"{result.returncode}"
            ),
            flush=True,
        )

        return {
            "status":
                status,

            "action":
                action_name,

            "returncode":
                result.returncode,
        }

    def play(
        self,
        action_name: str,
        *,
        source: str | None = None,
        blocking: bool = False,
    ) -> dict[str, Any]:

        if (
            action_name
            not in ACTION_SPECS
        ):
            print(
                (
                    "动作跳过: "
                    f"未知动作 "
                    f"{action_name}"
                ),
                flush=True,
            )

            return {
                "status":
                    "unknown_action",

                "action":
                    action_name,
            }

        if self.mode == "off":
            print(
                (
                    "动作模式: off，"
                    f"跳过 {action_name}"
                ),
                flush=True,
            )

            return {
                "status":
                    "off",

                "action":
                    action_name,
            }

        request = (
            self._build_request(
                action_name,
                source=source,
            )
        )

        self._print_request(
            action_name,
            request,
        )

        # 默认 dry-run。
        # 不启动 executor，
        # 不加载 Unitree SDK，
        # 不写任何机器人命令。
        if self.mode == "dry-run":
            print(
                (
                    "动作模式: dry-run，"
                    "未向机器人写入"
                ),
                flush=True,
            )

            return {
                "status":
                    "dry_run",

                "action":
                    action_name,

                "request":
                    request,
            }

        # 即使 enabled=True，
        # 也必须再次显式确认。
        if not self.confirm_writes:
            print(
                (
                    "动作跳过: "
                    "未确认机器人写入"
                ),
                flush=True,
            )

            return {
                "status":
                    "confirmation_required",

                "action":
                    action_name,
            }

        # 所有手臂动作全局串行。
        # 正在执行时不再启动第二个动作。
        acquired = (
            self._motion_lock
            .acquire(
                blocking=False
            )
        )

        if not acquired:
            print(
                (
                    "动作跳过: "
                    f"{action_name} "
                    "当前已有手臂动作"
                ),
                flush=True,
            )

            return {
                "status":
                    "busy",

                "action":
                    action_name,
            }

        def runner():
            try:
                self._execute(
                    action_name,
                    request,
                )

            finally:
                self._motion_lock.release()

        if blocking:
            try:
                return (
                    self._execute(
                        action_name,
                        request,
                    )
                )

            finally:
                self._motion_lock.release()

        thread = threading.Thread(
            target=runner,
            name=(
                "g1-action-"
                + action_name
            ),
            daemon=False,
        )

        self._thread = thread
        thread.start()

        return {
            "status":
                "started",

            "action":
                action_name,
        }

    def wait(
        self,
        timeout: float | None = None,
    ):
        thread = self._thread

        if (
            thread is None
            or not thread.is_alive()
        ):
            return True

        thread.join(
            timeout=timeout
        )

        return (
            not thread.is_alive()
        )
