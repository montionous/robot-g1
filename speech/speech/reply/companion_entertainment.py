from __future__ import annotations


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

        当前仅预留接口，
        后续接共享需求数据库。
    后续可接：
        - 老人偏好
        - 历史点播
        - LLM生成候选话术
    """

    original = result.get(
        "reply"
    )

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
