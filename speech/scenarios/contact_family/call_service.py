from __future__ import annotations

import tempfile
import time
from pathlib import Path

import requests


class CallServiceError(
    RuntimeError
):
    pass


class MockCallService:

    def __init__(
        self,
        base_url=(
            "http://127.0.0.1:8790"
        ),
        *,
        timeout=5.0,
    ):
        self.base_url = (
            base_url.rstrip("/")
        )

        self.timeout = timeout


    def health(self):
        response = requests.get(
            f"{self.base_url}/health",
            timeout=self.timeout,
        )

        response.raise_for_status()

        return response.json()


    def start_call(
        self,
        *,
        elderly_id,
        elderly_name,
        contact_id,
        contact_name,
        relation,
        phone_masked,
    ):
        response = requests.post(
            f"{self.base_url}/api/calls",

            json={
                "elderly_id":
                    elderly_id,

                "elderly_name":
                    elderly_name,

                "contact_id":
                    contact_id,

                "contact_name":
                    contact_name,

                "relation":
                    relation,

                "phone_masked":
                    phone_masked,
            },

            timeout=self.timeout,
        )

        response.raise_for_status()

        data = response.json()

        return data["call"]


    def get_call(
        self,
        call_id,
    ):
        response = requests.get(
            (
                f"{self.base_url}"
                f"/api/calls/{call_id}"
            ),
            timeout=self.timeout,
        )

        response.raise_for_status()

        return (
            response.json()[
                "call"
            ]
        )


    def hangup(
        self,
        call_id,
    ):
        response = requests.post(
            (
                f"{self.base_url}"
                f"/api/calls/"
                f"{call_id}/hangup"
            ),
            timeout=self.timeout,
        )

        response.raise_for_status()

        return (
            response.json()[
                "call"
            ]
        )


    def mark_no_answer(
        self,
        call_id,
    ):
        response = requests.post(
            (
                f"{self.base_url}"
                f"/api/calls/"
                f"{call_id}/no_answer"
            ),
            timeout=self.timeout,
        )

        response.raise_for_status()

        return (
            response.json()[
                "call"
            ]
        )


    def wait_for_answer(
        self,
        call_id,
        *,
        timeout=20.0,
        poll_interval=0.5,
    ):
        deadline = (
            time.monotonic()
            + timeout
        )

        while (
            time.monotonic()
            < deadline
        ):
            call = self.get_call(
                call_id
            )

            status = call[
                "status"
            ]

            if status in {
                "answered",
                "rejected",
                "no_answer",
                "completed",
            }:
                return call

            time.sleep(
                poll_interval
            )

        return self.mark_no_answer(
            call_id
        )


    def upload_elderly_audio(
        self,
        call_id,
        wav_path,
    ):
        wav_path = Path(
            wav_path
        )

        response = requests.post(
            (
                f"{self.base_url}"
                f"/api/calls/"
                f"{call_id}"
                f"/audio/elderly"
            ),
            data=wav_path.read_bytes(),
            headers={
                "Content-Type":
                    "audio/wav",
            },
            timeout=max(
                self.timeout,
                15.0,
            ),
        )

        response.raise_for_status()

        return (
            response.json()[
                "message"
            ]
        )


    def get_audio_messages(
        self,
        call_id,
        *,
        after=0,
        sender=None,
    ):
        params = {
            "after":
                int(after),
        }

        if sender is not None:
            params["sender"] = sender

        response = requests.get(
            (
                f"{self.base_url}"
                f"/api/calls/"
                f"{call_id}/audio"
            ),
            params=params,
            timeout=self.timeout,
        )

        response.raise_for_status()

        return (
            response.json()[
                "messages"
            ]
        )


    def wait_for_family_audio(
        self,
        call_id,
        *,
        after=0,
        timeout=60.0,
        poll_interval=0.5,
    ):
        deadline = (
            time.monotonic()
            + timeout
        )

        while (
            time.monotonic()
            < deadline
        ):
            messages = (
                self.get_audio_messages(
                    call_id,
                    after=after,
                    sender="family",
                )
            )

            if messages:
                return {
                    "status":
                        "audio",

                    "message":
                        messages[0],
                }

            call = self.get_call(
                call_id
            )

            if call["status"] != "answered":
                return {
                    "status":
                        call["status"],

                    "message":
                        None,
                }

            time.sleep(
                poll_interval
            )

        return {
            "status":
                "timeout",

            "message":
                None,
        }


    def download_audio(
        self,
        message,
    ):
        audio_url = message[
            "audio_url"
        ]

        if audio_url.startswith(
            "http://"
        ) or audio_url.startswith(
            "https://"
        ):
            url = audio_url

        else:
            url = (
                self.base_url
                + audio_url
            )

        response = requests.get(
            url,
            timeout=max(
                self.timeout,
                20.0,
            ),
        )

        response.raise_for_status()

        fd = (
            tempfile
            .NamedTemporaryFile(
                prefix="family_call_",
                suffix=".wav",
                delete=False,
            )
        )

        try:
            fd.write(
                response.content
            )

            path = Path(
                fd.name
            )

        finally:
            fd.close()

        return path
