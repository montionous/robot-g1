#!/usr/bin/env python3
"""Prepare clearly labelled, synthetic music preference for the bound elder.

Default --preview is READ-ONLY. --apply explicitly writes one idempotent sample
through elder_need_registry. Never modifies other elders or opera records.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

SCENE_DIR = Path(__file__).resolve().parent
SPEECH_ROOT = SCENE_DIR.parents[1]
sys.path.insert(0, str(SPEECH_ROOT))
sys.path.insert(0, str(SCENE_DIR))
DB = SPEECH_ROOT / "data" / "elder_companion.db"


def ro_connect():
    if not DB.is_file():
        raise RuntimeError(f"共享数据库不存在: {DB}")
    con = sqlite3.connect(DB.resolve().as_uri() + "?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def get_explicit(con, elder_id: int, category: str):
    rows = con.execute(
        """SELECT id, status, details_json, dedupe_key FROM elder_need
           WHERE elderly_id=? AND need_category='entertainment'
             AND need_code=? AND status='completed' ORDER BY id DESC""",
        (elder_id, f"play_{category}"),
    ).fetchall()
    selected = []
    for row in rows:
        try:
            detail = json.loads(row["details_json"] or "{}")
        except (TypeError, ValueError):
            continue
        if isinstance(detail, dict) and detail.get("request_mode") == "explicit":
            selected.append((row, detail))
    return selected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--elder-id", type=int, required=True, help="当前绑定的老人ID")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--preview", action="store_true", help="只读预览（默认）")
    mode.add_argument("--apply", action="store_true", help="确认写入明确标记的模拟数据")
    args = parser.parse_args()

    from elder_need_registry import create_need, elderly_is_enabled, update_need
    from entertainment_controller import EntertainmentController
    from entertainment_need_integration import EntertainmentNeedSession

    if not elderly_is_enabled(args.elder_id):
        raise SystemExit(f"停止：老人ID={args.elder_id} 不存在或未启用")
    import elder_need_registry as reg
    if getattr(reg, "DB_PATH", None) is not None and Path(reg.DB_PATH).resolve() != DB.resolve():
        raise SystemExit("停止：共享注册表使用的数据库与预期路径不一致")

    controller = EntertainmentController()
    music = [item for item in controller.library.list_items("music") if Path(item.path).is_file()]
    opera = [item for item in controller.library.list_items("opera") if Path(item.path).is_file()]
    if len(music) < 2 or not opera:
        raise SystemExit("停止：需要至少两首有效音乐和一段有效戏曲，不能构造可靠对比")

    # Choose a song other than the catalog's first: preference must visibly
    # affect selection rather than coincidentally matching default ordering.
    first = controller.library.first("music")
    choices = [item for item in music if first is not None and Path(item.path) != Path(first.path)]
    if not choices:
        raise SystemExit("停止：未找到与默认第一首不同的有效音乐")
    chosen = choices[0]
    dedupe = f"companion_entertainment:demo_fixture:elder_{args.elder_id}:music_v1"

    with ro_connect() as con:
        elder_row = con.execute(
            "SELECT id, enabled FROM elderly_person WHERE id=?", (args.elder_id,)
        ).fetchone()
        if elder_row is None or not elder_row["enabled"]:
            raise SystemExit("停止：共享数据库没有启用的指定老人")
        existing = con.execute("SELECT * FROM elder_need WHERE dedupe_key=?", (dedupe,)).fetchone()
        music_history = get_explicit(con, args.elder_id, "music")
        opera_history = get_explicit(con, args.elder_id, "opera")

    print("当前绑定老人ID:", args.elder_id)
    print("默认第一首:", first.title)
    print("拟模拟点播:", chosen.title)
    print("本地戏曲数量:", len(opera))
    print("已有音乐明确点播记录:", len(music_history))
    print("已有戏曲明确点播记录:", len(opera_history))
    print("操作模式:", "写入演示模拟数据" if args.apply else "只读预览")

    if opera_history:
        raise SystemExit("停止：该老人已有已完成的明确戏曲点播，不能声称‘戏曲无偏好’；未修改任何记录")
    if existing is not None:
        try:
            existing_details = json.loads(existing["details_json"] or "{}")
        except (TypeError, ValueError):
            existing_details = None
        if (
            existing["elderly_id"] != args.elder_id
            or existing["need_code"] != "play_music"
            or not isinstance(existing_details, dict)
            or existing_details.get("demo_fixture") is not True
            or existing_details.get("title") != chosen.title
        ):
            raise SystemExit("停止：固定去重键对应的旧记录与目标不一致，避免覆盖或冒认历史")
        print("发现相同的演示种子记录：", existing["id"], existing["status"])
        if existing["status"] == "completed":
            print("已经完成初始化，重复运行不会写入。")
            return
        if existing["status"] != "in_progress":
            raise SystemExit("停止：已有种子记录状态不适合自动恢复")
    elif music_history:
        raise SystemExit("停止：该老人已经有音乐明确点播历史，请先核实再决定是否需要模拟种子；未写入")

    if not args.apply:
        print("预览通过；需要实际写入时添加 --apply，届时将先备份共享SQLite数据库。")
        return

    # SQLite's backup API correctly includes any current WAL data.
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = SPEECH_ROOT / "backups" / f"entertainment_music_demo_seed_{stamp}"
    backup_dir.mkdir(parents=True, exist_ok=False)
    backup = backup_dir / "elder_companion.db"
    with sqlite3.connect(DB) as src, sqlite3.connect(backup) as dst:
        src.backup(dst)
    print("数据库备份:", backup)

    details = {
        "request_mode": "explicit", "media_type": "music",
        "title": chosen.title, "demo_fixture": True,
        "data_origin": "synthetic_example_for_showcase",
        "note": "脚本预置的模拟历史记录；不是老人真实语音，也不表示真实播放已发生",
        "simulated_request_text": f"我想听{chosen.title}",
    }
    if existing is None:
        record = create_need(
            elderly_id=args.elder_id,
            need_category="entertainment", need_code="play_music",
            summary=f"【演示模拟】历史音乐点播《{chosen.title}》",
            raw_text=None,  # Do not forge an elder's actual utterance.
            priority="normal", status="in_progress",
            source_scene="COMPANION_ENTERTAINMENT_DEMO_FIXTURE",
            source_session_id=f"demo_fixture:elder_{args.elder_id}:v1",
            source_round_no=1, details=details, dedupe_key=dedupe,
            handled_by="COMPANION_ENTERTAINMENT",
        )
        record_id = int(record["id"])
    else:
        record_id = int(existing["id"])

    result = update_need(record_id, status="completed", handled_by="COMPANION_ENTERTAINMENT")
    if result is None or result.get("status") != "completed":
        raise RuntimeError("未能确认模拟历史记录完成状态；请检查数据库及备份")

    needs = EntertainmentNeedSession(elderly_id=args.elder_id, library=controller.library, record=False)
    preferred_music = needs.preferred_item("music")
    preferred_opera = needs.preferred_item("opera")
    controller.preferred_item_lookup = needs.preferred_item
    play_result = controller.play_category("music")
    played = (play_result.get("play_item") or {}).get("title")
    if not preferred_music or preferred_music.title != chosen.title or preferred_opera is not None or played != chosen.title:
        raise RuntimeError("写入后偏好检查未通过；没有自动恢复共享数据库，以避免覆盖队友并发写入；请核查记录")

    log_dir = SPEECH_ROOT / "change_logs/chatgpt"
    log_dir.mkdir(parents=True, exist_ok=True)
    log = log_dir / f"{stamp}_demo_music_preference_seed.md"
    log.write_text(
        f"""# 演示模拟音乐偏好数据库记录 - {stamp}

## 数据性质
这是**明确标记的模拟历史数据**，不能作为老人真实点播经历的证明。不会创建其他老人，也未写入或删除戏曲偏好。

## 数据库
- 共用数据库：`data/elder_companion.db`
- 当前服务老人：`elderly_id={args.elder_id}`（启动时仍须显式绑定）
- 新增/确认记录：`elder_need.id={record_id}`
- `need_category=entertainment`, `need_code=play_music`, `status=completed`
- `request_mode=explicit`, `title={chosen.title}`, `demo_fixture=true`
- `raw_text=NULL`；模拟的点播文字只在 details 中，未伪装成真实老人原话
- `dedupe_key={dedupe}`
- 源：`COMPANION_ENTERTAINMENT_DEMO_FIXTURE`
- 备份：`{backup}`

## 验证
- 通过公共 registry 写入和更新，不手改时间字段。
- 校验偏好歌曲：`{chosen.title}`（区别于默认首曲 `{first.title}`）。
- 戏曲 `preferred_item('opera')` 返回 None；目录中仍有可播放戏曲。
- `controller.play_category('music')` 选择模拟偏好曲目。
- 没有调用机器人、播放或 TTS；没有校验队友的实时读取连接。

## Codex 接手
请保留 seed 脚本 `scenarios/companion_entertainment/seed_demo_music_preference.py` 的预览默认模式、显式 --apply、去重键、演示标记及戏曲历史保护。正式数据采集时不要当成真实历史。
""",
        encoding="utf-8",
    )
    print("模拟音乐偏好已写入：记录ID", record_id)
    print("验证：音乐选择", played, "；戏曲无明确历史偏好")
    print("Codex 变更记录:", log)


if __name__ == "__main__":
    main()
