from pathlib import Path
import sqlite3


PROJECT_ROOT = (
    Path(__file__).resolve()
    .parents[2]
)

DB_PATH = (
    PROJECT_ROOT
    / "data"
    / "elder_companion.db"
)


def main():

    conn = sqlite3.connect(DB_PATH)

    conn.execute(
        "PRAGMA foreign_keys = ON"
    )

    # 一次护理咨询
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS care_consultation_session (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            elderly_id INTEGER NOT NULL,

            max_rounds INTEGER NOT NULL DEFAULT 3,
            completed_rounds INTEGER NOT NULL DEFAULT 0,

            care_domain TEXT,
            risk_level TEXT,

            status TEXT NOT NULL DEFAULT 'consulting',
            end_reason TEXT,

            started_at TEXT NOT NULL
                DEFAULT CURRENT_TIMESTAMP,

            ended_at TEXT,

            FOREIGN KEY (elderly_id)
                REFERENCES elderly_person(id)
        )
        """
    )

    # 每一轮咨询消息
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS care_consultation_message (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            session_id INTEGER NOT NULL,

            round_no INTEGER NOT NULL,

            role TEXT NOT NULL,

            content TEXT NOT NULL,

            tags_json TEXT,

            created_at TEXT NOT NULL
                DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (session_id)
                REFERENCES care_consultation_session(id)
        )
        """
    )

    # 需要工作人员后续处理的护理请求
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS care_assistance_request (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            session_id INTEGER NOT NULL,
            elderly_id INTEGER NOT NULL,

            care_domain TEXT NOT NULL,
            risk_level TEXT NOT NULL,

            user_description TEXT NOT NULL,
            summary TEXT NOT NULL,

            status TEXT NOT NULL DEFAULT 'pending',

            created_at TEXT NOT NULL
                DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (session_id)
                REFERENCES care_consultation_session(id),

            FOREIGN KEY (elderly_id)
                REFERENCES elderly_person(id)
        )
        """
    )

    conn.commit()
    conn.close()

    print(
        "CARE_CONSULTATION_SUPPORT 数据表初始化完成"
    )

    print(
        "数据库:",
        DB_PATH
    )


if __name__ == "__main__":
    main()
