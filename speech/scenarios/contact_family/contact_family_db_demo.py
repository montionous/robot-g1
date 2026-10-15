from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


SCENE_DIR = (
    Path(__file__).resolve()
    .parent
)

PROJECT_ROOT = (
    SCENE_DIR.parents[1]
)

sys.path.insert(
    0,
    str(PROJECT_ROOT)
)


from speech_client import SpeechClient

from db_access import (
    create_call_log,
    find_family_contact,
    get_elderly,
)


# =========================================================
# 基础配置
# =========================================================

DEFAULT_ELDERLY_ID = 1

SPEECH_SERVER = (
    "http://127.0.0.1:8780"
)


# =========================================================
# 显示
# =========================================================

def banner(
    text,
):

    print()
    print("=" * 68)

    print(
        f"  {text}"
    )

    print("=" * 68)


def stage(
    icon,
    title,
    value="",
):

    if value:

        print(
            f"{icon} {title}: {value}"
        )

    else:

        print(
            f"{icon} {title}"
        )


# =========================================================
# 意图识别
# =========================================================

CONTACT_WORDS = [
    "打电话",
    "通电话",
    "通话",
    "联系",
    "说说话",
    "聊聊",
    "聊天",
]


def has_contact_intent(
    text,
):

    text = (
        text
        .replace(" ", "")
    )

    return any(
        word in text
        for word in CONTACT_WORDS
    )


# =========================================================
# 二次确认
# =========================================================

YES_WORDS = [
    "对",
    "对的",
    "是",
    "是的",
    "嗯",
    "好",
    "好的",
    "可以",
    "没错",
    "就是",
]


NO_WORDS = [
    "不是",
    "不对",
    "不要",
    "不用",
    "算了",
]


def classify_confirmation(
    text,
):

    text = (
        text
        .replace(" ", "")
    )

    # 必须先判断否定
    for word in NO_WORDS:

        if word in text:
            return False

    for word in YES_WORDS:

        if word in text:
            return True

    return None


# =========================================================
# 电话号码脱敏
# =========================================================

def mask_phone(
    phone,
):

    phone = str(phone)

    if len(phone) >= 7:

        return (
            phone[:3]
            + "****"
            + phone[-4:]
        )

    return "已保存"


# =========================================================
# TTS
# =========================================================

def say(
    speech,
    text,
    *,
    style="companion",
):

    stage(
        "🤖",
        "机器人",
        text,
    )

    return speech.speak(
        text,
        style=style,
        dialect="mandarin",
        play_on_host=True,
    )


# =========================================================
# 模拟拨号
# =========================================================

def perform_demo_call(
    speech,
    contact,
):

    say(
        speech,
        (
            f"好的，正在为您联系"
            f"{contact['relation']}。"
        ),
    )

    banner(
        "CONTACT FAMILY · CALL"
    )

    stage(
        "👤",
        "联系人",
        (
            f"{contact['relation']} "
            f"{contact['name']}"
        ),
    )

    stage(
        "📞",
        "号码",
        mask_phone(
            contact["phone"]
        ),
    )

    stage(
        "☎️",
        "状态",
        "正在呼叫……",
    )

    # 初赛展示：
    # 后面这里替换成真实电话接口。
    for i in range(
        3,
        0,
        -1,
    ):

        print(
            f"   呼叫中 {i} ..."
        )

        time.sleep(
            0.7
        )

    stage(
        "✅",
        "状态",
        "通话已接通（演示模式）",
    )

    return "connected_demo"


# =========================================================
# 主场景
# =========================================================

def run_scene(
    *,
    elderly_id,
    utterance,
    confirmation,
):

    banner(
        "老年陪伴机器人 · CONTACT_FAMILY"
    )

    speech = SpeechClient(
        SPEECH_SERVER
    )

    # -----------------------------------------------------
    # 当前老人
    # -----------------------------------------------------

    elderly = get_elderly(
        elderly_id
    )

    if elderly is None:

        raise RuntimeError(
            f"找不到老人 elderly_id={elderly_id}"
        )

    stage(
        "👴",
        "当前老人",
        (
            f"{elderly['name']} "
            f"(ID={elderly['id']})"
        ),
    )

    # -----------------------------------------------------
    # 老人表达需求
    # -----------------------------------------------------

    stage(
        "📝",
        "语音识别结果",
        utterance,
    )

    # -----------------------------------------------------
    # CONTACT_FAMILY
    # -----------------------------------------------------

    if not has_contact_intent(
        utterance
    ):

        stage(
            "❌",
            "意图识别",
            "未识别为 CONTACT_FAMILY",
        )

        return

    stage(
        "✅",
        "意图识别",
        "CONTACT_FAMILY",
    )

    # -----------------------------------------------------
    # 查询数据库
    # -----------------------------------------------------

    stage(
        "🔍",
        "数据库查询",
        "正在查询授权家属联系人",
    )

    contact = find_family_contact(
        elderly_id,
        utterance,
    )

    if contact is None:

        stage(
            "❌",
            "联系人查询",
            "没有找到匹配的授权联系人",
        )

        say(
            speech,
            "抱歉，我没有找到对应的授权联系人。",
        )

        create_call_log(
            elderly_id=elderly_id,

            contact_id=None,

            recognized_text=utterance,

            requested_relation=None,

            confirmed=False,

            call_status=(
                "contact_not_found"
            ),
        )

        return

    stage(
        "✅",
        "授权联系人",
        (
            f"{contact['relation']} / "
            f"{contact['name']}"
        ),
    )

    stage(
        "🔐",
        "授权状态",
        "已授权",
    )

    stage(
        "📞",
        "联系电话",
        mask_phone(
            contact["phone"]
        ),
    )

    # -----------------------------------------------------
    # 二次确认
    # -----------------------------------------------------

    say(
        speech,
        (
            f"好的，您是想联系您的"
            f"{contact['relation']}"
            f"{contact['name']}吗？"
        ),
    )

    stage(
        "👴",
        "老人确认",
        confirmation,
    )

    confirmed = (
        classify_confirmation(
            confirmation
        )
    )

    if confirmed is not True:

        stage(
            "🛑",
            "确认结果",
            "未通过",
        )

        say(
            speech,
            "好的，那我先不联系。",
        )

        create_call_log(
            elderly_id=elderly_id,

            contact_id=contact["id"],

            recognized_text=utterance,

            requested_relation=(
                contact["relation"]
            ),

            confirmed=False,

            call_status="cancelled",
        )

        return

    stage(
        "✅",
        "确认结果",
        "老人已明确确认",
    )

    # -----------------------------------------------------
    # 呼叫
    # -----------------------------------------------------

    call_status = (
        perform_demo_call(
            speech,
            contact,
        )
    )

    # -----------------------------------------------------
    # 记录日志
    # -----------------------------------------------------

    log_id = create_call_log(
        elderly_id=elderly_id,

        contact_id=contact["id"],

        recognized_text=utterance,

        requested_relation=(
            contact["relation"]
        ),

        confirmed=True,

        call_status=call_status,
    )

    stage(
        "📝",
        "服务记录",
        (
            f"已写入数据库 "
            f"log_id={log_id}"
        ),
    )

    banner(
        "场景完成"
    )

    print(
        "CONTACT_FAMILY"
        " → 数据库查询"
        " → 授权校验"
        " → 二次确认"
        " → 呼叫"
        " → 日志记录"
    )


# =========================================================
# main
# =========================================================

def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--elderly-id",
        type=int,
        default=DEFAULT_ELDERLY_ID,
    )

    parser.add_argument(
        "--utterance",
        default=(
            "我想和女儿说说话"
        ),
    )

    parser.add_argument(
        "--confirmation",
        default="对",
    )

    args = parser.parse_args()

    run_scene(
        elderly_id=args.elderly_id,
        utterance=args.utterance,
        confirmation=args.confirmation,
    )


if __name__ == "__main__":
    main()
