from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent

SCENE_DIR = (
    ROOT
    / "scenarios"
    / "contact_family"
)

sys.path.insert(
    0,
    str(SCENE_DIR),
)


from call_backend import (
    ContactCallBackend,
)


class FakeCompleted:

    def __init__(
        self,
        *,
        returncode=0,
        stdout="",
        stderr="",
    ):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class ContactCallBackendTest(
    unittest.TestCase
):

    def test_invalid_mode(self):
        with self.assertRaises(
            ValueError
        ):
            ContactCallBackend(
                mode="unknown"
            )


    def test_parse_json_contract(self):
        result = (
            ContactCallBackend
            ._parse_contract_output(
                (
                    '{"contact_id":"owner",'
                    '"external_dial_requested":false,'
                    '"mode":"dry_run",'
                    '"operation_state":"planned",'
                    '"schema_version":'
                    '"g1_contact_family_call_v1"}'
                )
            )
        )

        self.assertEqual(
            result[
                "operation_state"
            ],
            "planned",
        )

        self.assertIs(
            result[
                "external_dial_requested"
            ],
            False,
        )

        self.assertEqual(
            result[
                "contract"
            ][
                "contact_id"
            ],
            "owner",
        )



    def test_parse_dry_run_contract(self):
        result = (
            ContactCallBackend
            ._parse_contract_output(
                """
operation_state=planned
external_dial_requested=false
"""
            )
        )

        self.assertEqual(
            result[
                "operation_state"
            ],
            "planned",
        )

        self.assertIs(
            result[
                "external_dial_requested"
            ],
            False,
        )


    @patch(
        "call_backend.subprocess.run"
    )
    def test_dry_run_prepare(
        self,
        run,
    ):
        run.return_value = (
            FakeCompleted(
                stdout=(
                    "operation_state=planned\n"
                    "external_dial_requested=false\n"
                )
            )
        )

        backend = (
            ContactCallBackend(
                mode="dry_run"
            )
        )

        result = backend.prepare()

        self.assertTrue(
            result["ready"]
        )

        self.assertFalse(
            result[
                "external_dial_requested"
            ]
        )

        self.assertEqual(
            result[
                "display_state"
            ],
            "PHONE_DRY_RUN_READY",
        )

        command = (
            run.call_args.args[0]
        )

        self.assertIn(
            "--dry-run",
            command,
        )


    def test_real_prepare_uses_preflight(self):
        """
        real prepare 应进入 Android client preflight。

        这里 mock 整个底层 client，
        不访问手机、不访问网络。
        """

        backend = ContactCallBackend(
            mode="real",
            phone_url=
                "http://10.0.0.2:8765",
        )

        fake_result = {
            "ok": True,
            "mode": "real",
            "operation_state":
                "preflight_ok",
            "external_dial_requested":
                False,
        }

        with patch.object(
            backend,
            "_run_phone_client",
            return_value=fake_result,
        ) as run:

            result = backend.prepare()

        run.assert_called_once_with(
            preflight=True,
            timeout=45,
        )

        self.assertTrue(
            result["ready"]
        )

        self.assertEqual(
            result[
                "display_state"
            ],
            "PHONE_PREFLIGHT_READY",
        )

        self.assertFalse(
            result[
                "external_dial_requested"
            ]
        )

    @patch(
        "call_backend.subprocess.run"
    )
    def test_real_preflight_passes_uncreated_output_directory(
        self,
        run,
    ):
        run.return_value = (
            FakeCompleted(
                stdout=(
                    '{"operation_state":"preflight_ok",'
                    '"external_dial_requested":false}'
                )
            )
        )

        with tempfile.TemporaryDirectory() as directory:
            backend = ContactCallBackend(
                mode="real",
                phone_url="http://10.0.0.2:8765",
            )

            with patch(
                "call_backend.REPO_ROOT",
                Path(directory),
            ):
                result = backend._run_phone_client(
                    preflight=True,
                )

            output_dir = Path(
                result["output_dir"]
            )

            self.assertFalse(
                output_dir.exists()
            )

            command = run.call_args.args[0]

            self.assertEqual(
                command[
                    command.index("--output-dir")
                    + 1
                ],
                str(output_dir),
            )

    @patch(
        "call_backend.subprocess.run"
    )
    def test_dry_run_dial_never_calls_external_script(
        self,
        run,
    ):
        backend = (
            ContactCallBackend(
                mode="dry_run"
            )
        )

        result = backend.dial()

        run.assert_not_called()

        self.assertTrue(
            result["ok"]
        )

        self.assertFalse(
            result[
                "external_dial_requested"
            ]
        )

        self.assertEqual(
            result[
                "dial_status"
            ],
            "dry_run_only",
        )


    def test_real_dial_uses_real_entry(self):
        """
        DIAL_AUTHORIZED 后 real backend
        应进入底层 Android dial client。

        本测试完全 mock 底层 client，
        不读取 token、不访问手机、不真实拨号。
        """

        backend = ContactCallBackend(
            mode="real",
            phone_url=
                "http://10.0.0.2:8765",
        )

        fake_result = {
            "ok": True,
            "mode": "real",
            "operation_state":
                "accepted",
            "external_dial_requested":
                True,
        }

        with patch.object(
            backend,
            "_run_phone_client",
            return_value=fake_result,
        ) as run:

            result = backend.dial()

        run.assert_called_once_with(
            preflight=False,
            timeout=45,
        )

        self.assertTrue(
            result["ok"]
        )

        self.assertEqual(
            result[
                "operation_state"
            ],
            "accepted",
        )

        self.assertTrue(
            result[
                "external_dial_requested"
            ]
        )

        self.assertEqual(
            result[
                "dial_status"
            ],
            "accepted",
        )

if __name__ == "__main__":
    unittest.main(
        verbosity=2
    )
