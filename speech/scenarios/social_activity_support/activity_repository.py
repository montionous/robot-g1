#!/usr/bin/env python3

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path

from init_activity_db import DB_PATH


class ActivityRepository:

    def _connect(self):

        conn = sqlite3.connect(
            DB_PATH
        )

        conn.row_factory = (
            sqlite3.Row
        )

        conn.execute(
            "PRAGMA foreign_keys = ON"
        )

        return conn


    @staticmethod
    def _row_to_dict(
        row,
    ):

        if row is None:
            return None

        item = dict(row)

        capacity = item.get(
            "capacity"
        )

        registered = item.get(
            "registered_count",
            0,
        )

        if capacity is None:
            item[
                "available_spots"
            ] = None

        else:
            item[
                "available_spots"
            ] = max(
                0,
                capacity
                - registered,
            )

        return item


    def query_sessions(
        self,
        *,
        activity_date=None,
        period=None,
        category=None,
        keyword=None,
        include_cancelled=False,
        limit=30,
    ):

        if activity_date is None:
            activity_date = (
                date.today()
                .isoformat()
            )

        sql = """
        SELECT
            s.session_id,
            s.activity_date,
            s.start_time,
            s.end_time,
            s.capacity,
            s.registered_count,
            s.registration_deadline,
            s.status,

            a.activity_id,
            a.name,
            a.category,
            a.description,
            a.tags,
            a.organizer,
            a.location,
            a.requires_registration,
            a.notes

        FROM social_activity_session AS s

        JOIN social_activity AS a
          ON a.activity_id = s.activity_id

        WHERE
            a.enabled = 1
            AND s.activity_date = ?
        """

        params = [
            activity_date
        ]

        # 查询今天的活动时，不再推荐已经结束的场次。
        # 正在进行中的活动仍然可以保留。
        if (
            activity_date
            == date.today().isoformat()
        ):
            sql += """
            AND s.end_time > ?
            """

            params.append(
                datetime.now().strftime(
                    "%H:%M"
                )
            )


        if not include_cancelled:

            sql += """
            AND s.status != 'cancelled'
            """


        if period == "morning":

            sql += """
            AND s.start_time < '12:00'
            """

        elif period == "afternoon":

            sql += """
            AND s.start_time >= '12:00'
            AND s.start_time < '18:00'
            """

        elif period == "evening":

            sql += """
            AND s.start_time >= '18:00'
            """


        if category:

            sql += """
            AND a.category = ?
            """

            params.append(
                category
            )


        if keyword:

            pattern = (
                f"%{keyword}%"
            )

            sql += """
            AND (
                a.name LIKE ?
                OR a.tags LIKE ?
                OR a.description LIKE ?
            )
            """

            params.extend(
                [
                    pattern,
                    pattern,
                    pattern,
                ]
            )


        sql += """
        ORDER BY

            CASE s.status
                WHEN 'open'
                    THEN 0
                WHEN 'full'
                    THEN 1
                WHEN 'closed'
                    THEN 2
                WHEN 'cancelled'
                    THEN 3
                ELSE 4
            END,

            s.start_time
        LIMIT ?
        """

        params.append(
            int(limit)
        )


        with self._connect() as conn:

            rows = conn.execute(
                sql,
                params,
            ).fetchall()


        return [
            self._row_to_dict(
                row
            )
            for row in rows
        ]


    def list_activities(
        self,
        *,
        enabled_only=True,
    ):
        """
        返回活动目录。

        用于把老人自然语言约束到
        数据库中真实存在的活动。
        """

        sql = """
        SELECT
            activity_id,
            name,
            category,
            description,
            tags,
            organizer,
            location,
            requires_registration,
            notes,
            enabled
        FROM social_activity
        """

        params = []

        if enabled_only:
            sql += """
            WHERE enabled = 1
            """

        sql += """
        ORDER BY activity_id
        """

        with self._connect() as conn:

            rows = conn.execute(
                sql,
                params,
            ).fetchall()

        return [
            dict(row)
            for row in rows
        ]


    def get_session(
        self,
        session_id,
    ):

        sql = """
        SELECT
            s.session_id,
            s.activity_date,
            s.start_time,
            s.end_time,
            s.capacity,
            s.registered_count,
            s.registration_deadline,
            s.status,

            a.activity_id,
            a.name,
            a.category,
            a.description,
            a.tags,
            a.organizer,
            a.location,
            a.requires_registration,
            a.notes

        FROM social_activity_session AS s

        JOIN social_activity AS a
          ON a.activity_id = s.activity_id

        WHERE
            s.session_id = ?
        """

        with self._connect() as conn:

            row = conn.execute(
                sql,
                (
                    session_id,
                ),
            ).fetchone()

        return self._row_to_dict(
            row
        )


    def query_upcoming_sessions(
        self,
        *,
        activity_id=None,
        days=7,
        include_cancelled=False,
        limit=30,
    ):
        """
        查询从现在开始未来若干天的场次。
        """

        from datetime import timedelta

        today = date.today()

        end_date = (
            today
            + timedelta(
                days=max(
                    1,
                    int(days),
                )
                - 1
            )
        )

        now_time = (
            datetime.now()
            .strftime("%H:%M")
        )

        sql = """
        SELECT
            s.session_id,
            s.activity_date,
            s.start_time,
            s.end_time,
            s.capacity,
            s.registered_count,
            s.registration_deadline,
            s.status,

            a.activity_id,
            a.name,
            a.category,
            a.description,
            a.tags,
            a.organizer,
            a.location,
            a.requires_registration,
            a.notes

        FROM social_activity_session AS s

        JOIN social_activity AS a
          ON a.activity_id = s.activity_id

        WHERE
            a.enabled = 1

            AND s.activity_date
                BETWEEN ? AND ?

            AND (
                s.activity_date > ?
                OR (
                    s.activity_date = ?
                    AND s.end_time > ?
                )
            )
        """

        params = [
            today.isoformat(),
            end_date.isoformat(),
            today.isoformat(),
            today.isoformat(),
            now_time,
        ]

        if activity_id is not None:

            sql += """
            AND s.activity_id = ?
            """

            params.append(
                int(activity_id)
            )

        if not include_cancelled:

            sql += """
            AND s.status != 'cancelled'
            """

        sql += """
        ORDER BY
            s.activity_date,
            s.start_time
        LIMIT ?
        """

        params.append(
            int(limit)
        )

        with self._connect() as conn:

            rows = conn.execute(
                sql,
                params,
            ).fetchall()

        return [
            self._row_to_dict(
                row
            )
            for row in rows
        ]


    def get_next_session(
        self,
        *,
        activity_id,
        after_date,
        after_time="00:00",
        only_available=False,
    ):
        """
        查询同一个活动在指定时间之后的下一场。

        only_available=True 时，
        跳过 cancelled / full / closed，
        并跳过已经没有剩余名额的场次。
        """

        sql = """
        SELECT
            s.session_id,
            s.activity_date,
            s.start_time,
            s.end_time,
            s.capacity,
            s.registered_count,
            s.registration_deadline,
            s.status,

            a.activity_id,
            a.name,
            a.category,
            a.description,
            a.tags,
            a.organizer,
            a.location,
            a.requires_registration,
            a.notes

        FROM social_activity_session AS s

        JOIN social_activity AS a
          ON a.activity_id = s.activity_id

        WHERE
            a.enabled = 1
            AND s.activity_id = ?
            AND (
                s.activity_date > ?
                OR (
                    s.activity_date = ?
                    AND s.start_time > ?
                )
            )
        """

        params = [
            activity_id,
            after_date,
            after_date,
            after_time,
        ]

        if only_available:

            sql += """
            AND s.status = 'open'

            AND (
                s.capacity IS NULL
                OR s.registered_count < s.capacity
            )
            """

        sql += """
        ORDER BY
            s.activity_date,
            s.start_time
        LIMIT 1
        """

        with self._connect() as conn:

            row = conn.execute(
                sql,
                params,
            ).fetchone()

        return self._row_to_dict(
            row
        )


    def get_interest(
        self,
        elder_id,
        session_id,
    ):

        with self._connect() as conn:

            row = conn.execute(
                """
                SELECT *
                FROM social_activity_interest
                WHERE
                    elder_id = ?
                    AND session_id = ?
                """,
                (
                    elder_id,
                    session_id,
                ),
            ).fetchone()

        return (
            dict(row)
            if row
            else None
        )


    def record_interest(
        self,
        *,
        elder_id,
        session_id,
        status,
    ):

        existing = self.get_interest(
            elder_id,
            session_id,
        )

        if existing:

            return {
                "created": False,
                "interest":
                    existing,
            }


        with self._connect() as conn:

            cursor = conn.execute(
                """
                INSERT INTO social_activity_interest (
                    elder_id,
                    session_id,
                    status
                )
                VALUES (?, ?, ?)
                """,
                (
                    elder_id,
                    session_id,
                    status,
                ),
            )

            conn.commit()

            interest_id = (
                cursor.lastrowid
            )


        return {
            "created": True,

            "interest": {
                "interest_id":
                    interest_id,

                "elder_id":
                    elder_id,

                "session_id":
                    session_id,

                "status":
                    status,
            },
        }


    def create_notification(
        self,
        *,
        elder_id,
        session_id,
        notification_type,
        message,
    ):

        with self._connect() as conn:

            cursor = conn.execute(
                """
                INSERT INTO staff_notification (
                    elder_id,
                    session_id,
                    notification_type,
                    message,
                    status
                )
                VALUES (?, ?, ?, ?, 'pending')
                """,
                (
                    elder_id,
                    session_id,
                    notification_type,
                    message,
                ),
            )

            conn.commit()

            return (
                cursor.lastrowid
            )


if __name__ == "__main__":

    repo = ActivityRepository()

    for item in repo.query_sessions():

        print(
            item["start_time"],
            item["name"],
            item["status"],
            item["available_spots"],
        )
