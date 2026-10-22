from __future__ import annotations

import argparse
import contextlib
import io
import os
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from robot_leds import (
    RobotLedClient,
    add_robot_led_arguments,
    validate_robot_led_arguments,
)


class RecordingRunner:
    def __init__(self, *, returncode: int = 0, output: str = "") -> None:
        self.calls: list[tuple[list[str], dict]] = []
        self.returncode = returncode
        self.output = output

    def __call__(self, command, **kwargs):
        self.calls.append((list(command), dict(kwargs)))
        return SimpleNamespace(
            returncode=self.returncode,
            stdout=self.output,
        )


class RobotLedClientTests(unittest.TestCase):
    def test_dry_run_prints_request_without_running_script(self):
        runner = RecordingRunner()
        client = RobotLedClient(
            mode="dry-run",
            script_path="/does/not/exist.sh",
            runner=runner,
        )

        result = client.show("processing", source="test")

        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["effect"], 18)
        self.assertEqual(runner.calls, [])
        self.assertEqual(
            result["command"],
            [
                "bash",
                str(Path("/does/not/exist.sh")),
                "--confirm-g1-led-demo",
                "18",
            ],
        )

    def test_off_never_runs_script(self):
        runner = RecordingRunner()
        client = RobotLedClient(mode="off", runner=runner)

        result = client.show("listening")

        self.assertEqual(result["status"], "off")
        self.assertEqual(runner.calls, [])

    def test_execute_requires_confirmation_even_when_script_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "g1_companion_led_test.sh"
            script.touch()
            runner = RecordingRunner()
            client = RobotLedClient(
                mode="execute",
                confirm_writes=False,
                script_path=script,
                runner=runner,
            )

            result = client.show("acknowledged")

        self.assertEqual(result["status"], "confirmation_required")
        self.assertEqual(runner.calls, [])

    def test_execute_uses_the_explicit_led_script_argv(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "g1_companion_led_test.sh"
            script.touch()
            runner = RecordingRunner(output="ok")
            client = RobotLedClient(
                mode="execute",
                confirm_writes=True,
                script_path=script,
                runner=runner,
            )

            result = client.show("confirmation", source="contact_family")
            self.assertTrue(client.wait_for_idle(1.0))

        self.assertEqual(result["status"], "started")
        self.assertEqual(client.last_execution["status"], "completed")
        self.assertEqual(
            runner.calls[0][0],
            [
                "bash",
                str(script),
                "--confirm-g1-led-demo",
                "20",
            ],
        )
        self.assertTrue(runner.calls[0][1]["check"] is False)

    def test_missing_script_is_safe(self):
        runner = RecordingRunner()
        client = RobotLedClient(
            mode="execute",
            confirm_writes=True,
            script_path="/does/not/exist.sh",
            runner=runner,
        )

        result = client.show("farewell")

        self.assertEqual(result["status"], "missing_script")
        self.assertEqual(runner.calls, [])

    def test_short_duplicate_is_not_relaunched(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "g1_companion_led_test.sh"
            script.touch()
            runner = RecordingRunner()
            client = RobotLedClient(
                mode="execute",
                confirm_writes=True,
                script_path=script,
                runner=runner,
            )

            first = client.show("listening")
            second = client.show("listening")
            self.assertTrue(client.wait_for_idle(1.0))

        self.assertEqual(first["status"], "started")
        self.assertEqual(second["status"], "deduplicated")
        self.assertEqual(len(runner.calls), 1)

    def test_script_failure_does_not_raise(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "g1_companion_led_test.sh"
            script.touch()
            client = RobotLedClient(
                mode="execute",
                confirm_writes=True,
                script_path=script,
                runner=RecordingRunner(returncode=7),
            )

            result = client.show("retry")
            self.assertTrue(client.wait_for_idle(1.0))

        self.assertEqual(result["status"], "started")
        self.assertEqual(client.last_execution["status"], "failed")
        self.assertEqual(client.last_execution["returncode"], 7)

    def test_timeout_does_not_raise(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "g1_companion_led_test.sh"
            script.touch()

            def timeout_runner(*_args, **_kwargs):
                raise subprocess.TimeoutExpired("g1_companion_led_test.sh", 2)

            client = RobotLedClient(
                mode="execute",
                confirm_writes=True,
                script_path=script,
                runner=timeout_runner,
            )

            result = client.show("processing")
            self.assertTrue(client.wait_for_idle(1.0))

        self.assertEqual(result["status"], "started")
        self.assertEqual(client.last_execution["status"], "timeout")

    def test_execute_does_not_block_and_keeps_only_latest_pending_effect(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "g1_companion_led_test.sh"
            script.touch()
            entered = threading.Event()
            release = threading.Event()
            calls: list[list[str]] = []

            def slow_runner(command, **_kwargs):
                calls.append(list(command))
                entered.set()
                release.wait(1.0)
                return SimpleNamespace(returncode=0, stdout="")

            client = RobotLedClient(
                mode="execute",
                confirm_writes=True,
                script_path=script,
                runner=slow_runner,
            )

            started_at = time.monotonic()
            first = client.show("listening")
            elapsed = time.monotonic() - started_at
            self.assertEqual(first["status"], "started")
            self.assertLess(elapsed, 0.1)
            self.assertTrue(entered.wait(1.0))

            second = client.show("farewell")
            self.assertEqual(second["status"], "started")
            release.set()
            self.assertTrue(client.wait_for_idle(1.0))

        self.assertEqual([command[-1] for command in calls], ["25", "22"])

    @unittest.skipUnless(os.name == "posix", "requires POSIX process groups")
    def test_real_wrapper_process_group_is_cancelled_before_next_effect(self):
        """A newer effect must stop wrapper descendants, not just its shell.

        The real teammate wrapper has a shell pipeline and may keep a dynamic
        effect alive.  This local stand-in deliberately backgrounds a child
        that ignores the first SIGINT; seeing its TERM cleanup marker proves
        the process-group escalation reached it before the next effect runs.
        """

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "g1_companion_led_test.sh"
            started = root / "started"
            stopped = root / "stopped"
            script.write_text(
                "#!/usr/bin/env bash\n"
                "set -eu\n"
                "if [ \"$2\" = \"25\" ]; then\n"
                "  (\n"
                "    trap '' INT\n"
                f"    trap 'printf stopped > {stopped}' TERM\n"
                "    while :; do sleep 30; done\n"
                "  ) &\n"
                f"  printf started > {started}\n"
                "  wait $!\n"
                "fi\n",
                encoding="utf-8",
            )
            client = RobotLedClient(
                mode="execute",
                confirm_writes=True,
                script_path=script,
                command_timeout=5.0,
            )

            self.assertEqual(client.show("listening")["status"], "started")
            deadline = time.monotonic() + 1.0
            while not started.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(started.exists())

            self.assertEqual(client.show("farewell")["status"], "started")
            self.assertTrue(client.wait_for_idle(4.0))
            self.assertTrue(stopped.exists())
            self.assertEqual(client.last_execution["status"], "completed")
            self.assertEqual(client.last_execution["event"], "farewell")

    @unittest.skipUnless(os.name == "posix", "requires POSIX process groups")
    def test_real_wrapper_timeout_returns_after_group_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "g1_companion_led_test.sh"
            script.write_text(
                "#!/usr/bin/env bash\n"
                "set -eu\n"
                "sleep 30 &\n"
                "wait $!\n",
                encoding="utf-8",
            )
            client = RobotLedClient(
                mode="execute",
                confirm_writes=True,
                script_path=script,
                command_timeout=0.1,
            )

            started_at = time.monotonic()
            self.assertEqual(client.show("processing")["status"], "started")
            self.assertTrue(client.wait_for_idle(3.0))
            elapsed = time.monotonic() - started_at

        self.assertEqual(client.last_execution["status"], "timeout")
        self.assertLess(elapsed, 3.0)


class RobotLedArgumentTests(unittest.TestCase):
    def _parser(self):
        parser = argparse.ArgumentParser()
        add_robot_led_arguments(parser)
        return parser

    def test_defaults_to_safe_dry_run(self):
        parser = self._parser()
        args = parser.parse_args([])

        validate_robot_led_arguments(parser, args)

        self.assertEqual(args.robot_leds, "dry-run")
        self.assertFalse(args.confirm_g1_led_demo)

    def test_execute_requires_explicit_confirmation(self):
        parser = self._parser()
        args = parser.parse_args(["--robot-leds", "execute"])

        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                validate_robot_led_arguments(parser, args)

    def test_confirmation_requires_execute_mode(self):
        parser = self._parser()
        args = parser.parse_args(["--confirm-g1-led-demo"])

        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                validate_robot_led_arguments(parser, args)

    def test_execute_and_confirmation_are_accepted(self):
        parser = self._parser()
        args = parser.parse_args(
            ["--robot-leds", "execute", "--confirm-g1-led-demo"]
        )

        validate_robot_led_arguments(parser, args)


if __name__ == "__main__":
    unittest.main()
