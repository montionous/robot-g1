from __future__ import annotations

from demo_protocol import (
    ALLOWED_BY_STATE,
    DONE,
    END,
    NEXT_MUSIC,
    OTHER,
    PLAYING_MUSIC_FIRST,
    PLAYING_MUSIC_SECOND,
    PLAYING_NEWS,
    PLAYING_OPERA,
    PLAY_MUSIC,
    SWITCH_NEWS,
    SWITCH_OPERA,
    WAIT_MUSIC_REQUEST,
)


class ShowcaseController:

    def __init__(self):
        self.state = (
            WAIT_MUSIC_REQUEST
        )


    @property
    def done(self):
        return self.state == DONE


    @property
    def allowed_intents(self):
        return set(
            ALLOWED_BY_STATE.get(
                self.state,
                set(),
            )
        )


    def handle(
        self,
        intent,
    ):
        if self.done:
            return {
                "action": "done",
                "state": self.state,
                "done": True,
            }

        if intent == OTHER:
            return {
                "action": "ignore",
                "state": self.state,
                "done": False,
            }

        if (
            intent
            not in self.allowed_intents
        ):
            return {
                "action": "ignore",
                "state": self.state,
                "done": False,
            }

        if intent == END:
            self.state = DONE

            return {
                "action": END,
                "state": self.state,
                "done": True,
            }

        if (
            self.state
            == WAIT_MUSIC_REQUEST
            and intent
            == PLAY_MUSIC
        ):
            self.state = (
                PLAYING_MUSIC_FIRST
            )

            return {
                "action": PLAY_MUSIC,
                "state": self.state,
                "done": False,
            }

        if (
            self.state
            == PLAYING_MUSIC_FIRST
            and intent
            == NEXT_MUSIC
        ):
            self.state = (
                PLAYING_MUSIC_SECOND
            )

            return {
                "action": NEXT_MUSIC,
                "state": self.state,
                "done": False,
            }

        if (
            self.state
            == PLAYING_MUSIC_SECOND
            and intent
            == SWITCH_NEWS
        ):
            self.state = (
                PLAYING_NEWS
            )

            return {
                "action": SWITCH_NEWS,
                "state": self.state,
                "done": False,
            }

        if (
            self.state
            == PLAYING_NEWS
            and intent
            == SWITCH_OPERA
        ):
            self.state = (
                PLAYING_OPERA
            )

            return {
                "action": SWITCH_OPERA,
                "state": self.state,
                "done": False,
            }

        return {
            "action": "ignore",
            "state": self.state,
            "done": False,
        }
