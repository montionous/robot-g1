from __future__ import annotations

from elder_need_registry import (
    create_need,
    get_need,
    update_need,
)


SOURCE_SCENE = (
    "CARE_CONSULTATION_SUPPORT"
)


CARE_NEED_INFO = {
    "mobility": {
        "need_code":
            "care_mobility",

        "summary":
            "肢体活动与肌肉关节不适护理咨询",
    },

    "dizziness": {
        "need_code":
            "care_dizziness",

        "summary":
            "头晕与一般状态护理咨询",
    },

    "sleep": {
        "need_code":
            "care_sleep",

        "summary":
            "睡眠护理咨询",
    },

    "appetite": {
        "need_code":
            "care_appetite",

        "summary":
            "饮食与食欲护理咨询",
    },

    "bowel": {
        "need_code":
            "care_bowel",

        "summary":
            "排便与生活护理咨询",
    },

    "fatigue": {
        "need_code":
            "care_fatigue",

        "summary":
            "疲劳与一般状态护理咨询",
    },

    "general_care": {
        "need_code":
            "care_general",

        "summary":
            "一般日常护理咨询",
    },
}


class CareNeedBridge:

    def __init__(
        self,
        *,
        elderly_id,
        session_id,
        dry_run=False,
    ):

        self.elderly_id = (
            int(elderly_id)
        )

        self.session_id = (
            session_id
        )

        self.dry_run = bool(
            dry_run
        )

        self.need_id = None
        self._initial_care_domain = None
        self._initial_risk_level = None


    def _need_info(
        self,
        care_domain,
    ):

        return (
            CARE_NEED_INFO.get(
                care_domain,
                CARE_NEED_INFO[
                    "general_care"
                ],
            )
        )


    @staticmethod
    def _priority(
        risk_level,
    ):

        if risk_level == "needs_staff":
            return "high"

        return "normal"


    def sync(
        self,
        *,
        care_domain,
        risk_level,
        raw_text,
        round_no,
        staff_follow_up_created=False,
        assistance_request_id=None,
    ):

        # showcase / dry-run 不污染公共需求表。
        if self.dry_run:
            return None


        # external abnormality 属于其他场景。
        # 后续由对应异常场景写自己的共享需求。
        if risk_level == "external_route":
            return None


        care_domain = (
            care_domain
            or "general_care"
        )

        info = self._need_info(
            care_domain
        )

        if self._initial_care_domain is None:
            self._initial_care_domain = care_domain

        if self._initial_risk_level is None:
            self._initial_risk_level = risk_level


        details = {
            "care_domain":
                care_domain,

            "risk_level":
                risk_level,

            "staff_follow_up":
                bool(
                    staff_follow_up_created
                ),

            "assistance_request_id":
                assistance_request_id,

            # elder_need 是供跨场景和控制台快速查看的摘要。
            # 主咨询记录仍保留完整逐轮对话；这里保留当前轮，
            # 让工作人员看到最新的护理表达和风险状态。
            "latest_raw_text":
                str(raw_text or "").strip(),

            "initial_care_domain":
                self._initial_care_domain,

            "initial_risk_level":
                self._initial_risk_level,
        }


        # -------------------------------------------------
        # 本护理 session 第一次确认需求：
        # 创建一条共享需求。
        #
        # dedupe_key 保证同一个护理 session
        # 不会因为程序重试重复写。
        # -------------------------------------------------

        if self.need_id is None:

            row = create_need(
                elderly_id=
                    self.elderly_id,

                need_category=
                    "care",

                need_code=
                    info[
                        "need_code"
                    ],

                summary=
                    info[
                        "summary"
                    ],

                raw_text=
                    raw_text,

                priority=
                    self._priority(
                        risk_level
                    ),

                status=
                    "in_progress",

                source_scene=
                    SOURCE_SCENE,

                source_session_id=
                    self.session_id,

                source_round_no=
                    round_no,

                details=
                    details,

                dedupe_key=(
                    "care:"
                    f"{self.session_id}"
                ),

                handled_by=
                    SOURCE_SCENE,
            )

            self.need_id = (
                row[
                    "id"
                ]
            )

            return row


        # -------------------------------------------------
        # 后续轮次更新同一条需求，
        # 不创建新行。
        # -------------------------------------------------

        return update_need(
            self.need_id,

            summary=
                info[
                    "summary"
                ],

            priority=
                self._priority(
                    risk_level
                ),

            status=
                "in_progress",

            raw_text=
                str(raw_text or "").strip(),

            source_round_no=
                round_no,

            details=
                details,

            handled_by=
                (
                    "care_staff_follow_up"
                    if staff_follow_up_created
                    else SOURCE_SCENE
                ),
        )


    def finalize(
        self,
        *,
        care_domain,
        risk_level,
        end_reason,
        staff_follow_up_created=False,
        assistance_request_id=None,
    ):

        if (
            self.dry_run
            or self.need_id is None
        ):

            return None


        row = get_need(
            self.need_id
        )

        if row is None:
            return None

        old_details = (
            row.get(
                "details"
            )
            or {}
        )


        details = {
            **old_details,

            "care_domain":
                care_domain,

            "risk_level":
                risk_level,

            "staff_follow_up":
                bool(
                    staff_follow_up_created
                ),

            "assistance_request_id":
                assistance_request_id,

            "care_end_reason":
                end_reason,
        }


        # -------------------------------------------------
        # 有工作人员后续任务时：
        # 护理对话结束，但共享需求仍保持处理中。
        #
        # 否则护理场景正常结束时，
        # 这次需求标记 completed。
        # -------------------------------------------------

        if (
            risk_level == "needs_staff"
            and staff_follow_up_created
        ):

            status = (
                "in_progress"
            )

            handled_by = (
                "care_staff_follow_up"
            )

        elif end_reason == "processing_error":

            status = "failed"

            handled_by = (
                SOURCE_SCENE
            )

        elif end_reason == "manual_interrupt":

            status = "cancelled"

            handled_by = (
                SOURCE_SCENE
            )

        else:

            status = "completed"

            handled_by = (
                SOURCE_SCENE
            )


        return update_need(
            self.need_id,

            status=
                status,

            priority=
                self._priority(
                    risk_level
                ),

            details=
                details,

            handled_by=
                handled_by,
        )
