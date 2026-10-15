"""Decode the two owners' JSONL contracts without importing their runtimes."""
import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

LOCAL_ZONE = ZoneInfo("Asia/Shanghai")
MAX_LINE = 64 * 1024
EMOTIONS = {"happy": "开心", "sad": "悲伤", "angry": "生气", "calm": "平静", "unknown": "无法判断"}
ANOMALIES = {"fall": "疑似跌倒", "night_rise": "夜间起身", "prolonged_static": "长时间静卧",
             "out_of_view": "目标离开视野", "audio_distress": "声音异常"}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def timestamp(value):
    if value in (None, ""):
        return None
    if not isinstance(value, str) or len(value) > 80:
        raise ValueError("时间格式不正确")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=LOCAL_ZONE)
    return parsed.astimezone(timezone.utc).isoformat(timespec="milliseconds")


def text(value, limit=2000):
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError("事件文本格式或长度不正确")
    return value


def number(value, minimum=0, maximum=1):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError("数值必须为有限数字")
    if not minimum <= value <= maximum:
        raise ValueError("数值超出允许范围")
    return value


def normalize(raw, module, mode):
    if not isinstance(raw, dict):
        raise ValueError("事件必须是 JSON 对象")
    if module == 'interaction':
        from .records import normalize as normalize_record
        return normalize_record(raw, mode)
    if str(raw.get("kind", "")).endswith("summary"):
        return None
    event_id = text(raw.get("event_id", ""), 160)
    if not event_id:
        raise ValueError("缺少 event_id")
    row = {"external_id": event_id, "module": module, "kind": "event", "mode": mode,
           "emotion": None, "level": None, "observed_at": None, "source_seconds": None,
           "score": None, "inference": "", "input_state": "", "notification": "unknown"}
    if module == "emotion":
        schema = raw.get("schema_version")
        if schema not in {"emotion_strategy_v1", "emotion_snapshot_v1"}:
            raise ValueError("不是情绪策略或状态记录")
        if raw.get('source_run_id') is not None:
            text(raw['source_run_id'], 160)
        emotion = raw.get("emotion")
        if emotion not in EMOTIONS or (schema == "emotion_strategy_v1" and emotion not in {"happy", "sad", "angry"}):
            raise ValueError("情绪类别不正确")
        reason = text(raw.get("reason", ""))
        row.update(emotion=emotion, observed_at=timestamp(raw.get("observed_at")),
                   title=EMOTIONS[emotion], detail={"emotion_entered": "检测到情绪线索，模块已生成回应策略",
                                                  "emotion_transition": "检测到情绪变化，模块已更新回应策略"}.get(reason, reason),
                   inference=text(raw.get("inference_level", ""), 80),
                   input_state=text(raw.get("input_state", ""), 80))
        if row["observed_at"] is None:
            raise ValueError("情绪记录缺少观测时间")
        if "match_score" in raw:
            row["score"] = number(raw["match_score"])
        if raw.get("source_kind") == "video":
            row["mode"] = "replay"
        if raw.get("source_seconds") is not None:
            row["source_seconds"] = number(raw["source_seconds"], maximum=1e11)
        if row["mode"] == "replay":
            row["observed_at"] = None
        elif (datetime.fromisoformat(row["observed_at"]) - datetime.now(timezone.utc)).total_seconds() > 5:
            raise ValueError("观测时间超前，请检查模块时钟")
        if schema == "emotion_snapshot_v1":
            row["kind"] = "snapshot"
    else:
        level = raw.get("level")
        event_type = text(raw.get("type", ""), 100)
        if level not in {"L1", "L2", "L3"} or not event_type:
            raise ValueError("异常记录缺少 type 或有效等级")
        seconds = number(raw.get("time", 0), maximum=1e11)
        replay = mode == "replay" or seconds < 1e9 or raw.get("source_kind") == "video"
        row.update(level=level, source_seconds=seconds if seconds < 1e9 else None,
                   observed_at=None if replay else datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec="milliseconds"),
                   title=ANOMALIES.get(event_type, event_type), detail=text(raw.get("reason", raw.get("subtype", ""))))
        if replay:
            row["mode"] = "replay"
        if "confidence" in raw:
            row["score"] = number(raw["confidence"])
        actions = raw.get("actions_taken", [])
        if not isinstance(actions, list) or len(actions) > 20 or any(not isinstance(a, str) for a in actions):
            raise ValueError("actions_taken 格式不正确")
        if "notify_l3" in actions or "ask_l2_then_notify" in actions:
            row["notification"] = "requested"
        if row["observed_at"] and (datetime.fromisoformat(row["observed_at"]) - datetime.now(timezone.utc)).total_seconds() > 5:
            raise ValueError("观测时间超前，请检查模块时钟")
    row["raw_json"] = json.dumps(raw, ensure_ascii=False, allow_nan=False, sort_keys=True)
    return row


def allowed_path(value, roots):
    path = Path(value).expanduser().resolve()
    if path.suffix != ".jsonl" or not any(path.is_relative_to(root.resolve()) for root in roots):
        raise ValueError("只允许接入指定模块目录内的 JSONL 文件")
    if path.exists() and not path.is_file():
        raise ValueError("数据源不是普通文件")
    return path


def read_batch(source, roots):
    path = allowed_path(source["path"], roots)
    with path.open("rb") as stream:
        stat = os.fstat(stream.fileno())
        first = stream.readline(MAX_LINE + 1)
        fingerprint = f"{stat.st_dev}:{stat.st_ino}:" + (hashlib.sha256(first).hexdigest() if first.endswith(b"\n") else "")
        changed = source["fingerprint"] and source["fingerprint"] != fingerprint
        if source["boundary"] and stat.st_size >= source["offset"]:
            stream.seek(max(0, source["offset"] - 4096))
            changed = changed or hashlib.sha256(stream.read(min(source["offset"], 4096))).hexdigest() != source["boundary"]
        reset = bool(changed or stat.st_size < source["offset"])
        generation = source["generation"] + int(reset)
        stream.seek(0 if reset else source["offset"])
        rows, rejected, error = [], 0, ""
        for _ in range(500):
            position = stream.tell()
            line = stream.readline(MAX_LINE + 1)
            if len(line) > MAX_LINE:
                raise ValueError("单条记录超过 64 KiB；请由模块缩小记录后重新接入")
            if not line or not line.endswith(b"\n"):
                stream.seek(position)
                break
            try:
                raw = json.loads(line, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("禁止 NaN/Infinity")))
                row = normalize(raw, source["module"], source["mode"])
                if row:
                    rows.append(row)
            except (ValueError, UnicodeDecodeError, TypeError, OverflowError, RecursionError) as exc:
                rejected += 1
                error = f"记录被拒绝：{exc}（byte {position}）"
        offset = stream.tell()
        stream.seek(max(0, offset - 4096))
        boundary = hashlib.sha256(stream.read(min(offset, 4096))).hexdigest()
        # shortcut: same first line and unchanged final 4 KiB cannot identify a rewritten prefix; use a new file per session.
        return rows, {"offset": offset, "fingerprint": fingerprint, "generation": generation,
                      "rejected": source["rejected"] + rejected,
                      "error": error or (source["error"] if source["error"].startswith("记录被拒绝：") else ""), "boundary": boundary}
