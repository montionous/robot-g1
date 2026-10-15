#!/usr/bin/env python3

from __future__ import annotations

import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from threading import Lock
from uuid import uuid4

import uvicorn

from fastapi import (
    FastAPI,
    HTTPException,
    Request,
)

from fastapi.responses import (
    FileResponse,
    HTMLResponse,
)

from pydantic import BaseModel


app = FastAPI(
    title="CONTACT_FAMILY Mock Call Server"
)


SCENE_DIR = Path(__file__).resolve().parent
SPEECH_ROOT = SCENE_DIR.parents[1]

AUDIO_ROOT = (
    SPEECH_ROOT
    / "runtime"
    / "mock_calls"
)

AUDIO_ROOT.mkdir(
    parents=True,
    exist_ok=True,
)


CALLS = {}
CALL_ORDER = []

AUDIO_MESSAGES = {}
AUDIO_INDEX = {}

AUDIO_SEQ = 0

LOCK = Lock()


MAX_AUDIO_BYTES = (
    12
    * 1024
    * 1024
)


def now():
    return datetime.now().isoformat(
        timespec="seconds"
    )


class CreateCallRequest(BaseModel):
    elderly_id: int
    elderly_name: str

    contact_id: int
    contact_name: str
    relation: str

    phone_masked: str


def get_call_or_404(
    call_id: str,
):
    with LOCK:
        call = CALLS.get(
            call_id
        )

        if call is None:
            raise HTTPException(
                status_code=404,
                detail="call_not_found",
            )

        return dict(call)


def next_audio_id():
    global AUDIO_SEQ

    with LOCK:
        AUDIO_SEQ += 1
        return AUDIO_SEQ


def extension_for_content_type(
    content_type,
):
    content_type = (
        str(content_type or "")
        .split(";")[0]
        .strip()
        .lower()
    )

    mapping = {
        "audio/wav": ".wav",
        "audio/x-wav": ".wav",
        "audio/webm": ".webm",
        "audio/mp4": ".m4a",
        "audio/mpeg": ".mp3",
        "audio/ogg": ".ogg",
    }

    return mapping.get(
        content_type,
        ".bin",
    )


def convert_to_g1_wav(
    source_path: Path,
    output_path: Path,
):
    ffmpeg = shutil.which(
        "ffmpeg"
    )

    if not ffmpeg:
        raise RuntimeError(
            "ffmpeg_not_found"
        )

    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source_path),
        "-ar",
        "16000",
        "-ac",
        "1",
        "-c:a",
        "pcm_s16le",
        str(output_path),
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "ffmpeg_convert_failed: "
            + (
                result.stderr.strip()
                or "unknown_error"
            )
        )


@app.get("/health")
def health():
    return {
        "ok": True,
        "service":
            "mock-call-server",
        "audio_root":
            str(AUDIO_ROOT),
        "ffmpeg":
            shutil.which("ffmpeg"),
    }


@app.post("/api/calls")
def create_call(
    request: CreateCallRequest,
):
    call_id = (
        uuid4()
        .hex[:12]
    )

    call = {
        "id":
            call_id,

        "elderly_id":
            request.elderly_id,

        "elderly_name":
            request.elderly_name,

        "contact_id":
            request.contact_id,

        "contact_name":
            request.contact_name,

        "relation":
            request.relation,

        "phone_masked":
            request.phone_masked,

        "status":
            "ringing",

        "created_at":
            now(),

        "answered_at":
            None,

        "ended_at":
            None,
    }

    call_audio_dir = (
        AUDIO_ROOT
        / call_id
    )

    call_audio_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    with LOCK:
        CALLS[
            call_id
        ] = call

        CALL_ORDER.append(
            call_id
        )

        AUDIO_MESSAGES[
            call_id
        ] = []

    return {
        "ok": True,
        "call": call,
    }


@app.get("/api/calls/latest")
def latest_call():
    with LOCK:
        if not CALL_ORDER:
            return {
                "ok": True,
                "call": None,
            }

        call_id = (
            CALL_ORDER[-1]
        )

        return {
            "ok": True,
            "call":
                dict(
                    CALLS[call_id]
                ),
        }


@app.get("/api/calls/{call_id}")
def get_call(
    call_id: str,
):
    return {
        "ok": True,
        "call":
            get_call_or_404(
                call_id
            ),
    }


@app.post("/api/calls/{call_id}/answer")
def answer_call(
    call_id: str,
):
    with LOCK:
        call = CALLS.get(
            call_id
        )

        if call is None:
            raise HTTPException(
                status_code=404,
                detail="call_not_found",
            )

        if call["status"] != "ringing":
            return {
                "ok": True,
                "call":
                    dict(call),
            }

        call["status"] = "answered"
        call["answered_at"] = now()

        return {
            "ok": True,
            "call":
                dict(call),
        }


@app.post("/api/calls/{call_id}/reject")
def reject_call(
    call_id: str,
):
    with LOCK:
        call = CALLS.get(
            call_id
        )

        if call is None:
            raise HTTPException(
                status_code=404,
                detail="call_not_found",
            )

        if call["status"] == "ringing":
            call["status"] = "rejected"
            call["ended_at"] = now()

        return {
            "ok": True,
            "call":
                dict(call),
        }


@app.post("/api/calls/{call_id}/no_answer")
def no_answer(
    call_id: str,
):
    with LOCK:
        call = CALLS.get(
            call_id
        )

        if call is None:
            raise HTTPException(
                status_code=404,
                detail="call_not_found",
            )

        if call["status"] == "ringing":
            call["status"] = "no_answer"
            call["ended_at"] = now()

        return {
            "ok": True,
            "call":
                dict(call),
        }


@app.post("/api/calls/{call_id}/hangup")
def hangup(
    call_id: str,
):
    with LOCK:
        call = CALLS.get(
            call_id
        )

        if call is None:
            raise HTTPException(
                status_code=404,
                detail="call_not_found",
            )

        if call["status"] == "answered":
            call["status"] = "completed"
            call["ended_at"] = now()

        return {
            "ok": True,
            "call":
                dict(call),
        }


@app.post(
    "/api/calls/{call_id}/audio/{sender}"
)
async def upload_audio(
    call_id: str,
    sender: str,
    request: Request,
):
    if sender not in {
        "elderly",
        "family",
    }:
        raise HTTPException(
            status_code=400,
            detail="invalid_sender",
        )

    call = get_call_or_404(
        call_id
    )

    if call["status"] != "answered":
        raise HTTPException(
            status_code=409,
            detail=(
                "call_not_answered"
            ),
        )

    body = await request.body()

    if not body:
        raise HTTPException(
            status_code=400,
            detail="empty_audio",
        )

    if len(body) > MAX_AUDIO_BYTES:
        raise HTTPException(
            status_code=413,
            detail="audio_too_large",
        )

    content_type = (
        request.headers.get(
            "content-type",
            "application/octet-stream",
        )
    )

    extension = (
        extension_for_content_type(
            content_type
        )
    )

    audio_id = next_audio_id()

    call_dir = (
        AUDIO_ROOT
        / call_id
    )

    call_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    source_path = (
        call_dir
        / (
            f"{audio_id:06d}_"
            f"{sender}"
            f"{extension}"
        )
    )

    source_path.write_bytes(
        body
    )

    wav_path = (
        call_dir
        / (
            f"{audio_id:06d}_"
            f"{sender}.wav"
        )
    )

    source_type = (
        str(content_type)
        .split(";")[0]
        .lower()
        .strip()
    )

    if (
        source_type
        in {
            "audio/wav",
            "audio/x-wav",
        }
        and extension == ".wav"
    ):
        if source_path != wav_path:
            shutil.copyfile(
                source_path,
                wav_path,
            )

    else:
        try:
            convert_to_g1_wav(
                source_path,
                wav_path,
            )

        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=str(exc),
            ) from exc

    message = {
        "id":
            audio_id,

        "call_id":
            call_id,

        "sender":
            sender,

        "created_at":
            now(),

        "mime_type":
            "audio/wav",

        "audio_url":
            f"/api/audio/{audio_id}",

        "size_bytes":
            wav_path.stat().st_size,

        "_path":
            str(wav_path),
    }

    with LOCK:
        AUDIO_MESSAGES.setdefault(
            call_id,
            [],
        ).append(
            message
        )

        AUDIO_INDEX[
            audio_id
        ] = message

    public_message = dict(
        message
    )

    public_message.pop(
        "_path",
        None,
    )

    return {
        "ok": True,
        "message":
            public_message,
    }


@app.get(
    "/api/calls/{call_id}/audio"
)
def list_audio(
    call_id: str,
    after: int = 0,
    sender: str | None = None,
):
    get_call_or_404(
        call_id
    )

    if (
        sender is not None
        and sender not in {
            "elderly",
            "family",
        }
    ):
        raise HTTPException(
            status_code=400,
            detail="invalid_sender",
        )

    with LOCK:
        messages = []

        for item in AUDIO_MESSAGES.get(
            call_id,
            [],
        ):
            if item["id"] <= after:
                continue

            if (
                sender is not None
                and item["sender"]
                != sender
            ):
                continue

            public_item = dict(
                item
            )

            public_item.pop(
                "_path",
                None,
            )

            messages.append(
                public_item
            )

    return {
        "ok": True,
        "messages":
            messages,
    }


@app.get("/api/audio/{audio_id}")
def get_audio(
    audio_id: int,
):
    with LOCK:
        message = AUDIO_INDEX.get(
            audio_id
        )

        if message is None:
            raise HTTPException(
                status_code=404,
                detail="audio_not_found",
            )

        path = Path(
            message["_path"]
        )

    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail="audio_file_not_found",
        )

    return FileResponse(
        str(path),
        media_type="audio/wav",
        filename=path.name,
        headers={
            "Cache-Control":
                "no-store",
        },
    )


FAMILY_HTML = r"""
<!doctype html>

<html lang="zh-CN">

<head>
<meta charset="utf-8">

<meta
    name="viewport"
    content="width=device-width, initial-scale=1"
>

<title>家属端模拟电话</title>

<style>

body {
    font-family:
        Arial,
        "Microsoft YaHei",
        sans-serif;

    background: #f3f4f6;

    margin: 0;

    padding: 20px;
}

.card {
    max-width: 520px;

    margin: 30px auto;

    background: white;

    border-radius: 18px;

    padding: 26px;

    box-shadow:
        0 8px 30px
        rgba(0,0,0,0.12);
}

h1 {
    text-align: center;
}

.status {
    font-size: 24px;

    font-weight: bold;

    text-align: center;

    margin: 24px 0;
}

.info {
    font-size: 19px;

    line-height: 1.8;
}

.voice {
    margin-top: 22px;

    padding: 16px;

    background: #f9fafb;

    border-radius: 12px;

    min-height: 42px;
}

.voice-title {
    font-size: 18px;

    margin-bottom: 12px;
}

.buttons {
    display: flex;

    gap: 12px;

    margin-top: 24px;
}

button {
    flex: 1;

    border: none;

    padding: 17px 10px;

    font-size: 19px;

    border-radius: 12px;

    cursor: pointer;
}

.answer {
    background: #16a34a;

    color: white;
}

.reject {
    background: #dc2626;

    color: white;
}

.hangup {
    background: #374151;

    color: white;
}

.talk {
    background: #2563eb;

    color: white;
}

.talk-recording {
    background: #ea580c;

    color: white;
}

.play {
    width: 100%;

    background: #7c3aed;

    color: white;
}

.hint {
    margin-top: 12px;

    color: #4b5563;

    font-size: 15px;

    line-height: 1.6;
}

</style>
</head>

<body>

<div class="card">

<h1>家属端</h1>

<div
    id="status"
    class="status"
>
等待来电
</div>

<div
    id="info"
    class="info"
></div>

<div
    id="voice"
    class="voice"
></div>

<div
    id="buttons"
    class="buttons"
></div>

<div
    id="hint"
    class="hint"
></div>

</div>


<script>

let currentCallId = null;

let lastElderlyAudioId = 0;

let mediaRecorder = null;

let recordingStream = null;

let recordingChunks = [];


async function post(url) {

    await fetch(
        url,
        {
            method: "POST"
        }
    );

    await refresh();

}


function textStatus(status) {

    const mapping = {
        ringing:
            "来电中",

        answered:
            "通话中",

        rejected:
            "已拒绝",

        no_answer:
            "无人接听",

        completed:
            "通话结束"
    };

    return (
        mapping[status]
        || status
    );

}


function isRecording() {

    return (
        mediaRecorder
        &&
        mediaRecorder.state
        === "recording"
    );

}


function chooseMimeType() {

    const types = [
        "audio/webm;codecs=opus",
        "audio/webm",
        "audio/mp4"
    ];

    for (
        const type
        of types
    ) {
        if (
            window.MediaRecorder
            &&
            MediaRecorder
                .isTypeSupported(type)
        ) {
            return type;
        }
    }

    return "";
}


async function toggleRecording(
    callId
) {

    if (isRecording()) {

        mediaRecorder.stop();

        return;
    }

    if (
        !navigator.mediaDevices
        ||
        !navigator.mediaDevices
            .getUserMedia
    ) {
        alert(
            "当前浏览器不支持麦克风录音"
        );

        return;
    }

    if (
        !window.MediaRecorder
    ) {
        alert(
            "当前浏览器不支持 MediaRecorder"
        );

        return;
    }

    try {

        recordingStream =
            await navigator
                .mediaDevices
                .getUserMedia({
                    audio: true
                });

        recordingChunks = [];

        const mimeType =
            chooseMimeType();

        if (mimeType) {

            mediaRecorder =
                new MediaRecorder(
                    recordingStream,
                    {
                        mimeType:
                            mimeType
                    }
                );

        }

        else {

            mediaRecorder =
                new MediaRecorder(
                    recordingStream
                );

        }


        mediaRecorder
            .addEventListener(
                "dataavailable",
                event => {

                    if (
                        event.data
                        &&
                        event.data.size > 0
                    ) {
                        recordingChunks.push(
                            event.data
                        );
                    }

                }
            );


        mediaRecorder
            .addEventListener(
                "stop",
                async () => {

                    const actualType =
                        mediaRecorder.mimeType
                        ||
                        "audio/webm";

                    const blob =
                        new Blob(
                            recordingChunks,
                            {
                                type:
                                    actualType
                            }
                        );

                    document
                        .getElementById(
                            "voice"
                        )
                        .innerHTML =
                        "<div class='voice-title'>正在发送家属语音...</div>";

                    try {

                        const response =
                            await fetch(
                                "/api/calls/"
                                + callId
                                + "/audio/family",
                                {
                                    method:
                                        "POST",

                                    headers: {
                                        "Content-Type":
                                            actualType
                                    },

                                    body:
                                        blob
                                }
                            );

                        if (!response.ok) {

                            const text =
                                await response
                                    .text();

                            throw new Error(
                                text
                            );
                        }

                        document
                            .getElementById(
                                "voice"
                            )
                            .innerHTML =
                            "<div class='voice-title'>家属语音已发送，等待老人回复</div>";

                    }

                    catch (error) {

                        document
                            .getElementById(
                                "voice"
                            )
                            .innerHTML =
                            "<div class='voice-title'>发送失败：" +
                            error +
                            "</div>";

                    }

                    finally {

                        if (
                            recordingStream
                        ) {

                            recordingStream
                                .getTracks()
                                .forEach(
                                    track =>
                                        track.stop()
                                );

                        }

                        recordingStream = null;
                        mediaRecorder = null;
                        recordingChunks = [];

                        await refresh();

                    }

                }
            );


        mediaRecorder.start();

        await refresh();

    }

    catch (error) {

        alert(
            "无法使用手机麦克风："
            + error
        );

    }

}


async function playAudio(
    url
) {

    const audio =
        new Audio(url);

    try {

        await audio.play();

    }

    catch (error) {

        alert(
            "浏览器阻止自动播放，请再次点击播放按钮。"
        );

    }

}


function showElderlyAudio(
    message
) {

    const voice =
        document.getElementById(
            "voice"
        );

    voice.innerHTML =
        "<div class='voice-title'>收到老人语音</div>"
        +
        "<button class='play' "
        +
        "onclick=\"playAudio('"
        +
        message.audio_url
        +
        "')\">播放老人语音</button>";

    const audio =
        new Audio(
            message.audio_url
        );

    audio.play()
        .catch(
            () => {
                // 手机浏览器可能禁止自动播放。
                // 页面已经保留手动播放按钮。
            }
        );

}


async function pollElderlyAudio(
    call
) {

    if (
        call.status
        !== "answered"
    ) {
        return;
    }

    const response =
        await fetch(
            "/api/calls/"
            + call.id
            + "/audio"
            + "?after="
            + lastElderlyAudioId
            + "&sender=elderly"
        );

    if (!response.ok) {
        return;
    }

    const data =
        await response.json();

    for (
        const message
        of data.messages
    ) {

        lastElderlyAudioId =
            Math.max(
                lastElderlyAudioId,
                message.id
            );

        showElderlyAudio(
            message
        );

    }

}


async function refresh() {

    try {

        const response =
            await fetch(
                "/api/calls/latest",
                {
                    cache:
                        "no-store"
                }
            );

        const data =
            await response.json();

        const call =
            data.call;

        const status =
            document.getElementById(
                "status"
            );

        const info =
            document.getElementById(
                "info"
            );

        const buttons =
            document.getElementById(
                "buttons"
            );

        const voice =
            document.getElementById(
                "voice"
            );

        const hint =
            document.getElementById(
                "hint"
            );


        if (!call) {

            status.textContent =
                "等待来电";

            info.innerHTML = "";

            buttons.innerHTML = "";

            voice.innerHTML =
                "等待机器人发起通话";

            hint.innerHTML = "";

            return;
        }


        if (
            currentCallId
            !== call.id
        ) {

            currentCallId =
                call.id;

            lastElderlyAudioId = 0;

            voice.innerHTML = "";

        }


        status.textContent =
            textStatus(
                call.status
            );


        info.innerHTML =
            "<div>老人：" +
            call.elderly_name +
            "</div>" +

            "<div>联系人：" +
            call.relation +
            " / " +
            call.contact_name +
            "</div>" +

            "<div>号码：" +
            call.phone_masked +
            "</div>" +

            "<div>Call ID：" +
            call.id +
            "</div>";


        if (
            call.status ===
            "ringing"
        ) {

            buttons.innerHTML =
                '<button class="answer" ' +
                'onclick="post(\'/api/calls/' +
                call.id +
                '/answer\')">' +
                '接听' +
                '</button>' +

                '<button class="reject" ' +
                'onclick="post(\'/api/calls/' +
                call.id +
                '/reject\')">' +
                '拒绝' +
                '</button>';

            voice.innerHTML =
                "接听后即可进行真实语音交流";

            hint.innerHTML =
                "手机端需要允许浏览器使用麦克风。";

        }

        else if (
            call.status ===
            "answered"
        ) {

            const recordClass =
                isRecording()
                ? "talk-recording"
                : "talk";

            const recordText =
                isRecording()
                ? "停止并发送"
                : "开始说话";

            buttons.innerHTML =
                '<button class="' +
                recordClass +
                '" onclick="toggleRecording(\'' +
                call.id +
                '\')">' +
                recordText +
                '</button>' +

                '<button class="hangup" ' +
                'onclick="post(\'/api/calls/' +
                call.id +
                '/hangup\')">' +
                '挂断' +
                '</button>';

            hint.innerHTML =
                "操作方式：听到老人语音后，点击“开始说话”；说完后点击“停止并发送”。";

            await pollElderlyAudio(
                call
            );

        }

        else {

            buttons.innerHTML = "";

            hint.innerHTML = "";

            if (
                call.status ===
                "completed"
            ) {
                voice.innerHTML =
                    "本次通话已结束";
            }

        }

    }

    catch (error) {

        document
            .getElementById(
                "status"
            )
            .textContent =
                "无法连接服务器";

    }

}


refresh();

setInterval(
    refresh,
    700
);

</script>

</body>
</html>
"""


@app.get(
    "/family",
    response_class=HTMLResponse,
)
def family_page():
    return FAMILY_HTML


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8790,
        log_level="info",
    )
