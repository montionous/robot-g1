from __future__ import annotations

import argparse

from contact_family_logic import (
    ContactFamilySession,
)

from db_access import (
    create_call_log,
    get_elderly,
)


def print_stage(
    icon,
    name,
    value,
):
    print(
        f"{icon} {name}: {value}"
    )


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--elderly-id",
        type=int,
        default=1,
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

    elderly = get_elderly(
        args.elderly_id
    )

    if elderly is None:
        raise RuntimeError(
            "老人不存在"
        )

    print()
    print("=" * 65)
    print(
        "  CONTACT_FAMILY · 初赛场景测试"
    )
    print("=" * 65)

    print_stage(
        "👴",
        "当前老人",
        elderly["name"],
    )

    print()
    print_stage(
        "🗣",
        "老人",
        args.utterance,
    )

    session = ContactFamilySession(
        args.elderly_id
    )

    result = session.handle_request(
        args.utterance
    )

    print_stage(
        "🧠",
        "意图",
        result.get(
            "intent"
        ),
    )

    print_stage(
        "📌",
        "状态",
        result["state"],
    )

    if (
        result["state"]
        == "CONTACT_NOT_FOUND"
    ):

        print_stage(
            "🤖",
            "机器人",
            result["reply"],
        )

        return

    if (
        result["state"]
        != "AWAITING_CONFIRMATION"
    ):

        print_stage(
            "⚠️",
            "结果",
            result.get(
                "message"
            ),
        )

        return

    print()
    print_stage(
        "🔍",
        "数据库",
        "已找到授权联系人",
    )

    print_stage(
        "👤",
        "联系人",
        (
            f"{result['relation']} / "
            f"{result['contact_name']}"
        ),
    )

    print_stage(
        "📞",
        "电话",
        result["phone_masked"],
    )

    print_stage(
        "🔐",
        "授权",
        (
            "通过"
            if result["authorized"]
            else "未授权"
        ),
    )

    print()
    print_stage(
        "🤖",
        "机器人",
        result["reply"],
    )

    print()
    print_stage(
        "👴",
        "老人",
        args.confirmation,
    )

    confirm = (
        session
        .handle_confirmation(
            args.confirmation
        )
    )

    print_stage(
        "📌",
        "确认状态",
        confirm["state"],
    )

    print_stage(
        "🤖",
        "机器人",
        confirm.get(
            "reply"
        ),
    )

    # -----------------------------------------------------
    # 老人没有确认
    # -----------------------------------------------------

    if (
        confirm.get(
            "confirmed"
        )
        is not True
    ):

        create_call_log(
            elderly_id=
                args.elderly_id,

            contact_id=
                (
                    session.contact["id"]
                    if session.contact
                    else None
                ),

            recognized_text=
                args.utterance,

            requested_relation=
                (
                    session.contact[
                        "relation"
                    ]
                    if session.contact
                    else None
                ),

            confirmed=False,

            call_status=
                "cancelled",
        )

        return

    # -----------------------------------------------------
    # 模拟真实电话模块
    # -----------------------------------------------------

    print()
    print("=" * 65)
    print(
        "  CALL SERVICE"
    )
    print("=" * 65)

    print_stage(
        "☎️",
        "拨号目标",
        (
            f"{confirm['relation']} / "
            f"{confirm['contact_name']}"
        ),
    )

    print_stage(
        "☎️",
        "状态",
        "正在呼叫",
    )

    print_stage(
        "✅",
        "状态",
        "已接通（初赛模拟）",
    )

    log_id = create_call_log(
        elderly_id=
            args.elderly_id,

        contact_id=
            confirm["contact_id"],

        recognized_text=
            args.utterance,

        requested_relation=
            confirm["relation"],

        confirmed=True,

        call_status=
            "connected_demo",
    )

    print()
    print_stage(
        "💾",
        "数据库",
        f"服务记录 #{log_id}",
    )

    print()

    print(
        "CONTACT_FAMILY"
        " → 联系人匹配"
        " → 授权校验"
        " → 二次确认"
        " → 呼叫"
        " → 服务记录"
    )


if __name__ == "__main__":
    main()
