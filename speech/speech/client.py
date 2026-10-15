from __future__ import annotations

from pathlib import Path

import requests


class SpeechClient:

    def __init__(
        self,
        base_url="http://127.0.0.1:8780",
        *,
        token=None,
        timeout=90,
    ):

        self.base_url = (
            base_url.rstrip("/")
        )

        self.timeout = timeout

        self.headers = {}

        if token:

            self.headers[
                "X-Speech-Token"
            ] = token

    def health(self):

        response = requests.get(
            f"{self.base_url}/health",
            timeout=5,
        )

        response.raise_for_status()

        return response.json()

    def speak(
        self,
        text,
        *,
        style="normal",
        dialect="mandarin",
        speed=None,
        pitch=None,
        volume=None,
        emotion=None,
        play_on_host=False,
    ):

        response = requests.post(
            f"{self.base_url}/speak",

            headers=self.headers,

            json={
                "text":
                    text,

                "style":
                    style,

                "dialect":
                    dialect,

                "speed":
                    speed,

                "pitch":
                    pitch,

                "volume":
                    volume,

                "emotion":
                    emotion,

                "play_on_host":
                    play_on_host,
            },

            timeout=self.timeout,
        )

        response.raise_for_status()

        return response.json()

    def transcribe(
        self,
        audio_path,
        *,
        language=None,
        enable_itn=True,
    ):

        path = Path(
            audio_path
        )

        if not path.exists():
            raise FileNotFoundError(
                path
            )

        data = {
            "enable_itn":
                str(
                    bool(
                        enable_itn
                    )
                ).lower(),
        }

        if language:

            data[
                "language"
            ] = language

        with path.open(
            "rb"
        ) as f:

            response = requests.post(
                f"{self.base_url}/asr",

                headers=self.headers,

                files={
                    "file": (
                        path.name,
                        f,
                    )
                },

                data=data,

                timeout=self.timeout,
            )

        response.raise_for_status()

        return response.json()
