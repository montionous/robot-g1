from __future__ import annotations


STYLE_PRESETS = {
    "normal": {
        "speed": 1.0,
        "pitch": 1.0,
        "volume": 75,
        "emotion": "neutral",
    },

    "companion": {
        "speed": 0.90,
        "pitch": 1.0,
        "volume": 75,
        "emotion": "warm",
    },

    "comfort": {
        "speed": 0.82,
        "pitch": 0.96,
        "volume": 72,
        "emotion": "gentle",
    },

    "emergency": {
        "speed": 0.90,
        "pitch": 0.96,
        "volume": 82,
        "emotion": "calm",
    },

    "happy": {
        "speed": 1.05,
        "pitch": 1.02,
        "volume": 78,
        "emotion": "cheerful",
    },
}


DIALECT_INSTRUCTIONS = {
    "mandarin": "",
    "putonghua": "",

    "sichuan":
        "请用四川话表达。",

    "chongqing":
        "请用重庆话表达。",

    "henan":
        "请用河南话表达。",

    "cantonese":
        "请用广东话表达。",

    "shanghai":
        "请用上海话表达。",

    "shandong":
        "请用山东话表达。",

    "shaanxi":
        "请用陕西话表达，语言自然、亲切，使用老人容易听懂的陕西方言。",

    "northeast":
        "请用东北话表达。",
}


EMOTION_INSTRUCTIONS = {
    "neutral":
        "请使用自然、平静、尊重老人的语气。",

    "warm":
        "请使用温暖、亲切、自然的陪伴语气。",

    "gentle":
        "请使用温柔、耐心、安抚性的语气，不要夸张。",

    "calm":
        "请使用沉稳、冷静、清晰、让人安心的语气。",

    "cheerful":
        "请使用轻快、积极但不过分夸张的语气。",
}


def delivery_instruction(
    *,
    speed: float,
    pitch: float,
    volume: int,
) -> str:
    """Optional Qwen3-TTS instruct text. CosyVoice uses numeric rate/pitch/volume instead."""
    parts: list[str] = []
    if speed >= 1.03:
        parts.append("语速稍快。")
    elif speed <= 0.76:
        parts.append("语速明显放慢，一句一句说清楚。")
    elif speed <= 0.88:
        parts.append("语速放慢，不要赶。")
    if pitch >= 1.015:
        parts.append("音调略高，听起来轻快一些。")
    elif pitch <= 0.97:
        parts.append("音调略低，听起来沉稳、柔和一些。")
    if volume <= 66:
        parts.append("音量稍轻，不要大声。")
    elif volume >= 80:
        parts.append("声音清晰、稍饱满。")
    return "".join(parts)


def build_instruction(
    *,
    dialect: str = "mandarin",
    emotion: str = "neutral",
) -> str:

    dialect = dialect.strip().lower()
    emotion = emotion.strip().lower()

    if dialect not in DIALECT_INSTRUCTIONS:
        raise ValueError(
            f"不支持的方言: {dialect}"
        )

    if emotion not in EMOTION_INSTRUCTIONS:
        raise ValueError(
            f"不支持的语气: {emotion}"
        )

    return (
        DIALECT_INSTRUCTIONS[dialect]
        +
        EMOTION_INSTRUCTIONS[emotion]
    )
