#!/usr/bin/env python3

from __future__ import annotations

import sqlite3
from pathlib import Path


PROJECT_ROOT = (
    Path(__file__).resolve()
    .parents[2]
)

DB_PATH = (
    PROJECT_ROOT
    / "data"
    / "elder_companion.db"
)


ELDERLY_ID = 1


def main():

    conn = sqlite3.connect(DB_PATH)

    conn.execute(
        "PRAGMA foreign_keys = ON"
    )

    elder = conn.execute(
        """
        SELECT id, name
        FROM elderly_person
        WHERE id = ?
        """,
        (ELDERLY_ID,),
    ).fetchone()

    if elder is None:
        raise RuntimeError(
            "找不到 elderly_id=1"
        )


    # =====================================================
    # 病史
    # =====================================================

    conditions = [
        (
            ELDERLY_ID,
            "膝骨关节炎",
            "musculoskeletal",
            "knee",
            "active",
            1,
            "2024",
            (
                "既往已确诊。"
                "用于比赛演示中的个体化护理背景，"
                "不代表机器人重新进行疾病诊断。"
            ),
        ),
        (
            ELDERLY_ID,
            "高血压",
            "cardiovascular",
            None,
            "active",
            1,
            "2023",
            (
                "既往已确诊。"
                "当前护理咨询中仅作为健康背景，"
                "不由机器人调整用药。"
            ),
        ),
    ]

    for row in conditions:

        conn.execute(
            """
            INSERT INTO elder_health_condition (
                elderly_id,
                condition_name,
                condition_category,
                body_area,
                status,
                diagnosed,
                diagnosed_at,
                notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)

            ON CONFLICT(
                elderly_id,
                condition_name
            )
            DO UPDATE SET
                condition_category =
                    excluded.condition_category,
                body_area =
                    excluded.body_area,
                status =
                    excluded.status,
                diagnosed =
                    excluded.diagnosed,
                diagnosed_at =
                    excluded.diagnosed_at,
                notes =
                    excluded.notes,
                verified = 1,
                source =
                    'demo_verified_record'
            """,
            row,
        )


    # =====================================================
    # 护理基线
    # =====================================================

    baselines = [
        (
            ELDERLY_ID,
            "mobility",
            "usual_knee_state",
            (
                "平时膝部偶尔有轻度酸胀，"
                "通常休息后能够缓解"
            ),
        ),
        (
            ELDERLY_ID,
            "mobility",
            "walking_independence",
            "室内通常可以独立站立和行走",
        ),
        (
            ELDERLY_ID,
            "mobility",
            "assistive_device",
            "外出时通常使用手杖",
        ),
        (
            ELDERLY_ID,
            "sleep",
            "usual_sleep",
            (
                "平时偶尔夜间醒来一次，"
                "多数情况下能够再次入睡"
            ),
        ),
        (
            ELDERLY_ID,
            "appetite",
            "usual_appetite",
            (
                "平时食欲尚可，"
                "通常可以完成大部分正餐"
            ),
        ),
    ]

    for row in baselines:

        conn.execute(
            """
            INSERT INTO elder_care_baseline (
                elderly_id,
                care_domain,
                baseline_key,
                baseline_value
            )
            VALUES (?, ?, ?, ?)

            ON CONFLICT(
                elderly_id,
                care_domain,
                baseline_key
            )
            DO UPDATE SET
                baseline_value =
                    excluded.baseline_value,
                verified = 1,
                source =
                    'demo_verified_record',
                updated_at =
                    CURRENT_TIMESTAMP
            """,
            row,
        )


    # =====================================================
    # 护理历史
    # 先删除本条演示记录，避免反复 seed 产生重复数据
    # =====================================================

    conn.execute(
        """
        DELETE FROM elder_care_event
        WHERE elderly_id = ?
          AND event_type = 'fall'
          AND summary =
              '半年前有一次跌倒记录，之后恢复日常行走'
        """,
        (ELDERLY_ID,),
    )

    conn.execute(
        """
        INSERT INTO elder_care_event (
            elderly_id,
            event_type,
            event_date,
            care_domain,
            summary,
            outcome
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            ELDERLY_ID,
            "fall",
            "2026-03",
            "mobility",
            (
                "半年前有一次跌倒记录，"
                "之后恢复日常行走"
            ),
            "目前维持日常行走能力",
        ),
    )


    conn.commit()
    conn.close()

    print(
        f"王大爷个体护理演示档案写入完成 elderly_id={ELDERLY_ID}"
    )


if __name__ == "__main__":
    main()
