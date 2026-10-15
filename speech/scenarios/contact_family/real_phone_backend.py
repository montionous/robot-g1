from __future__ import annotations

import os
import subprocess
from pathlib import Path


SCENE_DIR = (
    Path(__file__)
    .resolve()
    .parent
)

SPEECH_ROOT = (
    SCENE_DIR.parents[1]
)

REPO_ROOT = (
    SPEECH_ROOT.parent
)

CALL_SCRIPT = (
    REPO_ROOT
    / "scripts"
    / "g1_call_owner_once.sh"
)


class RealPhoneBackendError(
    RuntimeError
):
    pass


class RealPhoneBackend:

    def __init__(
        self,
        *,
        phone_url=None,
        token_file=None,
    ):
        self.phone_url = (
            phone_url
            or os.getenv(
                "G1_PHONE_URL",
                "",
            ).strip()
        )

        self.token_file = (
            token_file
            or os.getenv(
                "G1_PHONE_TOKEN_FILE",
                (
                    str(
                        Path.home()
                        / ".config"
                        / "g1-phone-dial"
                        / "token"
                    )
                ),
            )
        )


    def _env(self):
        env = os.environ.copy()

        if self.phone_url:
            env[
                "G1_PHONE_URL"
            ] = self.phone_url

        env[
            "G1_PHONE_TOKEN_FILE"
        ] = str(
            self.token_file
        )

        return env


    def _run(
        self,
        args,
        *,
        timeout,
    ):
        if not CALL_SCRIPT.exists():
            raise RealPhoneBackendError(
                "未找到队友拨号入口: "
                f"{CALL_SCRIPT}"
            )

        command = [
            str(CALL_SCRIPT),
            *args,
        ]

        completed = subprocess.run(
            command,
            cwd=str(REPO_ROOT),
            env=self._env(),
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )

        return {
            "ok":
                completed.returncode == 0,

            "returncode":
                completed.returncode,

            "stdout":
                completed.stdout,

            "stderr":
                completed.stderr,

            "command":
                [
                    str(CALL_SCRIPT),
                    *args,
                ],
        }


    def dry_run(self):
        """
        完全不访问手机，
        适合现在没有队友手机时测试。
        """

        return self._run(
            ["--dry-run"],
            timeout=30,
        )


    def preflight(self):
        """
        检查手机/语音/PCM，
        不拨号。
        """

        return self._run(
            ["--preflight"],
            timeout=30,
        )


    def dial_owner_once(self):
        """
        真实入口。

        注意：
        队友的一键脚本自身仍会要求
        现场“确认拨号”。

        当前阶段先保留该安全行为。
        """

        return self._run(
            [],
            timeout=120,
        )
