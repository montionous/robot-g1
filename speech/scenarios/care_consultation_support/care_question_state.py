"""Track answers to care information points, using this session's dialogue only.

Short replies are evidence only for the immediately preceding single question.
Unknown answers, acknowledgements and requests to repeat are never health facts.
"""
from __future__ import annotations

import re


LABELS = {
    "walking": "当前站立、行走与平时的比较",
    "baseline_comparison": "本次不适与平时的比较",
    "duration": "本次不适的持续时间",
    "onset": "本次不适是否刚出现及起始时间",
    "recent_course": "近期同类记录之后的持续、缓解或再次出现",
    "injury": "近期摔倒、扭伤或碰撞",
}
UNCLEAR = re.compile(r"没听[清见懂]|听不[清见懂]|再说一[遍次]|重复一[遍次]|什么意思|不明白")
UNKNOWN = re.compile(r"不知道|不清楚|说不[清准]|不确定|记不清|没注意|不好说|可能|也许")
SUPPORT = re.compile(r"担心|害怕|紧张|陪我|陪着我|和我聊|跟我聊")
QUESTION = re.compile(r"[？?]|吗|是不是|是否|有没有|多久|多长时间|稳不稳")
WALKING = re.compile(r"走路|行走|步行|走起来|走起路|走动|走得|站起来|站起身|站立|站得|站不稳|站着")
COMPARISON = re.compile(r"平时|平常|平日|以往|以前|之前|往常")
SHORT_ANSWER = re.compile(
    r"(?:嗯|呃|啊|哦|唔|是啊|是的)?[，, ]*"
    r"(?:还是|基本)?(?:差不多|一样|不一样|不太一样|还行|还好|正常|挺稳的|还稳|不稳|不太稳|不是很稳|稳当|"
    r"是|是的|不是|对|不对|有|没有|没摔|没有摔倒|没有扭伤|"
    r"明显一些|更明显|更疼|更酸|轻一些|好一些|重一些|"
    r"(?:和|跟|比)?(?:平时|平常|以前|原来)(?:差不多|一样|更明显|明显一些|要明显一些))"
    r"(?:一点|一些|吧|的|了|呢)?[。！!，, ]*"
)
DURATION = re.compile(r"(?:[一二两三四五六七八九十几半\d]+(?:个)?(?:小时|天|周|星期|月|年)|昨[天晚]|前天|刚刚|刚才|今天早上)")


def sentences(text):
    return [s.strip() for s in re.split(r"(?<=[。！？!?；;])|\n", str(text or "")) if s.strip()]


def question_topics(text):
    """Only classify questions; mentions in advice are not new questions."""
    topics = set()
    for sentence in sentences(text):
        if not QUESTION.search(sentence):
            continue
        if (re.search(r"上次|前几天|那次|近期记录|最近记录|提过类似|记录过类似", sentence)
                and re.search(r"一直|持续|缓解|又出现|到现在|变化", sentence)):
            topics.add("recent_course")
        elif re.search(r"最近才|刚刚出现|刚出现|刚开始|新出现|第一次|头一回|什么时候开始|何时开始|最近.{0,8}出现.{0,12}还是", sentence):
            topics.add("onset")
        # Duration is its own information point, even when it concerns walking.
        elif re.search(r"多久|多长时间|几天|什么时候|何时", sentence):
            topics.add("duration")
        elif WALKING.search(sentence) and re.search(r"稳|平时|平常|影响|困难|能否|能不能|怎么样|如何|费力|还好", sentence):
            topics.add("walking")
        elif re.search(r"摔|跌倒|扭伤|碰撞", sentence):
            topics.add("injury")
        elif COMPARISON.search(sentence) and re.search(r"比|一样|变化|差不多|明显", sentence):
            topics.add("baseline_comparison")
    return topics


def _explicit_topics(text):
    topics = set()
    for sentence in sentences(text):
        if UNKNOWN.search(sentence) or UNCLEAR.search(sentence) or re.search(r"[？?]|吗|是不是|是否|稳不稳", sentence):
            continue
        if WALKING.search(sentence) and re.search(r"稳|困难|费力|影响|不如|差不多|一样", sentence):
            topics.add("walking")
        if re.search(r"(?:昨天|今天|前天|昨晚|上周|这周|早上|下午|晚上).*(?:开始|出现|才疼|才酸)|(?:刚刚|刚才)(?:开始|出现)", sentence):
            topics.add("onset")
        if (re.search(r"上次|前几天|那次|之前|上回", sentence)
                and re.search(r"一直没缓解|一直没好|缓解后|好了.*又|好过.*又", sentence)):
            topics.add("recent_course")
        if (COMPARISON.search(sentence) and re.search(r"明显|更|一样|差不多|不如|加重|减轻", sentence)
                and not WALKING.search(sentence)):
            topics.add("baseline_comparison")
        if (DURATION.search(sentence) and re.search(r"持续|已经|天了|周了|月了|开始|出现", sentence)
                and not SUPPORT.search(sentence) and not re.search(r"摔|跌倒|扭伤|碰撞", sentence)):
            topics.add("duration")
        if re.search(r"(?:没|没有|未|摔了|跌倒了|扭了|扭伤了).*(?:摔|跌倒|扭|碰)|(?:摔倒|跌倒|扭伤|碰撞)(?:过|了)", sentence):
            topics.add("injury")
    return topics


def analyze_care_questions(history, user_text="", *, answer_decisions=None):
    turns = list(history or [])
    text = str(user_text or "").strip()
    if text and (not turns or turns[-1].get("role") != "user" or turns[-1].get("content") != text):
        turns.append({"role": "user", "content": text})
    confirmed = {}
    asked = set()
    previous_questions = set()
    repeat_requested = set()
    current_text = ""
    for index, turn in enumerate(turns):
        role = turn.get("role")
        value = str(turn.get("content") or "").strip()
        if role == "assistant":
            previous_questions = question_topics(value)
            asked.update(previous_questions)
        elif role == "user":
            current_text = value
            repeat_requested = set()
            explicit = set()
            if UNCLEAR.search(value):
                repeat_requested = previous_questions - confirmed.keys()
            elif not UNKNOWN.search(value):
                explicit = _explicit_topics(value)
                if len(previous_questions) == 1:
                    topic = next(iter(previous_questions))
                    if SHORT_ANSWER.fullmatch(value) or (topic == "duration" and DURATION.search(value)):
                        explicit.add(topic)
            decision = (answer_decisions or {}).get(index)
            if decision and decision.get("topic") in previous_questions and decision.get("confidence", 0) >= .80:
                topic = decision["topic"]
                if decision.get("status") == "answered":
                    evidence = decision.get("evidence", "")
                    if evidence.strip() and evidence in value:
                        explicit.add(topic)
                        repeat_requested.discard(topic)
                elif decision.get("status") in {"unclear", "not_answered", "repeat_requested"}:
                    explicit.discard(topic)
                    if decision["status"] == "repeat_requested" and topic not in confirmed:
                        repeat_requested.add(topic)
            for topic in explicit:
                confirmed[topic] = value
            # Never attach a later bare answer to a question interrupted by an
            # intervening user turn, or to a statement in the next robot reply.
            previous_questions = set()
    return {
        "confirmed": confirmed,
        "asked": sorted(asked),
        "repeat_requested": sorted(repeat_requested),
        "support_requested": bool(SUPPORT.search(current_text)),
    }


def blocked_topics(state):
    # Re-ask an unanswered item only when the elder explicitly asks to hear it.
    blocked = set(state["confirmed"]) | (set(state["asked"]) - set(state["repeat_requested"]))
    if state.get("recent_related_history"):
        blocked.add("onset")
        if {"onset", "duration"} & set(state["confirmed"]):
            blocked.add("recent_course")
    return blocked


def safe_follow_up(state):
    if state["support_requested"]:
        return "您先别着急，我在这里陪着您，您可以慢慢说。"
    recent = state.get("recent_related_history")
    if recent and "recent_course" not in blocked_topics(state):
        return (f"您在{recent['observation_date']}提过类似不适，"
                "这次是一直没缓解，还是缓解后又出现了？")
    return "您刚才说的情况我了解了，您还有想告诉我的，可以慢慢说。"


def apply_question_state(plan, state):
    plan["question_state"] = state
    preferred = plan.get("preferred_question")
    if state["support_requested"] or question_topics(preferred) & blocked_topics(state):
        plan["strategy"] = "supportive_follow_up" if state["support_requested"] else "answered_information_follow_up"
        plan["preferred_question"] = None
        plan["required_groups"] = []
        plan["must_use"] = []
        plan["fallback_reply"] = safe_follow_up(state)
    return plan


def question_state_prompt(state):
    lines = ["[CARE_QUESTION_STATE]", "已明确回答的信息不得重复追问；未听清不算已回答。"]
    for topic, answer in state["confirmed"].items():
        lines.append(f"- 已回答 {LABELS[topic]}：老人原话 {answer}")
    for topic in set(state["asked"]) - state["confirmed"].keys() - set(state["repeat_requested"]):
        lines.append(f"- {LABELS[topic]}已问但未获明确回答：先回应当前话题，不机械重复。")
    for topic in state["repeat_requested"]:
        lines.append(f"- 老人表示没听清：允许简短重述尚未回答的{LABELS[topic]}。")
    recent = state.get("recent_related_history")
    if recent:
        lines.append(f"- {recent['observation_date']}已有同类不适记录（最近{recent['window_days']}天内）。")
        lines.append("- 老人未主动说明本次为新发时，不再泛问是否最近才出现、是否第一次或何时开始。")
        lines.append("- 如病程仍需了解，应结合上述记录问此前之后一直未缓解还是缓解后又出现；该问题已答也不得再问。")
        lines.append("- 记录日期不等于症状持续时长，不得假定一直未缓解或把过去功能状态当成现在。")
        lines.append("- 老人已主动说明本次起始时间、持续时间或上次之后的病程时，不再追问这些已明确的信息。")
    if state["support_requested"]:
        lines.append("- 本轮老人需要安抚陪伴：先回应担心、陪伴需求，暂停护理追问；不保证健康无危险。")
    return "\n".join(lines)


def guard_care_questions(reply, state):
    """Apply after all generation and fallbacks so neither can reinsert a question."""
    blocked = blocked_topics(state)
    kept = [s for s in sentences(reply) if not question_topics(s) & blocked]
    return "".join(kept) or safe_follow_up(state)
