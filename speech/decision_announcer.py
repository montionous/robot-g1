from __future__ import annotations

import time
from companion_recording import record_speech_request, record_speech_receipt


def announce_decision(
    speech,
    text,
    *,
    enabled=False,
    dialect="mandarin",
):
    """
    播报机器人刚刚完成的关键业务判断。

    用于向用户明确反馈系统当前识别到的
    意图、对象、状态或风险等级。

    text 不需要包含“检测到”，
    本函数会统一添加。
    """

    if not enabled:
        return

    text = str(text or "").strip()

    if not text:
        return

    message = f"检测到{text}"

    print(
        "判断播报:",
        message,
    )

    record_speech_request('decision_announcer', message, source='announce_decision')
    try:
        result=speech.speak_g1(message,style='companion',dialect=dialect)
    except BaseException as error:
        record_speech_receipt('decision_announcer',message,source='announce_decision',error=error)
        raise
    record_speech_receipt('decision_announcer',message,source='announce_decision',result=result)

    time.sleep(0.3)
