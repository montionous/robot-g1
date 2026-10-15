#!/usr/bin/env python3

from __future__ import annotations

from activity_controller import (
    ActivityController,
)


def main():

    controller = (
        ActivityController(
            elder_id=1,
            elder_name="王大爷",
        )
    )


    print(
        "=" * 72
    )

    print(
        "SOCIAL_ACTIVITY_SUPPORT"
        " 社交活动协助"
    )

    print(
        "=" * 72
    )

    print(
        "示例：今天有什么活动 / "
        "下午有什么活动 / "
        "今天有没有唱歌活动 / "
        "第一个 / "
        "几点 / "
        "在哪里 / "
        "还有位置吗 / "
        "我要参加 / "
        "不想参加"
    )


    while controller.active:

        print()

        try:

            text = input(
                "老人> "
            ).strip()

        except (
            KeyboardInterrupt,
            EOFError,
        ):

            print()
            break


        if not text:
            continue


        result = (
            controller
            .handle_text(
                text
            )
        )


        print(
            "动作:",
            result[
                "action"
            ]
        )

        print(
            "机器人:",
            result[
                "reply"
            ]
        )


        selected = result.get(
            "selected"
        )

        if selected:

            print(
                "当前活动:",
                selected[
                    "name"
                ],
            )

            print(
                "场次ID:",
                selected[
                    "session_id"
                ],
            )


    print()

    print(
        "场景结束"
    )


if __name__ == "__main__":
    main()
