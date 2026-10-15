from pathlib import Path
import sqlite3


PROJECT_ROOT = (
    Path(__file__).resolve()
    .parent
)

DB_PATH = (
    PROJECT_ROOT
    / "data"
    / "elder_companion.db"
)


def main():

    conn = sqlite3.connect(
        DB_PATH
    )

    conn.execute(
        "PRAGMA foreign_keys = ON"
    )

    # 多个场景可能同时读写同一个数据库。
    conn.execute(
        "PRAGMA journal_mode = WAL"
    )

    conn.execute(
        "PRAGMA busy_timeout = 5000"
    )


    # =====================================================
    # 跨场景统一老人需求表
    #
    # 一行 = 一次已经确认的老人需求
    #
    # 各场景自己的详细日志仍保留在各自业务表中。
    # 这里仅保存供其他模块共享的标准化需求。
    # =====================================================

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS elder_need (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            elderly_id INTEGER NOT NULL,

            need_category TEXT NOT NULL,
            need_code TEXT NOT NULL,

            summary TEXT NOT NULL,
            raw_text TEXT,

            priority TEXT NOT NULL
                DEFAULT 'normal',

            status TEXT NOT NULL
                DEFAULT 'detected',

            source_scene TEXT NOT NULL,

            source_session_id TEXT,
            source_round_no INTEGER,

            confidence REAL,

            details_json TEXT,

            dedupe_key TEXT UNIQUE,

            handled_by TEXT,

            created_at TEXT NOT NULL
                DEFAULT CURRENT_TIMESTAMP,

            updated_at TEXT NOT NULL
                DEFAULT CURRENT_TIMESTAMP,

            completed_at TEXT,

            FOREIGN KEY (elderly_id)
                REFERENCES elderly_person(id),

            CHECK (
                priority IN (
                    'normal',
                    'high',
                    'urgent'
                )
            ),

            CHECK (
                status IN (
                    'detected',
                    'in_progress',
                    'completed',
                    'cancelled',
                    'failed'
                )
            )
        )
        """
    )


    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS
            idx_elder_need_elder_created

        ON elder_need (
            elderly_id,
            created_at DESC
        )
        """
    )


    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS
            idx_elder_need_status_created

        ON elder_need (
            status,
            created_at DESC
        )
        """
    )


    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS
            idx_elder_need_scene_created

        ON elder_need (
            source_scene,
            created_at DESC
        )
        """
    )


    conn.commit()
    conn.close()


    print(
        "elder_need 公共需求表初始化完成"
    )

    print(
        "数据库:",
        DB_PATH,
    )


if __name__ == "__main__":
    main()
