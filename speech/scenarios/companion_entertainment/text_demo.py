#!/usr/bin/env python3

from __future__ import annotations

from entertainment_controller import (
    EntertainmentController,
)


def show_result(result):

    print()
    print(
        "动作:",
        result[
            "action"
        ],
    )

    print(
        "机器人:",
        result[
            "reply"
        ],
    )

    print(
        "当前类别:",
        result[
            "category"
        ],
    )

    item = result.get(
        "play_item"
    )

    if item:

        print(
            "将播放:",
            item["title"],
        )

        print(
            "文件:",
            item["path"],
        )

    print(
        "先停止当前播放:",
        result[
            "stop_playback"
        ],
    )


def main():

    controller = (
        EntertainmentController()
    )

    print(
        "=" * 70
    )

    print(
        "COMPANION_ENTERTAINMENT"
        " 文字控制测试"
    )

    print(
        "=" * 70
    )

    print(
        "可输入："
        "有点无聊 / "
        "放点音乐 / "
        "我想听甜蜜蜜 / "
        "换一个 / "
        "换成戏曲 / "
        "我想听贵妃醉酒 / "
        "听新闻 / "
        "不听了"
    )

    while controller.active:

        print()

        try:
            text = input(
                "老人> "
            ).strip()

        except (
            EOFError,
            KeyboardInterrupt,
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

        show_result(
            result
        )

    print()
    print(
        "场景结束"
    )


if __name__ == "__main__":
    main()
