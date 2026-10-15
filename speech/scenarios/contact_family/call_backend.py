from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from datetime import datetime


SCENE_DIR = Path(__file__).resolve().parent
SPEECH_ROOT = SCENE_DIR.parents[1]
REPO_ROOT = SPEECH_ROOT.parent

REAL_CALL_SCRIPT = (
    REPO_ROOT
    / "scripts"
    / "g1_call_owner_once.sh"
)


PHONE_DIAL_SCRIPT = (
    REPO_ROOT
    / "scripts"
    / "g1_phone_dial.py"
)

DEFAULT_TOKEN_FILE = Path(
    os.getenv(
        "G1_PHONE_TOKEN_FILE",
        str(
            Path.home()
            / ".config"
            / "g1-phone-dial"
            / "token"
        ),
    )
)


class CallBackendError(RuntimeError):
    pass


class ContactCallBackend:
    """
    CONTACT_FAMILY 的统一通话后端。

    mode:
        dry_run
            不访问手机、不真实拨号。
            当前无手机时用于验证业务接线。

        real
            调用队友提供的真实 Android 拨号入口。

    原有 MockCallService 暂时继续由旧 g1_voice_demo
    独立维护，等本层验证完再统一接进来。
    """

    VALID_MODES = {
        "safe_stub",
        "dry_run",
        "real",
    }


    def __init__(
        self,
        *,
        mode="dry_run",
        phone_url=None,
    ):
        mode = str(
            mode or ""
        ).strip().lower()

        if mode not in self.VALID_MODES:
            raise ValueError(
                f"不支持的通话后端: {mode}"
            )

        self.mode = mode

        self.phone_url = (
            phone_url
            or os.getenv(
                "G1_PHONE_URL",
                "",
            ).strip()
        )


    def _base_env(self):
        env = os.environ.copy()

        if self.phone_url:
            env[
                "G1_PHONE_URL"
            ] = self.phone_url

        return env


    @staticmethod
    def _parse_contract_output(
        stdout,
    ):
        """
        解析队友拨号脚本输出。

        当前正式合同输出为 JSON，例如：

        {
          "contact_id": "owner",
          "external_dial_requested": false,
          "mode": "dry_run",
          "operation_state": "planned",
          "schema_version":
              "g1_contact_family_call_v1"
        }

        同时保留旧 key=value 文本兼容，
        避免调试脚本格式变化影响场景。
        """

        text = str(
            stdout or ""
        ).strip()

        result = {
            "operation_state":
                None,

            "external_dial_requested":
                None,

            "contract":
                None,
        }

        if not text:
            return result

        # -------------------------------------------------
        # 1. 优先解析完整 JSON
        # -------------------------------------------------

        payload = None

        try:
            candidate = json.loads(
                text
            )

            if isinstance(
                candidate,
                dict,
            ):
                payload = candidate

        except json.JSONDecodeError:
            pass

        # -------------------------------------------------
        # 2. 如果前面混有普通日志，
        #    尝试寻找最后一个 JSON 行
        # -------------------------------------------------

        if payload is None:

            for raw_line in reversed(
                text.splitlines()
            ):

                line = raw_line.strip()

                if not line:
                    continue

                try:
                    candidate = (
                        json.loads(
                            line
                        )
                    )

                except json.JSONDecodeError:
                    continue

                if isinstance(
                    candidate,
                    dict,
                ):
                    payload = candidate
                    break

        if payload is not None:

            state = payload.get(
                "operation_state"
            )

            if state is not None:
                result[
                    "operation_state"
                ] = str(
                    state
                ).strip()

            external = payload.get(
                "external_dial_requested"
            )

            if isinstance(
                external,
                bool,
            ):
                result[
                    "external_dial_requested"
                ] = external

            elif external is not None:

                value = str(
                    external
                ).strip().lower()

                if value == "true":
                    result[
                        "external_dial_requested"
                    ] = True

                elif value == "false":
                    result[
                        "external_dial_requested"
                    ] = False

            result[
                "contract"
            ] = payload

            return result

        # -------------------------------------------------
        # 3. 兼容旧 key=value 输出
        # -------------------------------------------------

        for raw_line in (
            text.splitlines()
        ):

            line = raw_line.strip()

            if (
                "operation_state="
                in line
            ):
                value = (
                    line
                    .split(
                        "operation_state=",
                        1,
                    )[1]
                    .split()[0]
                    .strip(",")
                )

                result[
                    "operation_state"
                ] = value

            if (
                "external_dial_requested="
                in line
            ):
                value = (
                    line
                    .split(
                        "external_dial_requested=",
                        1,
                    )[1]
                    .split()[0]
                    .strip(",")
                    .lower()
                )

                if value == "true":
                    result[
                        "external_dial_requested"
                    ] = True

                elif value == "false":
                    result[
                        "external_dial_requested"
                    ] = False

        return result


    def _run_script(
        self,
        args,
        *,
        timeout,
    ):
        if not REAL_CALL_SCRIPT.exists():
            raise CallBackendError(
                "找不到真实拨号脚本: "
                f"{REAL_CALL_SCRIPT}"
            )

        command = [
            str(REAL_CALL_SCRIPT),
            *args,
        ]

        completed = subprocess.run(
            command,
            cwd=str(REPO_ROOT),
            env=self._base_env(),
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )

        parsed = (
            self._parse_contract_output(
                completed.stdout
            )
        )

        return {
            "ok":
                completed.returncode == 0,

            "mode":
                self.mode,

            "returncode":
                completed.returncode,

            "operation_state":
                parsed[
                    "operation_state"
                ],

            "external_dial_requested":
                parsed[
                    "external_dial_requested"
                ],

            "stdout":
                completed.stdout,

            "stderr":
                completed.stderr,
        }


    def _prepare_safe_stub(self):
        """
        CONTACT_FAMILY 开发安全模式。

        不调用任何电话脚本，
        不访问 Android，
        不读取 token，
        不产生真实外拨。
        """

        return {
            "ok": True,
            "mode": "safe_stub",
            "ready": True,

            "operation_state":
                "local_ready",

            "external_dial_requested":
                False,

            "display_state":
                "PHONE_LOCAL_SAFE_READY",

            "stdout": "",
            "stderr": "",
        }


    def _new_output_dir(
        self,
        prefix,
    ):
        stamp = datetime.now().strftime(
            "%Y%m%d-%H%M%S"
        )

        path = (
            REPO_ROOT
            / "runs"
            / "contact-family-phone"
            / f"{prefix}-{stamp}-{os.getpid()}"
        )

        path.mkdir(
            parents=True,
            exist_ok=True,
        )

        return path


    def _require_real_config(self):
        if not self.phone_url:
            raise CallBackendError(
                "真实拨号缺少 G1_PHONE_URL"
            )

        if not PHONE_DIAL_SCRIPT.exists():
            raise CallBackendError(
                "找不到 Android 拨号 client: "
                f"{PHONE_DIAL_SCRIPT}"
            )


    def _run_phone_client(
        self,
        *,
        preflight=False,
        timeout=45,
    ):
        self._require_real_config()

        prefix = (
            "preflight"
            if preflight
            else "dial"
        )

        output_dir = (
            self._new_output_dir(
                prefix
            )
        )

        command = [
            sys.executable,
            str(PHONE_DIAL_SCRIPT),

            "--phone-url",
            self.phone_url,

            "--output-dir",
            str(output_dir),
        ]

        if preflight:
            command.append(
                "--preflight"
            )

        else:
            token_file = Path(
                os.getenv(
                    "G1_PHONE_TOKEN_FILE",
                    str(
                        DEFAULT_TOKEN_FILE
                    ),
                )
            )

            if not token_file.exists():
                raise CallBackendError(
                    "真实拨号 token 文件不存在: "
                    f"{token_file}"
                )

            token = (
                token_file
                .read_text(
                    encoding="utf-8"
                )
                .strip()
            )

            if not token:
                raise CallBackendError(
                    "真实拨号 token 为空"
                )

            command.extend(
                [
                    "--token",
                    token,

                    "--confirm-g1-phone-dial",
                ]
            )

        completed = subprocess.run(
            command,
            cwd=str(REPO_ROOT),
            env=self._base_env(),
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )

        parsed = (
            self._parse_contract_output(
                completed.stdout
            )
        )

        return {
            "ok":
                completed.returncode == 0,

            "mode":
                self.mode,

            "returncode":
                completed.returncode,

            "operation_state":
                parsed[
                    "operation_state"
                ],

            "external_dial_requested":
                parsed[
                    "external_dial_requested"
                ],

            "contract":
                parsed.get(
                    "contract"
                ),

            "output_dir":
                str(output_dir),

            "stdout":
                completed.stdout,

            "stderr":
                completed.stderr,
        }


    def prepare(self):
        """
        电话准备阶段。

        dry_run:
            只验证队友拨号编排可以计划，
            不访问手机。

        real:
            执行真正 preflight，
            但不产生电话。
        """

        if self.mode == "safe_stub":
            return self._prepare_safe_stub()

        if self.mode == "dry_run":

            result = self._run_script(
                ["--dry-run"],
                timeout=30,
            )

            result[
                "ready"
            ] = (
                result["ok"]
                and
                result[
                    "operation_state"
                ] == "planned"
                and
                result[
                    "external_dial_requested"
                ] is False
            )

            result[
                "display_state"
            ] = (
                "PHONE_DRY_RUN_READY"
                if result["ready"]
                else "PHONE_DRY_RUN_FAILED"
            )

            return result

        result = self._run_phone_client(
            preflight=True,
            timeout=45,
        )

        result["ready"] = (
            result["ok"]
            and
            result.get(
                "operation_state"
            ) == "preflight_ok"
        )

        result[
            "display_state"
        ] = (
            "PHONE_PREFLIGHT_READY"
            if result["ready"]
            else "PHONE_PREFLIGHT_FAILED"
        )

        return result


    def dial(self):
        """
        调用真实外部拨号。

        dry_run 永远不会外拨。
        """

        if self.mode == "safe_stub":

            return {
                "ok": True,
                "mode": "safe_stub",

                "operation_state":
                    "simulated",

                "external_dial_requested":
                    False,

                "dial_status":
                    "safe_stub_only",

                "display_state":
                    "DIAL_NOT_SENT_SAFE_STUB",
            }

        if self.mode == "dry_run":

            return {
                "ok": True,
                "mode": self.mode,

                "operation_state":
                    "planned",

                "external_dial_requested":
                    False,

                "dial_status":
                    "dry_run_only",

                "display_state":
                    "DIAL_NOT_SENT_DRY_RUN",
            }

        result = self._run_phone_client(
            preflight=False,
            timeout=45,
        )

        # 注意：
        # 脚本成功也只能说明拨号请求流程成功。
        # 不能把它解释成“电话已经接通”。
        result[
            "dial_status"
        ] = (
            result.get(
                "operation_state"
            )
            or (
                "request_finished"
                if result["ok"]
                else "failed"
            )
        )

        result[
            "display_state"
        ] = (
            "DIAL_REQUEST_FINISHED"
            if result["ok"]
            else "DIAL_REQUEST_FAILED"
        )

        return result
