from __future__ import annotations


def append_led_notice(reply, category, *, enabled):
    """Only describe LED changes when physical LED execution is enabled."""
    if not enabled or not reply:
        return reply
    notices = {
        "music": "我给您把灯光也调一下，听歌更有气氛。",
        "news": "我给您把灯光也调一下，咱专心听新闻。",
        "opera": "我给您把灯光也调一下，听戏更有味道。",
    }
    notice = notices.get(category)
    return f"{reply} {notice}" if notice else reply


def generate_reply(
    command: dict,
    result: dict,
    *,
    dialect: str = "shaanxi",
    elderly_context: dict | None = None,
):
    """
    娱乐场景统一回复生成。

    输入：
        command:
            用户动作意图

        result:
            娱乐控制结果

    输出：
        str | None

    当前版本：
        模板规则生成。

    elderly_context:
        可选老人上下文，例如：
        {
            "preferred_music": "甜蜜蜜",
            "preferred_opera": "贵妃醉酒",
        }

        当前预留附加上下文接口。
        历史选曲依据由 controller 的 selection_reason 传入，
        回复层不重新查询共享数据库。
    """

    original = result.get(
        "reply"
    )

    play_item = result.get("play_item") or {}
    title = play_item.get("title")
    category = command.get("category") or result.get("category")
    if (
        result.get("action") == "play"
        and command.get("action") == "play_category"
        and category in {"music", "opera"}
        and result.get("selection_reason") == "history"
        and title
    ):
        if dialect == "shaanxi":
            return f"好嘞，点播偏好里有《{title}》，今儿咱就先听这首。"
        return f"好的，按点播偏好为您优先播放《{title}》。"

    if dialect != "shaanxi":
        return original


    command_action = command.get(
        "action"
    )

    result_action = result.get(
        "action"
    )


    category = (
        command.get("category")
        or result.get("category")
    )


    play_item = result.get(
        "play_item"
    )

    title = None

    if play_item:
        title = play_item.get(
            "title"
        )


    if result_action == "ask_category":

        return (
            "想听点啥？"
            "音乐、新闻、戏曲都行，"
            "您跟我说一声。"
        )


    if result_action == "play":

        if category == "music":

            if command_action == "next":

                return (
                    "好嘞，给您换一首，"
                    "咱接着听。"
                )


            if (
                command_action == "play_query"
                and title
            ):

                return (
                    f"成，给您找着了，"
                    f"咱就听{title}。"
                )


            return (
                "好嘞，给您放点音乐，"
                "咱慢慢听。"
            )


        if category == "news":

            return (
                "成，咱听听新闻，"
                "看看有啥新消息。"
            )


        if category == "opera":

            if (
                command_action == "play_query"
                and title
            ):

                return (
                    f"好嘞，给您找着了，"
                    f"咱听听{title}。"
                )


            return (
                "好嘞，咱听段戏。"
            )


    if result_action == "not_found":

        return (
            "这个我这儿暂时没有，"
            "咱换个别的听。"
        )


    if result_action == "empty":

        return (
            "这个我这儿暂时没准备好，"
            "咱换个别的听。"
        )


    if result_action == "continue":

        return None


    if result_action == "stop":

        return (
            "好嘞，那咱今儿就先听到这儿。"
            "您啥时候想听了，再叫我就成。"
        )


    return original
