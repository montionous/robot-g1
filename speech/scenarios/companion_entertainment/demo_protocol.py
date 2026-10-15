from __future__ import annotations


# ============================================================
# States
# ============================================================

WAIT_MUSIC_REQUEST = "wait_music_request"

PLAYING_MUSIC_FIRST = "playing_music_first"

PLAYING_MUSIC_SECOND = "playing_music_second"

PLAYING_NEWS = "playing_news"

PLAYING_OPERA = "playing_opera"

DONE = "done"


# ============================================================
# Intents
# ============================================================

PLAY_MUSIC = "play_music"

NEXT_MUSIC = "next_music"

SWITCH_NEWS = "switch_news"

SWITCH_OPERA = "switch_opera"

# 指定了某个具体内容、作品、人物或更细媒体类型。
# 比赛固定流程中识别得到，但不允许执行。
SPECIFIC_MEDIA_REQUEST = "specific_media_request"

END = "end"

OTHER = "other"


# ============================================================
# State gate
#
# 这里是比赛版最重要的约束。
# 即使 ASR / LLM 正确识别出了别的控制意图，
# 只要当前状态不允许，也绝不能执行。
# ============================================================

ALLOWED_BY_STATE = {
    WAIT_MUSIC_REQUEST: {
        PLAY_MUSIC,
        END,
    },

    PLAYING_MUSIC_FIRST: {
        NEXT_MUSIC,
        END,
    },

    PLAYING_MUSIC_SECOND: {
        SWITCH_NEWS,
        END,
    },

    PLAYING_NEWS: {
        SWITCH_OPERA,
        END,
    },

    PLAYING_OPERA: {
        END,
    },

    DONE: set(),
}


PLAYING_STATES = {
    PLAYING_MUSIC_FIRST,
    PLAYING_MUSIC_SECOND,
    PLAYING_NEWS,
    PLAYING_OPERA,
}


# ============================================================
# Dialect
#
# 老人交互：陕西方言
# 系统决策播报：普通话
# ============================================================

INTERACTION_DIALECT = "shaanxi"

ANNOUNCER_DIALECT = "mandarin"


# ============================================================
# Spoken scripts
#
# 目前先使用较轻的陕西口语风格，
# 最终比赛前应让陕西本地人试听并校对。
# TTS 同时使用 dialect="shaanxi"。
# ============================================================

OPENING = (
    "您好，想听点啥？"
    "您跟我说一声，我给您放。"
)


PLAY_MUSIC_REPLY = (
    "好嘞，给您放点音乐，"
    "咱慢慢听。"
)


NEXT_MUSIC_REPLY = (
    "好嘞，给您换一首，"
    "咱接着听。"
)


SWITCH_NEWS_REPLY = (
    "成，咱换成新闻，"
    "听听有啥新消息。"
)


SWITCH_OPERA_REPLY = (
    "好嘞，咱换段戏听听。"
)


END_REPLY = (
    "好嘞，那咱今儿就先听到这儿。"
    "您啥时候想听了，再叫我就成。"
)


TIMEOUT_REPLY = (
    "那我先不打扰您了。"
    "您想听的时候，再叫我就成。"
)


# ============================================================
# Decision announcer messages
#
# decision_announcer 自己负责“检测到……”形式，
# 所以这里不要再手动加“检测到”。
# ============================================================

DECISION_MESSAGES = {
    PLAY_MUSIC:
        "您希望播放音乐。",

    NEXT_MUSIC:
        "您希望切换到下一首音乐。",

    SWITCH_NEWS:
        "您希望从音乐切换到新闻。",

    SWITCH_OPERA:
        "您希望从新闻切换到戏曲。",

    END:
        "您希望结束当前娱乐播放。",
}


INTERACTION_REPLIES = {
    PLAY_MUSIC:
        PLAY_MUSIC_REPLY,

    NEXT_MUSIC:
        NEXT_MUSIC_REPLY,

    SWITCH_NEWS:
        SWITCH_NEWS_REPLY,

    SWITCH_OPERA:
        SWITCH_OPERA_REPLY,

    END:
        END_REPLY,
}
