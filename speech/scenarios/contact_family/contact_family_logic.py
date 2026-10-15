from __future__ import annotations

from db_access import find_family_contact


CONTACT_INTENT_WORDS = [
    "打电话",
    "打个电话",
    "通电话",
    "通话",
    "联系",
    "说说话",
    "说会儿话",
    "聊聊天",
    "聊聊",
]


YES_WORDS = [
    "对",
    "对的",
    "是",
    "是的",
    "嗯",
    "嗯嗯",
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
    "先不用",
]


def normalize_text(text: str) -> str:
    return (
        str(text)
        .strip()
        .replace(" ", "")
    )


def normalize_dial_authorization(
    text: str,
) -> str:
    """
    真实外部拨号使用更严格的确认规则。

    只移除：
    - 空白
    - 常见中英文标点

    不做语义扩展。
    """

    value = str(
        text or ""
    ).strip()

    for char in (
        " ",
        "\t",
        "\n",
        "，",
        ",",
        "。",
        ".",
        "！",
        "!",
        "？",
        "?",
        "：",
        ":",
        "；",
        ";",
        "、",
        "“",
        "”",
        '"',
        "'",
    ):
        value = value.replace(
            char,
            "",
        )

    return value


def classify_dial_authorization(
    text: str,
):
    """
    返回：

    True
        只有精确“确认拨号”

    False
        明确取消

    None
        其他任何表达都不能授权
    """

    value = (
        normalize_dial_authorization(
            text
        )
    )

    if value == "确认拨号":
        return True

    if value in {
        "取消",
        "取消拨号",
        "不拨打",
        "不打了",
        "算了",
        "不用了",
    }:
        return False

    return None



def has_contact_intent(text: str) -> bool:
    text = normalize_text(text)

    return any(
        word in text
        for word in CONTACT_INTENT_WORDS
    )


def classify_confirmation(text: str):
    text = normalize_text(text)

    # 必须先判断否定
    for word in NO_WORDS:
        if word in text:
            return False

    for word in YES_WORDS:
        if word in text:
            return True

    return None


def mask_phone(phone: str) -> str:
    phone = str(phone)

    if len(phone) >= 7:
        return (
            phone[:3]
            + "****"
            + phone[-4:]
        )

    return "已保存"


class ContactFamilySession:
    """
    CONTACT_FAMILY 单次会话状态机。

    不负责：
    - ASR
    - TTS
    - 真正拨号

    只负责：
    - 联系意图
    - 数据库联系人匹配
    - 二次确认
    - 会话状态
    """

    def __init__(
        self,
        elderly_id: int,
    ):
        self.elderly_id = elderly_id

        self.state = "IDLE"

        self.original_text = None

        self.contact = None

    def begin_dial_authorization(
        self,
    ) -> dict:
        """
        第一级联系人确认完成后，
        进入真实拨号最终授权阶段。
        """

        if self.state != "CONFIRMED":
            return {
                "ok": False,
                "state": self.state,
                "message":
                    "当前不能进入拨号授权阶段",
            }

        if self.contact is None:
            return {
                "ok": False,
                "state": self.state,
                "message":
                    "当前没有已确认联系人",
            }

        self.state = (
            "AWAITING_DIAL_AUTHORIZATION"
        )

        return {
            "ok": True,
            "state": self.state,

            "contact_id":
                self.contact["id"],

            "contact_name":
                self.contact["name"],

            "relation":
                self.contact["relation"],

            "reply": (
                "好的，联系人已经确认。"
                "拨号前还需要您最后确认。"
                "如果确定拨打，请说确认拨号；"
                "不拨打请说取消。"
            ),
        }


    def handle_dial_authorization(
        self,
        text: str,
    ) -> dict:
        """
        对真实外部拨号进行最终授权。

        “好的 / 是的 / 可以 / 确认”
        均不能产生拨号权限。
        """

        if (
            self.state
            != "AWAITING_DIAL_AUTHORIZATION"
        ):
            return {
                "ok": False,
                "state": self.state,
                "authorized": False,
                "message":
                    "当前不处于拨号授权阶段",
            }

        decision = (
            classify_dial_authorization(
                text
            )
        )

        if decision is True:

            self.state = (
                "DIAL_AUTHORIZED"
            )

            return {
                "ok": True,
                "state": self.state,
                "authorized": True,

                "contact_id":
                    self.contact["id"],

                "contact_name":
                    self.contact["name"],

                "relation":
                    self.contact["relation"],

                "reply":
                    "好的，拨号确认通过。",
            }

        if decision is False:

            self.state = (
                "CANCELLED"
            )

            return {
                "ok": True,
                "state": self.state,
                "authorized": False,
                "reply":
                    "好的，那我不拨打电话。",
            }

        return {
            "ok": False,

            "state":
                "AWAITING_DIAL_AUTHORIZATION",

            "authorized":
                None,

            "reply": (
                "我还没有收到拨号确认。"
                "如果确定拨打，请完整说确认拨号；"
                "不拨打请说取消。"
            ),
        }



    def handle_request(
        self,
        text: str,
    ) -> dict:

        self.original_text = text

        # -------------------------------------------------
        # 1. CONTACT_FAMILY 意图判断
        # -------------------------------------------------

        if not has_contact_intent(text):

            self.state = (
                "NOT_CONTACT_FAMILY"
            )

            return {
                "ok": False,
                "state": self.state,
                "intent": None,
                "message":
                    "未识别到联系家人的明确需求",
            }

        # -------------------------------------------------
        # 2. 查询授权联系人
        # -------------------------------------------------

        contact = find_family_contact(
            self.elderly_id,
            text,
        )

        if contact is None:

            self.state = (
                "CONTACT_NOT_FOUND"
            )

            return {
                "ok": False,
                "state": self.state,
                "intent":
                    "CONTACT_FAMILY",
                "message":
                    "没有找到匹配的授权联系人",
                "reply":
                    "好的，请问您想联系哪位家人？",
            }

        self.contact = contact

        self.state = (
            "AWAITING_CONFIRMATION"
        )

        relation = contact["relation"]
        name = contact["name"]

        return {
            "ok": True,

            "state": self.state,

            "intent":
                "CONTACT_FAMILY",

            "contact_id":
                contact["id"],

            "contact_name":
                name,

            "relation":
                relation,

            "phone_masked":
                mask_phone(
                    contact["phone"]
                ),

            "authorized":
                bool(
                    contact["authorized"]
                ),

            "reply":
                (
                    f"好的，您是想联系您的"
                    f"{relation}{name}吗？"
                ),
        }

    def handle_confirmation(
        self,
        text: str,
    ) -> dict:

        if (
            self.state
            != "AWAITING_CONFIRMATION"
        ):

            return {
                "ok": False,
                "state": self.state,
                "message":
                    "当前不处于联系人确认阶段",
            }

        result = classify_confirmation(
            text
        )

        # -------------------------------------------------
        # 没听明白
        # -------------------------------------------------

        if result is None:

            return {
                "ok": False,

                "state":
                    "AWAITING_CONFIRMATION",

                "confirmed":
                    None,

                "reply":
                    "抱歉，我没有听清。"
                    "您是要联系这位家人吗？",
            }

        # -------------------------------------------------
        # 老人拒绝
        # -------------------------------------------------

        if result is False:

            self.state = "CANCELLED"

            return {
                "ok": True,

                "state":
                    self.state,

                "confirmed":
                    False,

                "reply":
                    "好的，那我先不联系。",
            }

        # -------------------------------------------------
        # 老人明确确认
        # -------------------------------------------------

        self.state = "CONFIRMED"

        return {
            "ok": True,

            "state":
                self.state,

            "confirmed":
                True,

            "contact_id":
                self.contact["id"],

            "contact_name":
                self.contact["name"],

            "relation":
                self.contact["relation"],

            # 注意：
            # phone 只给确定性的通话模块使用。
            # 不需要交给大模型。
            "phone":
                self.contact["phone"],

            "reply":
                (
                    f"好的，正在为您联系"
                    f"{self.contact['relation']}。"
                ),
        }
