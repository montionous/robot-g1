from __future__ import annotations

import argparse

from care_controller import (
    CareConsultation,
)

from care_db import (
    add_message,
    create_session,
    finish_session,
    get_elderly,
    update_session_context,
)

from care_intent import (
    is_care_trigger,
)


def banner(
    text,
):

    print()
    print("=" * 72)
    print(text)
    print("=" * 72)


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--elderly-id",
        type=int,
        default=1,
    )

    parser.add_argument(
        "--max-rounds",
        type=int,
        default=3,
    )

    parser.add_argument(
        "--utterance",
        default=None,
    )

    args = parser.parse_args()


    elderly = get_elderly(
        args.elderly_id
    )

    if elderly is None:

        raise RuntimeError(
            "老人不存在: "
            f"elderly_id={args.elderly_id}"
        )


    banner(
        "CARE_CONSULTATION_SUPPORT 日常护理咨询"
    )

    print(
        "当前老人:",
        elderly["name"],
    )

    print(
        "最大咨询轮数:",
        args.max_rounds,
    )


    if args.utterance:

        first_text = (
            args.utterance
            .strip()
        )

    else:

        first_text = input(
            "\n老人> "
        ).strip()


    if not is_care_trigger(
        first_text
    ):

        print(
            "场景判断: "
            "NOT_CARE_CONSULTATION"
        )

        return


    print(
        "场景判断: "
        "CARE_CONSULTATION_SUPPORT"
    )


    session_id = (
        create_session(
            args.elderly_id,
            args.max_rounds,
        )
    )


    consultation = (
        CareConsultation(
            elderly_id=
                args.elderly_id,

            session_id=
                session_id,

            max_rounds=
                args.max_rounds,
        )
    )


    current_text = first_text
    first_turn = True


    while True:

        if first_turn:

            result = (
                consultation.start(
                    current_text
                )
            )

            first_turn = False

        else:

            result = (
                consultation
                .handle_user_text(
                    current_text
                )
            )


        round_no = max(
            1,
            consultation.round_no,
        )


        add_message(
            session_id=
                session_id,

            round_no=
                round_no,

            role=
                "user",

            content=
                current_text,

            tags=None,
        )


        update_session_context(
            session_id=
                session_id,

            care_domain=
                result.get(
                    "care_domain"
                ),

            risk_level=
                result.get(
                    "risk_level"
                ),
        )


        print()
        print(
            "护理领域:",
            result.get(
                "care_domain"
            ),
        )

        print(
            "风险等级:",
            result.get(
                "risk_level"
            ),
        )


        tags = result.get(
            "tags"
        )

        if tags:

            print(
                "LLM Tags:",
                tags,
            )


        reply = result.get(
            "reply"
        )

        if reply:

            print(
                "机器人:",
                reply,
            )

            add_message(
                session_id=
                    session_id,

                round_no=
                    round_no,

                role=
                    "assistant",

                content=
                    reply,

                tags=
                    tags,
            )


        if result.get(
            "llm_ms"
        ) is not None:

            print(
                "LLM耗时:",
                f"{result['llm_ms']:.0f} ms",
            )


        transfer_to = (
            result.get(
                "transfer_to"
            )
        )

        if transfer_to:

            print(
                "场景转移:",
                transfer_to,
            )

            finish_session(
                session_id=
                    session_id,

                completed_rounds=
                    consultation.round_no,

                end_reason=
                    result.get(
                        "end_reason",
                        "transfer",
                    ),
            )

            return


        if (
            result.get(
                "state"
            )
            == "ENDED"
        ):

            request_id = (
                result.get(
                    "assistance_request_id"
                )
            )

            if request_id:

                print(
                    "护理请求已记录:",
                    request_id,
                )


            finish_session(
                session_id=
                    session_id,

                completed_rounds=
                    consultation.round_no,

                end_reason=
                    result.get(
                        "end_reason",
                        "completed",
                    ),
            )

            print(
                "护理咨询结束"
            )

            return


        current_text = input(
            "\n老人> "
        ).strip()


if __name__ == "__main__":
    main()
