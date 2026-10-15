#!/usr/bin/env python3
"""老人陪伴情绪模块：本地视频到 1/3/4 策略事件的最小闭环。"""

from __future__ import annotations

import argparse
from collections import Counter, deque
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time
from typing import Any
import uuid

import cv2
import numpy as np


# Persist one detector-run namespace so imported logs cannot cross-link local event IDs.
RECORD_SOURCE_RUN_ID = uuid.uuid4().hex
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MODEL_ROOT = (
    REPOSITORY_ROOT
    / "data/visual/models/opencv-zoo-47534e27c9851bb1128ccc0102f1145e27f23f98"
)
YUNET_MODEL = MODEL_ROOT / "face_detection_yunet/face_detection_yunet_2023mar.onnx"
FER_MODEL = (
    MODEL_ROOT
    / "facial_expression_recognition/facial_expression_recognition_mobilefacenet_2022july.onnx"
)
MEDIAPIPE_MODEL_ROOT = REPOSITORY_ROOT / "data/visual/models/mediapipe-vision-v1"
GESTURE_MODEL = MEDIAPIPE_MODEL_ROOT / "gesture_recognizer.task"
POSE_MODEL = MEDIAPIPE_MODEL_ROOT / "pose_landmarker_lite.task"
YUNET_SHA256 = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"
FER_SHA256 = "4f61307602fc089ce20488a31d4e4614e3c9753a7d6c41578c854858b183e1a9"
GESTURE_SHA256 = "97952348cf6a6a4915c2ea1496b4b37ebabc50cbbf80571435643c455f2b0482"
POSE_SHA256 = "59929e1d1ee95287735ddd833b19cf4ac46d29bc7afddbbf6753c459690d574a"
DEFAULT_CAMERA_RECORD_DIRECTORY = REPOSITORY_ROOT / "vedio"
DISPLAY_WINDOW_NAME = "Elder Companion Emotion"
DISPLAY_SCREEN_FILL = 0.90
FALLBACK_SCREEN_WIDTH = 1920
FALLBACK_SCREEN_HEIGHT = 1080
DEFAULT_DISPLAY_FACE_BOX_SCALE = 1.4
FER_LABELS = ("angry", "disgust", "fearful", "happy", "neutral", "sad", "surprised")
ACTIVE_EMOTIONS = {"happy", "sad", "angry"}
FACE_EMOTION_ALIASES = {"surprised": "happy"}
FACE_ANCHOR_MAX_AGE_SECONDS = 8.0
FACE_COVERAGE_MIN_LANDMARKS = 10
CLOSED_FIST_GEOMETRY_MAX_RATIO = 0.60
OPEN_PALM_GEOMETRY_MIN_EXTENDED_FINGERS = 3
OPEN_PALM_GEOMETRY_MIN_FINGER_RATIO = 0.75
OPEN_PALM_GEOMETRY_MAX_OFFICIAL_GAP_MS = 1000
OPEN_PALM_GEOMETRY_MIN_OFFICIAL_SAMPLES = 2
FIST_HAND_CONTINUITY_MAX_X_DELTA = 0.15
CLAP_OPEN_SHOULDER_RATIO = 0.6
CLAP_CLOSE_SHOULDER_RATIO = 0.25
CLAP_CONVERGED_SHOULDER_RATIO = 0.35
CLAP_OCCLUSION_MIDPOINT_SHOULDER_RATIO = 0.3
CLAP_CONTACT_WINDOW_MS = 1000
CLAP_CONTACTS_REQUIRED = 2
CLAP_BURST_SUSTAIN_MS = 600
FIST_CLAP_DISAMBIGUATION_SECONDS = 3.0
ANGRY_BEHAVIOR_CUES = frozenset(
    {"closed_fist", "rapid_downward_fist_lower_frame"}
)
MOTION_BEHAVIOR_CUES = frozenset({"wave_open_palm", "clap_two_hands"})
ANGRY_REARM_SECONDS = 30.0
HAND_CONNECTIONS = (
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (0, 9), (9, 10), (10, 11), (11, 12),
    (0, 13), (13, 14), (14, 15), (15, 16),
    (0, 17), (17, 18), (18, 19), (19, 20),
)
STRATEGIES: dict[str, dict[str, Any]] = {
    "happy": {
        "strategy_id": "SHARE_POSITIVE",
        "goal": "回应积极感受并邀请老人继续分享",
        "tone": "温暖、稍轻快但不夸张",
        "do": ["回应当前愉快感受", "用开放式问题邀请分享", "顺着当前话题倾听"],
        "avoid": ["夸张庆祝", "幼儿化表达", "连续追问", "突然切换话题"],
    },
    "sad": {
        "strategy_id": "EMPATHIZE_AND_INVITE",
        "goal": "表达关心并询问老人是否愿意倾诉",
        "tone": "温和、缓慢、不施压",
        "do": ["先表达关心", "提供倾诉或安静陪伴的选择", "愿意时耐心倾听"],
        "avoid": ["说教", "否定感受", "强迫倾诉", "心理诊断", "虚假承诺"],
    },
    "angry": {
        "strategy_id": "DEESCALATE_AND_GIVE_SPACE",
        "goal": "降低刺激并确认老人需要帮助还是安静空间",
        "tone": "低声、缓慢、克制",
        "do": ["承认可能感到不适或不满", "减少动作并保持距离", "只询问一项具体需求"],
        "avoid": ["争辩", "反复追问", "开玩笑", "突然靠近", "擅自触碰", "无条件认错"],
    },
}


class EmotionDemoError(RuntimeError):
    """本地原型的稳定错误码。"""


class EmotionFaceAlignmentError(EmotionDemoError):
    """当前人脸关键点不足以可靠对齐。"""


def map_face_emotion(
    raw_label: str | None,
    match_score: float,
    min_match_score: float,
) -> str | None:
    """将模型原始类别投影为当前三类主动情绪。"""
    mapped_label = FACE_EMOTION_ALIASES.get(raw_label, raw_label)
    if mapped_label in ACTIVE_EMOTIONS and match_score >= min_match_score:
        return mapped_label
    return None


class TemporalEmotionFilter:
    """用有界时间窗口稳定主动情绪，并对同一状态去重。"""

    def __init__(
        self,
        *,
        window_seconds: float = 2.5,
        minimum_span_seconds: float = 2.0,
        min_samples: int = 12,
        enter_ratio: float = 0.7,
        exit_ratio: float = 0.35,
        cooldown_seconds: float = 10.0,
    ) -> None:
        if not (
            0.0 < minimum_span_seconds <= window_seconds
            and min_samples >= 2
            and 0.0 <= exit_ratio < enter_ratio <= 1.0
            and cooldown_seconds >= 0.0
        ):
            raise ValueError("emotion_filter_config_invalid")
        self.window_seconds = window_seconds
        self.minimum_span_seconds = minimum_span_seconds
        self.min_samples = min_samples
        self.enter_ratio = enter_ratio
        self.exit_ratio = exit_ratio
        self.cooldown_seconds = cooldown_seconds
        self.samples: deque[tuple[float, str | None, float]] = deque()
        self.active_emotion: str | None = None
        self.last_event_at = -math.inf

    def update(
        self,
        label: str | None,
        match_score: float,
        timestamp: float,
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        if not math.isfinite(timestamp) or not math.isfinite(match_score):
            raise ValueError("emotion_sample_invalid")
        if self.samples and timestamp < self.samples[-1][0]:
            raise ValueError("emotion_timestamp_not_monotonic")

        self.samples.append((timestamp, label, float(match_score)))
        cutoff = timestamp - self.window_seconds
        while self.samples and self.samples[0][0] < cutoff:
            self.samples.popleft()

        counts = Counter(sample_label for _, sample_label, _ in self.samples)
        span_seconds = self.samples[-1][0] - self.samples[0][0]
        ready = len(self.samples) >= self.min_samples and span_seconds >= self.minimum_span_seconds
        candidate: str | None = None
        candidate_count = 0
        active_counts = sorted(
            ((counts[emotion], emotion) for emotion in ACTIVE_EMOTIONS),
            reverse=True,
        )
        if active_counts and active_counts[0][0] > 0:
            tied = len(active_counts) > 1 and active_counts[0][0] == active_counts[1][0]
            if not tied:
                candidate_count, candidate = active_counts[0]
        ratio = candidate_count / len(self.samples)
        scores = [score for _, sample_label, score in self.samples if sample_label == candidate]
        average_score = sum(scores) / len(scores) if scores else 0.0

        if self.active_emotion is not None and ready:
            current_ratio = counts[self.active_emotion] / len(self.samples)
            if current_ratio < self.exit_ratio:
                self.active_emotion = None

        event = None
        if (
            ready
            and candidate is not None
            and ratio >= self.enter_ratio
            and candidate != self.active_emotion
            and timestamp - self.last_event_at >= self.cooldown_seconds
        ):
            self.active_emotion = candidate
            self.last_event_at = timestamp
            event = make_strategy_event(candidate, average_score, ratio)

        return (
            {
                "candidate": candidate,
                "stability_ratio": ratio,
                "match_score": average_score,
                "ready": ready,
                "active_emotion": self.active_emotion,
                "observed_emotion": label,
                "observed_match_score": float(match_score),
            },
            event,
        )


def make_strategy_event(
    emotion: str,
    match_score: float,
    stability_ratio: float,
    *,
    inference_level: str = "stable_face",
    evidence_source: str = "face",
    behavior_cues: list[str] | None = None,
) -> dict[str, Any]:
    strategy = STRATEGIES[emotion]
    return {
        "schema_version": "emotion_strategy_v1",
        "event_id": uuid.uuid4().hex,
        "source_run_id": RECORD_SOURCE_RUN_ID,
        "observed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "emotion": emotion,
        "match_score": round(match_score, 4),
        "stability_ratio": round(stability_ratio, 4),
        "reason": "emotion_entered",
        "inference_level": inference_level,
        "evidence_source": evidence_source,
        "behavior_cues": list(behavior_cues or []),
        "strategy": {
            **strategy,
            "do": list(strategy["do"]),
            "avoid": list(strategy["avoid"]),
        },
    }


class BehaviorCueFilter:
    """稳定强动作线索；动作只补足无稳定面部情绪的时刻。"""

    _RULES = {
        "thumb_up": ("happy", 1.0, 0.8, 5),
        "wave_open_palm": ("happy", 1.0, 0.8, 5),
        "clap_two_hands": ("happy", 1.0, 0.8, 5),
        "closed_fist": ("angry", 1.0, 0.8, 5),
        "rapid_downward_fist_lower_frame": ("angry", 1.0, 0.8, 5),
        "hand_near_eye_head_down": ("sad", 1.75, 1.5, 6),
        "cover_face_head_down": ("sad", 1.75, 1.5, 6),
    }

    def __init__(self, *, enter_ratio: float = 0.7, exit_ratio: float = 0.35) -> None:
        self.enter_ratio = enter_ratio
        self.exit_ratio = exit_ratio
        self.samples: deque[tuple[float, dict[str, float]]] = deque()
        self.active_emotion: str | None = None
        self.active_cue: str | None = None

    def update(self, cues: dict[str, float], timestamp: float) -> dict[str, Any]:
        if not math.isfinite(timestamp) or any(
            cue not in self._RULES or not math.isfinite(score) or not 0.0 <= score <= 1.0
            for cue, score in cues.items()
        ):
            raise ValueError("behavior_sample_invalid")
        if self.samples and timestamp < self.samples[-1][0]:
            raise ValueError("behavior_timestamp_not_monotonic")

        self.samples.append((timestamp, dict(cues)))
        cutoff = timestamp - max(rule[1] for rule in self._RULES.values())
        while self.samples and self.samples[0][0] < cutoff:
            self.samples.popleft()

        candidates: list[tuple[float, str, str, float]] = []
        current_ratio = 0.0
        for cue, (emotion, window, minimum_span, min_samples) in self._RULES.items():
            window_samples = [sample for sample in self.samples if sample[0] >= timestamp - window]
            span = window_samples[-1][0] - window_samples[0][0]
            matches = [sample_cues.get(cue, 0.0) for _, sample_cues in window_samples]
            ratio = sum(score >= 0.6 for score in matches) / len(matches)
            if cue == self.active_cue:
                current_ratio = ratio
            if len(window_samples) >= min_samples and span >= minimum_span and ratio >= self.enter_ratio:
                scores = [score for score in matches if score >= 0.6]
                candidates.append((ratio, emotion, cue, sum(scores) / len(scores)))

        if self.active_cue is not None and current_ratio < self.exit_ratio:
            self.active_emotion = None
            self.active_cue = None

        candidates.sort(reverse=True)
        if candidates:
            strongest_ratio = candidates[0][0]
            strongest = [candidate for candidate in candidates if candidate[0] == strongest_ratio]
            emotions = {candidate[1] for candidate in strongest}
            selected = max(strongest, key=lambda candidate: (candidate[3], candidate[2]))
        else:
            emotions = set()
            selected = None
        if selected is not None and len(emotions) == 1:
            stability_ratio, self.active_emotion, self.active_cue, match_score = selected
        else:
            match_score = 0.0
            stability_ratio = current_ratio

        return {
            "active_emotion": self.active_emotion,
            "active_cue": self.active_cue,
            "match_score": match_score,
            "stability_ratio": stability_ratio,
            "observed_cues": sorted(cues),
        }


class RecentFaceAnchor:
    """遮挡期间短暂保留最近可靠人脸，仅供动作线索定位。"""

    def __init__(self, *, max_age_seconds: float = FACE_ANCHOR_MAX_AGE_SECONDS) -> None:
        if not math.isfinite(max_age_seconds) or max_age_seconds <= 0.0:
            raise ValueError("face_anchor_config_invalid")
        self.max_age_seconds = max_age_seconds
        self._face: np.ndarray | None = None
        self._observed_at = -math.inf
        self._last_timestamp = -math.inf

    def update(
        self,
        face: np.ndarray | None,
        timestamp: float,
        min_face_size: float,
    ) -> np.ndarray | None:
        if (
            not math.isfinite(timestamp)
            or timestamp < self._last_timestamp
            or not math.isfinite(min_face_size)
            or min_face_size <= 0.0
        ):
            raise ValueError("face_anchor_sample_invalid")
        self._last_timestamp = timestamp
        if (
            face is not None
            and len(face) >= 8
            and np.isfinite(face[:8]).all()
            and min(float(face[2]), float(face[3])) >= min_face_size
        ):
            self._face = face.copy()
            self._observed_at = timestamp
        if self._face is not None and timestamp - self._observed_at <= self.max_age_seconds:
            return self._face
        return None


def behavior_cues_from_observation(
    gesture_scores: dict[str, float],
    hand_landmarks: list[np.ndarray],
    pose_landmarks: np.ndarray | None,
    face: np.ndarray | None,
    frame_size: tuple[int, int],
) -> dict[str, float]:
    """把 MediaPipe 输出映射成静态强动作线索。"""
    cues: dict[str, float] = {}
    for category, cue in (("Thumb_Up", "thumb_up"), ("Closed_Fist", "closed_fist")):
        score = gesture_scores.get(category, 0.0)
        if math.isfinite(score) and score >= 0.6:
            cues[cue] = float(score)

    if face is None or pose_landmarks is None or pose_landmarks.shape != (33, 2):
        return cues
    if len(face) < 8 or not np.isfinite(face[:8]).all() or not np.isfinite(pose_landmarks).all():
        return cues

    shoulder_width = abs(float(pose_landmarks[12, 0] - pose_landmarks[11, 0]))
    shoulder_y = float((pose_landmarks[11, 1] + pose_landmarks[12, 1]) / 2.0)
    head_gap = shoulder_y - float(pose_landmarks[0, 1])
    head_down = shoulder_width > 1e-3 and 0.0 <= head_gap / shoulder_width <= 0.65
    if not head_down:
        return cues

    frame_width, frame_height = frame_size
    if frame_width <= 0 or frame_height <= 0 or float(face[2]) <= 0.0:
        return cues
    eyes = np.asarray(face[4:8], dtype=np.float32).reshape(2, 2)
    eyes /= np.array([frame_width, frame_height], dtype=np.float32)
    near_eye_distance = 0.3 * float(face[2]) / frame_width
    near_eye_fingertips = 0
    face_left = float(face[0]) / frame_width
    face_top = float(face[1]) / frame_height
    face_width = float(face[2]) / frame_width
    face_height = float(face[3]) / frame_height
    upper_face_left = face_left - 0.12 * face_width
    upper_face_right = face_left + 1.12 * face_width
    upper_face_top = face_top - 0.15 * face_height
    upper_face_bottom = face_top + 0.72 * face_height
    hand_covers_upper_face = False
    for hand in hand_landmarks:
        if hand.shape != (21, 2) or not np.isfinite(hand).all():
            continue
        fingertips = hand[[4, 8, 12, 16, 20]]
        near_eye_fingertips += sum(
            min(float(np.linalg.norm(fingertip - eye)) for eye in eyes) <= near_eye_distance
            for fingertip in fingertips
        )
        landmarks_over_upper_face = np.logical_and.reduce(
            (
                hand[:, 0] >= upper_face_left,
                hand[:, 0] <= upper_face_right,
                hand[:, 1] >= upper_face_top,
                hand[:, 1] <= upper_face_bottom,
            )
        ).sum()
        hand_covers_upper_face = hand_covers_upper_face or (
            landmarks_over_upper_face >= FACE_COVERAGE_MIN_LANDMARKS
        )
    if near_eye_fingertips >= 3 or hand_covers_upper_face:
        cues["cover_face_head_down"] = 0.95
    elif near_eye_fingertips:
        cues["hand_near_eye_head_down"] = 0.9
    return cues


def is_closed_fist_geometry(hand: np.ndarray) -> bool:
    """当官方分类为 None 时，以折叠手指形状补足握拳轨迹。"""
    if hand.shape != (21, 2) or not np.isfinite(hand).all():
        return False
    palm_scale = float(np.linalg.norm(hand[0] - hand[9]))
    if palm_scale <= 1e-6:
        return False
    largest_finger_extent = max(
        float(np.linalg.norm(hand[fingertip] - hand[mcp])) / palm_scale
        for mcp, fingertip in ((5, 8), (9, 12), (13, 16), (17, 20))
    )
    return largest_finger_extent <= CLOSED_FIST_GEOMETRY_MAX_RATIO


def is_open_palm_geometry(hand: np.ndarray) -> bool:
    """补足官方 Open_Palm 标签短暂丢失的同一张开手。"""
    if hand.shape != (21, 2) or not np.isfinite(hand).all():
        return False
    palm_scale = float(np.linalg.norm(hand[0] - hand[9]))
    if palm_scale <= 1e-6:
        return False
    extended_fingers = sum(
        float(np.linalg.norm(hand[fingertip] - hand[mcp])) / palm_scale
        >= OPEN_PALM_GEOMETRY_MIN_FINGER_RATIO
        for mcp, fingertip in ((5, 8), (9, 12), (13, 16), (17, 20))
    )
    return extended_fingers >= OPEN_PALM_GEOMETRY_MIN_EXTENDED_FINGERS


class MotionCueTracker:
    """只从手势轨迹提取挥手、鼓掌与快速下落的视觉线索。"""

    def __init__(self) -> None:
        self._open_palm_samples: deque[tuple[int, float]] = deque()
        self._closed_fist_samples: deque[tuple[int, float]] = deque()
        self._recent_fist_anchors: dict[str, tuple[int, float]] = {}
        self._recent_hand_positions: deque[tuple[int, float, float]] = deque()
        self._recent_official_open_palm_ats: deque[int] = deque()
        self._clap_contact_ats: deque[int] = deque()
        self._clap_ready = False
        self._clap_open_at = -math.inf
        self._last_clap_pair_at = -math.inf
        self._last_clap_midpoint: tuple[float, float] | None = None
        self._last_clap_shoulder_width: float | None = None
        self._clap_converged_since = -math.inf
        self._clap_burst_fired = False
        self._last_clap_at = -math.inf
        self._last_wave_at = -math.inf
        self._last_fist_strike_at = -math.inf
        self._last_timestamp_ms = -1

    def update(
        self,
        open_palm_xs: list[float],
        closed_fist_ys: list[float],
        timestamp_ms: int,
        *,
        geometry_open_palm_xs: list[float] | None = None,
        hand_ys: dict[str, float] | None = None,
        fist_hand_ys: dict[str, float] | None = None,
        hand_positions: list[tuple[float, float]] | None = None,
        fist_hand_positions: list[tuple[float, float]] | None = None,
        clap_hand_positions: dict[str, tuple[float, float]] | None = None,
        shoulder_width: float | None = None,
    ) -> dict[str, float]:
        geometry_open_palm_xs = [] if geometry_open_palm_xs is None else geometry_open_palm_xs
        hand_ys = {} if hand_ys is None else hand_ys
        fist_hand_ys = {} if fist_hand_ys is None else fist_hand_ys
        hand_positions = [] if hand_positions is None else hand_positions
        fist_hand_positions = [] if fist_hand_positions is None else fist_hand_positions
        clap_hand_positions = {} if clap_hand_positions is None else clap_hand_positions
        if timestamp_ms < self._last_timestamp_ms or any(
            not math.isfinite(value) or not 0.0 <= value <= 1.0
            for value in (
                *open_palm_xs,
                *geometry_open_palm_xs,
                *closed_fist_ys,
                *hand_ys.values(),
                *fist_hand_ys.values(),
            )
        ) or any(
            len(position) != 2
            or any(not math.isfinite(value) or not 0.0 <= value <= 1.0 for value in position)
            for position in (*hand_positions, *fist_hand_positions)
        ) or not isinstance(clap_hand_positions, dict) or any(
            len(position) != 2
            or any(not math.isfinite(value) or not 0.0 <= value <= 1.0 for value in position)
            for position in clap_hand_positions.values()
        ) or (
            shoulder_width is not None
            and (not math.isfinite(shoulder_width) or shoulder_width <= 0.0)
        ):
            raise ValueError("motion_cue_sample_invalid")
        self._last_timestamp_ms = timestamp_ms
        cues: dict[str, float] = {}

        official_open_palm_x = open_palm_xs[0] if len(open_palm_xs) == 1 else None
        if official_open_palm_x is not None:
            self._recent_official_open_palm_ats.append(timestamp_ms)
        while (
            self._recent_official_open_palm_ats
            and self._recent_official_open_palm_ats[0]
            < timestamp_ms - OPEN_PALM_GEOMETRY_MAX_OFFICIAL_GAP_MS
        ):
            self._recent_official_open_palm_ats.popleft()
        geometry_open_palm_x = (
            geometry_open_palm_xs[0]
            if len(geometry_open_palm_xs) == 1
            and len(self._recent_official_open_palm_ats)
            >= OPEN_PALM_GEOMETRY_MIN_OFFICIAL_SAMPLES
            else None
        )
        open_palm_x = official_open_palm_x if official_open_palm_x is not None else geometry_open_palm_x
        if open_palm_x is not None:
            self._open_palm_samples.append((timestamp_ms, open_palm_x))
        while self._open_palm_samples and self._open_palm_samples[0][0] < timestamp_ms - 1000:
            self._open_palm_samples.popleft()
        if open_palm_x is not None and len(self._open_palm_samples) >= 5:
            timestamps, xs = zip(*self._open_palm_samples)
            deltas = np.diff(np.asarray(xs, dtype=np.float32))
            if (
                timestamps[-1] - timestamps[0] >= 600
                and max(xs) - min(xs) >= 0.15
                and np.any(deltas >= 0.025)
                and np.any(deltas <= -0.025)
            ):
                self._last_wave_at = timestamp_ms
        if timestamp_ms - self._last_wave_at <= 1000:
            cues["wave_open_palm"] = 0.9

        closed_fist_y = max(closed_fist_ys) if closed_fist_ys else None
        if closed_fist_y is not None:
            self._closed_fist_samples.append((timestamp_ms, closed_fist_y))
        while self._closed_fist_samples and self._closed_fist_samples[0][0] < timestamp_ms - 500:
            self._closed_fist_samples.popleft()
        if closed_fist_y is not None:
            previous_y = min(y for _, y in self._closed_fist_samples)
            if closed_fist_y >= 0.65 and closed_fist_y - previous_y >= 0.18:
                self._last_fist_strike_at = timestamp_ms
        for hand_name, fist_y in fist_hand_ys.items():
            if fist_y <= 0.5:
                self._recent_fist_anchors[hand_name] = (timestamp_ms, fist_y)
        for hand_name, (anchor_at, anchor_y) in list(self._recent_fist_anchors.items()):
            if timestamp_ms - anchor_at > 500:
                del self._recent_fist_anchors[hand_name]
                continue
            hand_y = hand_ys.get(hand_name)
            if (
                hand_y is not None
                and timestamp_ms > anchor_at
                and hand_y >= 0.65
                and hand_y - anchor_y >= 0.18
            ):
                self._last_fist_strike_at = timestamp_ms
                del self._recent_fist_anchors[hand_name]
        while self._recent_hand_positions and self._recent_hand_positions[0][0] < timestamp_ms - 500:
            self._recent_hand_positions.popleft()
        for fist_x, fist_y in fist_hand_positions:
            if fist_y < 0.65:
                continue
            if any(
                timestamp_ms > anchor_at
                and abs(fist_x - anchor_x) <= FIST_HAND_CONTINUITY_MAX_X_DELTA
                and fist_y - anchor_y >= 0.18
                for anchor_at, anchor_x, anchor_y in self._recent_hand_positions
            ):
                self._last_fist_strike_at = timestamp_ms
                break
        self._recent_hand_positions.extend(
            (timestamp_ms, hand_x, hand_y) for hand_x, hand_y in hand_positions
        )
        if timestamp_ms - self._last_fist_strike_at <= 1000:
            cues["rapid_downward_fist_lower_frame"] = 0.95

        # ponytail: 2D hand-gap trajectory; replace only if fixed-scene replay misses clapping.
        clap_converged: bool | None = None
        if len(clap_hand_positions) == 2 and shoulder_width is not None:
            left_hand, right_hand = clap_hand_positions.values()
            hand_gap = float(np.linalg.norm(np.subtract(left_hand, right_hand))) / shoulder_width
            self._last_clap_pair_at = timestamp_ms
            self._last_clap_midpoint = tuple(np.mean((left_hand, right_hand), axis=0))
            self._last_clap_shoulder_width = shoulder_width
            clap_converged = hand_gap <= CLAP_CONVERGED_SHOULDER_RATIO
            if hand_gap >= CLAP_OPEN_SHOULDER_RATIO:
                self._clap_ready = True
                self._clap_open_at = timestamp_ms
                self._clap_converged_since = -math.inf
                self._clap_burst_fired = False
            elif hand_gap <= CLAP_CLOSE_SHOULDER_RATIO:
                if self._clap_ready and timestamp_ms - self._clap_open_at <= CLAP_CONTACT_WINDOW_MS:
                    self._clap_contact_ats.append(timestamp_ms)
                    if self._clap_converged_since == -math.inf:
                        self._clap_converged_since = timestamp_ms
                self._clap_ready = False
        elif len(clap_hand_positions) == 1:
            lone_hand = next(iter(clap_hand_positions.values()))
            lone_near_midpoint = (
                self._last_clap_midpoint is not None
                and self._last_clap_shoulder_width is not None
                and float(np.linalg.norm(np.subtract(lone_hand, self._last_clap_midpoint)))
                / self._last_clap_shoulder_width
                <= CLAP_OCCLUSION_MIDPOINT_SHOULDER_RATIO
            )
            clap_converged = lone_near_midpoint
            if self._clap_ready:
                if (
                    timestamp_ms - self._last_clap_pair_at <= CLAP_CONTACT_WINDOW_MS
                    and lone_near_midpoint
                ):
                    self._clap_contact_ats.append(timestamp_ms)
                    self._clap_ready = False
                    if self._clap_converged_since == -math.inf:
                        self._clap_converged_since = timestamp_ms
                elif timestamp_ms - self._last_clap_pair_at > CLAP_CONTACT_WINDOW_MS:
                    self._clap_contact_ats.clear()
                    self._clap_ready = False
        # 完全丢手时既无收敛证据也无反证：收敛期保持，但不推进拍合计数。
        if clap_converged is False:
            self._clap_converged_since = -math.inf
        while (
            self._clap_contact_ats
            and self._clap_contact_ats[0] < timestamp_ms - CLAP_CONTACT_WINDOW_MS
        ):
            self._clap_contact_ats.popleft()
        if len(self._clap_contact_ats) >= CLAP_CONTACTS_REQUIRED:
            self._last_clap_at = timestamp_ms
            self._clap_contact_ats.clear()
            self._clap_burst_fired = True
        elif (
            clap_converged
            and not self._clap_burst_fired
            and self._clap_converged_since > -math.inf
            and timestamp_ms - self._clap_converged_since >= CLAP_BURST_SUSTAIN_MS
        ):
            # 连续拍合时两掌重叠、MediaPipe 只剩一只手：合并单手在中点附近持续存在即视为连续鼓掌。
            self._last_clap_at = timestamp_ms
            self._clap_contact_ats.clear()
            self._clap_burst_fired = True
        if timestamp_ms - self._last_clap_at <= 1000:
            cues["clap_two_hands"] = 0.9

        return cues


class MediaPipeBehaviorModel:
    """MediaPipe 官方手势与姿态模型的薄封装。"""

    def __init__(self, gesture_model: Path, pose_model: Path) -> None:
        self._mp = None
        self._gesture = None
        self._pose = None
        self._motion = MotionCueTracker()
        self.last_hand_landmarks: list[np.ndarray] = []
        self.last_hand_labels: list[str] = []
        try:
            import mediapipe as mp
            from mediapipe.tasks.python import vision

            self._mp = mp
            self._gesture = vision.GestureRecognizer.create_from_options(
                vision.GestureRecognizerOptions(
                    base_options=mp.tasks.BaseOptions(model_asset_path=str(gesture_model)),
                    running_mode=vision.RunningMode.VIDEO,
                    num_hands=2,
                )
            )
            self._pose = vision.PoseLandmarker.create_from_options(
                vision.PoseLandmarkerOptions(
                    base_options=mp.tasks.BaseOptions(model_asset_path=str(pose_model)),
                    running_mode=vision.RunningMode.VIDEO,
                    num_poses=1,
                )
            )
        except Exception as error:
            if self._gesture is not None:
                self._gesture.close()
            raise EmotionDemoError("emotion_behavior_model_init_failed") from error

    def infer(
        self,
        frame: np.ndarray,
        face: np.ndarray | None,
        timestamp_ms: int,
    ) -> dict[str, float]:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        try:
            gesture_result = self._gesture.recognize_for_video(image, timestamp_ms)
            pose_result = self._pose.detect_for_video(image, timestamp_ms)
        except (RuntimeError, ValueError) as error:
            raise EmotionDemoError("emotion_behavior_inference_failed") from error
        hands = [
            np.array([(landmark.x, landmark.y) for landmark in hand], dtype=np.float32)
            for hand in gesture_result.hand_landmarks
        ]
        gesture_scores: dict[str, float] = {}
        open_palm_xs: list[float] = []
        geometry_open_palm_xs: list[float] = []
        closed_fist_ys: list[float] = []
        hand_ys: dict[str, float] = {}
        fist_hand_ys: dict[str, float] = {}
        hand_positions: list[tuple[float, float]] = []
        clap_hand_positions: dict[str, tuple[float, float]] = {}
        fist_hand_positions: list[tuple[float, float]] = []
        hand_labels: list[str] = []
        for hand_index, hand in enumerate(hands):
            categories = (
                gesture_result.gestures[hand_index]
                if hand_index < len(gesture_result.gestures)
                else []
            )
            top_category = "None"
            top_score = 0.0
            official_open_palm = False
            official_closed_fist = False
            for category in categories:
                gesture_scores[category.category_name] = max(
                    gesture_scores.get(category.category_name, 0.0),
                    float(category.score),
                )
                if category.score > top_score:
                    top_category = category.category_name
                    top_score = float(category.score)
                official_open_palm = official_open_palm or (
                    category.category_name == "Open_Palm" and category.score >= 0.6
                )
                official_closed_fist = official_closed_fist or (
                    category.category_name == "Closed_Fist" and category.score >= 0.6
                )
            geometry_open_palm = top_category == "None" and is_open_palm_geometry(hand)
            geometry_closed_fist = top_category == "None" and is_closed_fist_geometry(hand)
            hand_name = (
                gesture_result.handedness[hand_index][0].category_name
                if hand_index < len(gesture_result.handedness) and gesture_result.handedness[hand_index]
                else f"hand_{hand_index}"
            )
            hand_y = float(np.mean(hand[[0, 5, 9, 13, 17], 1]))
            hand_x = float(hand[0, 0])
            in_motion_frame = (
                math.isfinite(hand_x)
                and math.isfinite(hand_y)
                and 0.0 <= hand_x <= 1.0
                and 0.0 <= hand_y <= 1.0
            )
            if official_open_palm and 0.0 <= hand_x <= 1.0:
                open_palm_xs.append(hand_x)
            elif geometry_open_palm and 0.0 <= hand_x <= 1.0:
                geometry_open_palm_xs.append(hand_x)
            if in_motion_frame:
                hand_ys.setdefault(hand_name, hand_y)
                hand_positions.append((hand_x, hand_y))
                if hand_name in {"Left", "Right"}:
                    clap_hand_positions.setdefault(hand_name, (hand_x, hand_y))
            if (official_closed_fist or geometry_closed_fist) and in_motion_frame:
                closed_fist_ys.append(hand_y)
                fist_hand_ys[hand_name] = hand_y
                fist_hand_positions.append((hand_x, hand_y))
            hand_labels.append(
                "Closed_Fist" if official_closed_fist else "fist_geometry" if geometry_closed_fist
                else "open_palm_geometry" if geometry_open_palm else top_category
            )
        self.last_hand_landmarks = hands
        self.last_hand_labels = hand_labels
        pose = None
        if pose_result.pose_landmarks:
            pose = np.array(
                [(landmark.x, landmark.y) for landmark in pose_result.pose_landmarks[0]],
                dtype=np.float32,
            )
        shoulder_width = None
        if pose is not None and pose.shape == (33, 2) and np.isfinite(pose).all():
            candidate_shoulder_width = float(np.linalg.norm(pose[12] - pose[11]))
            if candidate_shoulder_width > 1e-3:
                shoulder_width = candidate_shoulder_width
        height, width = frame.shape[:2]
        cues = behavior_cues_from_observation(gesture_scores, hands, pose, face, (width, height))
        cues.update(
            self._motion.update(
                open_palm_xs,
                closed_fist_ys,
                timestamp_ms,
                geometry_open_palm_xs=geometry_open_palm_xs,
                hand_ys=hand_ys,
                fist_hand_ys=fist_hand_ys,
                hand_positions=hand_positions,
                fist_hand_positions=fist_hand_positions,
                clap_hand_positions=clap_hand_positions,
                shoulder_width=shoulder_width,
            )
        )
        return cues

    def close(self) -> None:
        if self._gesture is not None:
            self._gesture.close()
        if self._pose is not None:
            self._pose.close()


class EmotionEvidenceFusion:
    """稳定面部结果优先；没有稳定面部结果时才使用强动作。"""

    def __init__(
        self,
        *,
        cooldown_seconds: float = 10.0,
        angry_rearm_seconds: float = ANGRY_REARM_SECONDS,
    ) -> None:
        if not math.isfinite(cooldown_seconds) or cooldown_seconds < 0.0:
            raise ValueError("fusion_cooldown_invalid")
        if not math.isfinite(angry_rearm_seconds) or angry_rearm_seconds < 0.0:
            raise ValueError("fusion_angry_rearm_invalid")
        self.cooldown_seconds = cooldown_seconds
        self.angry_rearm_seconds = angry_rearm_seconds
        self.active_emotion: str | None = None
        self.inference_level: str | None = None
        self.evidence_source: str | None = None
        self.behavior_cues: list[str] = []
        self._happy_motion_opening_emitted = False
        self.last_event_at = -math.inf
        self._pending_angry: dict[str, Any] | None = None
        self._clap_suppresses_angry_until = -math.inf
        self._angry_hold = False
        self._angry_idle_since: float | None = None

    def _angry_cues_present(self, behavior_status: dict[str, Any]) -> bool:
        if behavior_status.get("active_emotion") == "angry":
            return True
        observed = behavior_status.get("observed_cues") or []
        return any(cue in ANGRY_BEHAVIOR_CUES for cue in observed)

    def _refresh_angry_rearm(
        self, behavior_status: dict[str, Any], timestamp: float
    ) -> None:
        if not self._angry_hold:
            return
        if self._angry_cues_present(behavior_status):
            self._angry_idle_since = None
            return
        if self._angry_idle_since is None:
            self._angry_idle_since = timestamp
            return
        if timestamp - self._angry_idle_since >= self.angry_rearm_seconds:
            self._angry_hold = False
            self._angry_idle_since = None
            if self.active_emotion == "angry":
                self.active_emotion = None

    def _emit(
        self,
        emotion: str,
        match_score: float,
        stability_ratio: float,
        inference_level: str,
        evidence_source: str,
        behavior_cues: list[str],
        timestamp: float,
        *,
        allow_evidence_upgrade: bool = False,
    ) -> dict[str, Any] | None:
        changed = emotion != self.active_emotion
        self.inference_level = inference_level
        self.evidence_source = evidence_source
        self.behavior_cues = list(behavior_cues)
        if not changed and not allow_evidence_upgrade:
            return None
        self.active_emotion = emotion
        if (
            timestamp - self.last_event_at < self.cooldown_seconds
            and not allow_evidence_upgrade
        ):
            return None
        self.last_event_at = timestamp
        if emotion == "angry":
            self._angry_hold = True
            self._angry_idle_since = None
        else:
            self._angry_hold = False
            self._angry_idle_since = None
        if emotion == "happy" and any(
            cue in MOTION_BEHAVIOR_CUES for cue in behavior_cues
        ):
            self._happy_motion_opening_emitted = True
        elif emotion != "happy":
            self._happy_motion_opening_emitted = False
        return make_strategy_event(
            emotion,
            match_score,
            stability_ratio,
            inference_level=inference_level,
            evidence_source=evidence_source,
            behavior_cues=behavior_cues,
        )

    def update(
        self,
        face_status: dict[str, Any],
        behavior_status: dict[str, Any],
        timestamp: float,
    ) -> dict[str, Any] | None:
        face_emotion = face_status["active_emotion"]
        behavior_emotion = behavior_status["active_emotion"]
        active_cue = behavior_status.get("active_cue")
        if self.active_emotion != "happy":
            self._happy_motion_opening_emitted = False
        new_motion_cue = (
            active_cue in MOTION_BEHAVIOR_CUES
            and not self._happy_motion_opening_emitted
        )
        self._refresh_angry_rearm(behavior_status, timestamp)
        clap_observed = "clap_two_hands" in behavior_status["observed_cues"]
        if clap_observed:
            self._pending_angry = None
            self._clap_suppresses_angry_until = (
                timestamp + FIST_CLAP_DISAMBIGUATION_SECONDS
            )
        if (
            behavior_emotion == "happy"
            and active_cue in MOTION_BEHAVIOR_CUES
            and face_status.get("observed_emotion") == "happy"
        ):
            self._pending_angry = None
            return self._emit(
                "happy",
                (
                    face_status["match_score"]
                    if face_emotion == "happy"
                    else face_status["observed_match_score"]
                ),
                behavior_status["stability_ratio"],
                "stable_face" if face_emotion == "happy" else "action_face",
                "face_and_behavior",
                [active_cue],
                timestamp,
                allow_evidence_upgrade=new_motion_cue,
            )
        if face_emotion is not None:
            self._pending_angry = None
            same_behavior = behavior_emotion == face_emotion
            return self._emit(
                face_emotion,
                face_status["match_score"],
                face_status["stability_ratio"],
                "stable_face",
                "face_and_behavior" if same_behavior else "face",
                behavior_status["observed_cues"] if same_behavior else [],
                timestamp,
                allow_evidence_upgrade=same_behavior and new_motion_cue,
            )
        if behavior_emotion == "angry":
            if self._angry_hold:
                self._pending_angry = None
            elif not clap_observed and timestamp >= self._clap_suppresses_angry_until:
                if self._pending_angry is None:
                    self._pending_angry = {
                        "queued_at": timestamp,
                        "match_score": behavior_status["match_score"],
                        "stability_ratio": behavior_status["stability_ratio"],
                        "behavior_cues": [behavior_status["active_cue"]],
                    }
        elif behavior_emotion is not None:
            self._pending_angry = None
            return self._emit(
                behavior_emotion,
                behavior_status["match_score"],
                behavior_status["stability_ratio"],
                "possible",
                "behavior",
                [behavior_status["active_cue"]],
                timestamp,
            )

        if (
            self._pending_angry is not None
            and timestamp - self._pending_angry["queued_at"]
            >= FIST_CLAP_DISAMBIGUATION_SECONDS
        ):
            pending = self._pending_angry
            self._pending_angry = None
            return self._emit(
                "angry",
                pending["match_score"],
                pending["stability_ratio"],
                "possible",
                "behavior",
                pending["behavior_cues"],
                timestamp,
            )

        if (
            self._pending_angry is None
            and behavior_emotion is None
            and not self._angry_hold
            and timestamp - self.last_event_at >= self.cooldown_seconds
        ):
            self.active_emotion = None
            self.inference_level = None
            self.evidence_source = None
            self.behavior_cues = []
            self._happy_motion_opening_emitted = False
        return None


class FacialExpressionModel:
    """OpenCV Zoo Progressive Teacher 的官方预处理和七分类。"""

    _TARGET_LANDMARKS = np.array(
        [
            [38.2946, 51.6963],
            [73.5318, 51.5014],
            [56.0252, 71.7366],
            [41.5493, 92.3655],
            [70.7299, 92.2041],
        ],
        dtype=np.float32,
    )

    def __init__(self, model_path: Path) -> None:
        self.net = cv2.dnn.readNet(str(model_path))

    @staticmethod
    def _alignment_transform(landmarks: np.ndarray) -> np.ndarray:
        x = FacialExpressionModel._TARGET_LANDMARKS[:, 0:1]
        y = FacialExpressionModel._TARGET_LANDMARKS[:, 1:2]
        zeros, ones = np.zeros_like(x), np.ones_like(x)
        matrix = np.vstack(
            (
                np.hstack((x, y, ones, zeros)),
                np.hstack((y, -x, zeros, ones)),
            )
        )
        target = np.vstack((landmarks[:, 0:1], landmarks[:, 1:2]))
        sc, ss, tx, ty = np.linalg.lstsq(matrix, target, rcond=-1)[0].ravel()
        if sc * sc + ss * ss < 1e-8:
            raise EmotionFaceAlignmentError("emotion_face_alignment_failed")
        inverse = np.array([[sc, -ss, 0.0], [ss, sc, 0.0], [tx, ty, 1.0]])
        try:
            forward = np.linalg.inv(inverse)
        except np.linalg.LinAlgError as error:
            raise EmotionFaceAlignmentError("emotion_face_alignment_failed") from error
        forward[:, 2] = (0.0, 0.0, 1.0)
        return forward[:, :2].T

    def infer(self, frame: np.ndarray, face: np.ndarray) -> tuple[str, float, np.ndarray]:
        landmarks = face[4:14].reshape(5, 2).astype(np.float32)
        transform = self._alignment_transform(landmarks)
        aligned = cv2.warpAffine(frame, transform, (112, 112))
        rgb = cv2.cvtColor(aligned, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        normalized = (rgb - 0.5) / 0.5
        blob = cv2.dnn.blobFromImage(normalized)
        self.net.setInput(blob, "data")
        logits = np.asarray(self.net.forward("label"), dtype=np.float32).reshape(-1)
        if logits.size != len(FER_LABELS) or not np.isfinite(logits).all():
            raise EmotionDemoError("emotion_model_output_invalid")
        probabilities = np.exp(logits - logits.max())
        probabilities /= probabilities.sum()
        index = int(np.argmax(probabilities))
        return FER_LABELS[index], float(probabilities[index]), probabilities


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_model(path: Path, expected_sha256: str) -> None:
    if not path.is_file() or path.stat().st_size > 64 * 1024 * 1024:
        raise EmotionDemoError(f"emotion_model_missing:{path}")
    if _sha256(path) != expected_sha256:
        raise EmotionDemoError(f"emotion_model_hash_mismatch:{path}")


def _source(value: str) -> str | int:
    path = Path(value).expanduser()
    if path.exists():
        return str(path)
    if value.isdecimal():
        return int(value)
    raise EmotionDemoError(f"emotion_input_missing:{value}")


def record_directory_for_input(
    source: str | int,
    record_camera: bool,
    requested_directory: Path | None,
) -> Path | None:
    """仅在本次明确确认时录制相机；本地回放不重复保存。"""
    if requested_directory is not None:
        return requested_directory
    return DEFAULT_CAMERA_RECORD_DIRECTORY if isinstance(source, int) and record_camera else None


def next_recording_path(directory: Path, timestamp: str) -> Path:
    """为一次有界录制生成不覆盖旧素材的 MP4 路径。"""
    return directory / f"camera_{timestamp}_{uuid.uuid4().hex[:8]}.mp4"


def _screen_size() -> tuple[int, int]:
    """Return the current monitor size; fall back to 1920x1080 without a display."""
    try:
        import tkinter as tk
    except ImportError:
        return (FALLBACK_SCREEN_WIDTH, FALLBACK_SCREEN_HEIGHT)
    root = None
    try:
        root = tk.Tk()
        root.withdraw()
        width = int(root.winfo_screenwidth())
        height = int(root.winfo_screenheight())
        if width > 0 and height > 0:
            return (width, height)
    except Exception:
        pass
    finally:
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass
    return (FALLBACK_SCREEN_WIDTH, FALLBACK_SCREEN_HEIGHT)


def display_max_size(window_width: int, window_height: int) -> tuple[int, int]:
    """Return the preview box: explicit pixels, or about 90% of the current screen."""
    if window_width > 0 and window_height > 0:
        return (window_width, window_height)
    screen_width, screen_height = _screen_size()
    return (
        max(1, round(screen_width * DISPLAY_SCREEN_FILL)),
        max(1, round(screen_height * DISPLAY_SCREEN_FILL)),
    )


def display_frame_size(
    frame_width: int,
    frame_height: int,
    max_width: int,
    max_height: int,
) -> tuple[int, int]:
    """Scale a camera frame to fill max_width x max_height while keeping aspect ratio."""
    if min(frame_width, frame_height, max_width, max_height) <= 0:
        raise ValueError("display frame size must be positive")
    scale = min(max_width / frame_width, max_height / frame_height)
    return (
        max(1, round(frame_width * scale)),
        max(1, round(frame_height * scale)),
    )


def resized_display_frame(frame: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    """Resize only the preview copy; recording and inference keep the native frame."""
    height, width = frame.shape[:2]
    if (width, height) == size:
        return frame
    return cv2.resize(frame, size, interpolation=cv2.INTER_LINEAR)


class TkPreviewWindow:
    """可拖拽的预览窗口；尺寸直接来自 Tk 的内容区，不依赖 HighGUI 图像矩形。"""

    def __init__(self, title: str, size: tuple[int, int]) -> None:
        try:
            import tkinter as tk
        except ImportError as error:
            raise EmotionDemoError("emotion_preview_ui_unavailable") from error
        self._tk = tk
        self._closed = False
        self._size = size
        self._image: Any = None
        try:
            self._root = tk.Tk()
            self._root.title(title)
            self._label = tk.Label(self._root, background="black")
            self._label.pack(fill=tk.BOTH, expand=True)
            self._label.bind("<Configure>", self._on_resize)
            self._root.bind("<Escape>", self._close)
            self._root.bind("<KeyPress-q>", self._close)
            self._root.protocol("WM_DELETE_WINDOW", self._close)
            self._root.geometry(f"{size[0]}x{size[1]}")
        except tk.TclError as error:
            raise EmotionDemoError("emotion_preview_ui_unavailable") from error

    def _on_resize(self, event: Any) -> None:
        if event.width > 0 and event.height > 0:
            self._size = (int(event.width), int(event.height))

    def _close(self, _event: Any = None) -> None:
        self._closed = True

    def show(self, frame: np.ndarray) -> bool:
        if self._closed:
            return False
        encoded_ok, encoded = cv2.imencode(".ppm", resized_display_frame(frame, self._size))
        if not encoded_ok:
            raise EmotionDemoError("emotion_preview_encode_failed")
        try:
            self._image = self._tk.PhotoImage(data=encoded.tobytes(), format="PPM")
            self._label.configure(image=self._image)
            self._root.update_idletasks()
            self._root.update()
        except self._tk.TclError:
            self._closed = True
        return not self._closed

    def close(self) -> None:
        self._closed = True
        try:
            self._root.destroy()
        except self._tk.TclError:
            pass


def draw_mediapipe_hands(
    frame: np.ndarray,
    hands: list[np.ndarray],
    labels: list[str],
) -> np.ndarray:
    """在本地展示和显式标注导出中画出 MediaPipe 手部检测。"""
    output = frame.copy()
    height, width = output.shape[:2]
    for index, hand in enumerate(hands):
        if hand.shape != (21, 2) or not np.isfinite(hand).all():
            continue
        label = labels[index] if index < len(labels) else "hand"
        color = (0, 215, 255) if label == "fist_geometry" else (0, 255, 0)
        points = np.rint(hand * np.array([width, height])).astype(np.int32)
        for start, end in HAND_CONNECTIONS:
            cv2.line(output, tuple(points[start]), tuple(points[end]), color, 2, cv2.LINE_AA)
        for point in points:
            cv2.circle(output, tuple(point), 3, color, -1, cv2.LINE_AA)
        cv2.putText(
            output,
            f"mp:{label}",
            tuple(points[0] + np.array((8, -8))),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            color,
            2,
            cv2.LINE_AA,
        )
    return output


def _display_face_box(
    face: np.ndarray,
    frame_shape: tuple[int, ...],
    scale: float,
) -> tuple[int, int, int, int]:
    """Return a clipped, display-only face box around the raw detector box."""
    if not math.isfinite(scale) or scale <= 0.0:
        raise ValueError("face box scale must be positive")
    frame_height, frame_width = frame_shape[:2]
    x, y, width, height = (float(value) for value in face[:4])
    display_width = width * scale
    display_height = height * scale
    x1 = round(x - (display_width - width) / 2.0)
    y1 = round(y - (display_height - height) / 2.0)
    x2 = round(x + width + (display_width - width) / 2.0)
    y2 = round(y + height + (display_height - height) / 2.0)
    x1 = max(0, min(frame_width - 1, x1))
    y1 = max(0, min(frame_height - 1, y1))
    x2 = max(x1 + 1, min(frame_width - 1, x2))
    y2 = max(y1 + 1, min(frame_height - 1, y2))
    return x1, y1, x2, y2


def _overlay(
    frame: np.ndarray,
    result: dict[str, Any],
    *,
    face_box_scale: float = DEFAULT_DISPLAY_FACE_BOX_SCALE,
) -> np.ndarray:
    output = draw_mediapipe_hands(
        frame,
        result.get("media_pipe_hands", []),
        result.get("media_pipe_hand_labels", []),
    )
    face = result.get("face")
    if face is not None:
        x1, y1, x2, y2 = _display_face_box(face, output.shape, face_box_scale)
        cv2.rectangle(output, (x1, y1), (x2, y2), (0, 255, 0), 2)
    face_status = result["face_status"]
    behavior_status = result["behavior_status"]
    fused = result["fused"]
    lines = [
        f"input={result['input_state']}",
        f"raw={result['raw_label']} score={result['raw_score']:.2f}",
        f"face={face_status['active_emotion'] or '-'} ratio={face_status['stability_ratio']:.2f}",
        f"behavior={behavior_status['active_cue'] or '-'}",
        f"active={fused['active_emotion'] or 'calm(default)'} source={fused['evidence_source'] or '-'}",
    ]
    if fused["active_emotion"] is not None:
        lines.append(f"strategy={STRATEGIES[fused['active_emotion']]['strategy_id']}")
    for index, line in enumerate(lines):
        cv2.putText(
            output,
            line,
            (16, 30 + index * 28),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (0, 0, 255),
            2,
            cv2.LINE_AA,
        )
    return output


def write_dashboard_record(stream: Any, payload: dict[str, Any]) -> Any:
    """Optional metadata sidecar must not stop detection or write to its strategy pipe."""
    if stream is None:
        return None
    try:
        if stream.tell() >= 8 * 1024 * 1024:
            raise OSError("dashboard log reached 8 MiB")
        stream.write(json.dumps(payload, ensure_ascii=False, allow_nan=False) + "\n")
        stream.flush()
        return stream
    except OSError as error:
        print(f"emotion_dashboard_log_disabled: {error}", file=sys.stderr, flush=True)
        try:
            stream.close()
        except OSError:
            pass
        return None


def dashboard_snapshot(result: dict[str, Any], source: str | int, source_time: float, min_score: float = 0.45) -> dict[str, Any]:
    fused = result["fused"]
    emotion = fused["active_emotion"]
    face_valid = result["input_state"] == "face_ok" and result.get("face_status", {}).get("observed_emotion") == emotion
    behavior = result.get("behavior_status", {})
    behavior_valid = behavior.get("active_emotion") == emotion and behavior.get("active_cue") in behavior.get("observed_cues", [])
    inference = fused["inference_level"] or ""
    if emotion is not None and not (face_valid or behavior_valid):
        emotion = None
    elif emotion is not None and not face_valid:
        inference = "possible"
    if emotion is None:
        emotion = "calm" if (result["input_state"] == "face_ok" and result["raw_label"] == "neutral" and result.get("raw_score", 0) >= min_score) else "unknown"
        inference = ""
    return {
        "schema_version": "emotion_snapshot_v1", "event_id": uuid.uuid4().hex,
        "source_run_id": RECORD_SOURCE_RUN_ID,
        "observed_at": datetime.now().astimezone().isoformat(timespec="milliseconds"),
        "source_kind": "camera" if isinstance(source, int) else "video",
        "source_seconds": round(source_time, 3), "emotion": emotion,
        "input_state": result["input_state"], "inference_level": inference,
    }


def run_demo(args: argparse.Namespace) -> int:
    _verify_model(YUNET_MODEL, YUNET_SHA256)
    _verify_model(FER_MODEL, FER_SHA256)
    _verify_model(GESTURE_MODEL, GESTURE_SHA256)
    _verify_model(POSE_MODEL, POSE_SHA256)
    source = _source(args.input)
    annotated_path: Path | None = getattr(args, "export_annotated", None)
    if annotated_path is not None and (annotated_path.exists() or annotated_path.is_symlink()):
        raise EmotionDemoError("emotion_annotated_output_exists")
    if args.record_camera and not isinstance(source, int):
        raise EmotionDemoError("emotion_record_camera_requires_device")
    capture = cv2.VideoCapture(source)
    if not capture.isOpened():
        raise EmotionDemoError("emotion_input_open_failed")

    detector = cv2.FaceDetectorYN.create(str(YUNET_MODEL), "", (320, 320), 0.8, 0.3, 5000)
    expression_model = FacialExpressionModel(FER_MODEL)
    try:
        behavior_model = MediaPipeBehaviorModel(GESTURE_MODEL, POSE_MODEL)
    except EmotionDemoError:
        capture.release()
        raise
    face_filter = TemporalEmotionFilter()
    behavior_filter = BehaviorCueFilter()
    fusion = EmotionEvidenceFusion()
    face_anchor = RecentFaceAnchor()
    source_fps = capture.get(cv2.CAP_PROP_FPS)
    source_fps = source_fps if math.isfinite(source_fps) and source_fps > 0 else 30.0
    record_directory = record_directory_for_input(source, args.record_camera, args.record_dir)
    recording_path: Path | None = None
    video_writer: cv2.VideoWriter | None = None
    annotated_writer: cv2.VideoWriter | None = None
    sample_interval = 1.0 / args.inference_fps
    next_sample_at = 0.0
    started_at = time.monotonic()
    frame_count = sample_count = event_count = 0
    continue_after_first_event = bool(getattr(args, "continue_after_first_event", False))
    last_result: dict[str, Any] | None = None
    last_behavior_timestamp_ms = -1
    preview_window: TkPreviewWindow | None = None
    dashboard_stream = None
    dashboard_path = getattr(args, "dashboard_log", None)
    next_dashboard_at = 0.0

    try:
        if dashboard_path is not None:
            dashboard_path.parent.mkdir(parents=True, exist_ok=True)
            dashboard_stream = dashboard_path.open("x", encoding="utf-8")
        while (
            continue_after_first_event and event_count > 0
        ) or time.monotonic() - started_at < args.max_seconds:
            ok, frame = capture.read()
            if not ok:
                break
            frame_count += 1
            if record_directory is not None:
                if video_writer is None:
                    record_directory.mkdir(parents=True, exist_ok=True)
                    recording_path = next_recording_path(
                        record_directory,
                        datetime.now().astimezone().strftime("%Y%m%dT%H%M%S"),
                    )
                    height, width = frame.shape[:2]
                    video_writer = cv2.VideoWriter(
                        str(recording_path),
                        cv2.VideoWriter_fourcc(*"mp4v"),
                        source_fps,
                        (width, height),
                    )
                    if not video_writer.isOpened():
                        video_writer.release()
                        video_writer = None
                        raise EmotionDemoError("emotion_video_writer_open_failed")
                video_writer.write(frame)
            source_time = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
            if isinstance(source, int) or not math.isfinite(source_time) or source_time <= 0.0:
                source_time = frame_count / source_fps if not isinstance(source, int) else time.monotonic() - started_at

            if source_time >= next_sample_at:
                height, width = frame.shape[:2]
                detector.setInputSize((width, height))
                _, faces = detector.detect(frame)
                face = None if faces is None else max(faces, key=lambda item: float(item[2] * item[3]))
                input_state = "no_face"
                raw_label: str | None = None
                raw_score = 0.0
                mapped_label: str | None = None
                if face is not None:
                    if min(float(face[2]), float(face[3])) < args.min_face_size:
                        input_state = "face_too_small"
                    else:
                        input_state = "face_ok"
                        try:
                            raw_label, raw_score, _ = expression_model.infer(frame, face)
                        except EmotionFaceAlignmentError:
                            input_state = "face_alignment_failed"
                        else:
                            mapped_label = map_face_emotion(
                                raw_label,
                                raw_score,
                                args.min_match_score,
                            )
                face_status, _ = face_filter.update(mapped_label, raw_score, source_time)
                timestamp_ms = max(last_behavior_timestamp_ms + 1, round(source_time * 1000.0))
                behavior_face = face_anchor.update(face, source_time, args.min_face_size)
                behavior_cues = behavior_model.infer(frame, behavior_face, timestamp_ms)
                last_behavior_timestamp_ms = timestamp_ms
                behavior_status = behavior_filter.update(behavior_cues, source_time)
                event = fusion.update(face_status, behavior_status, source_time)
                last_result = {
                    "face": face,
                    "media_pipe_hands": getattr(behavior_model, "last_hand_landmarks", []),
                    "media_pipe_hand_labels": getattr(behavior_model, "last_hand_labels", []),
                    "input_state": input_state,
                    "raw_label": raw_label,
                    "raw_score": raw_score,
                    "face_status": face_status,
                    "behavior_status": behavior_status,
                    "fused": {
                        "active_emotion": fusion.active_emotion,
                        "inference_level": fusion.inference_level,
                        "evidence_source": fusion.evidence_source,
                    },
                }
                if dashboard_stream is not None and source_time >= next_dashboard_at:
                    dashboard_stream = write_dashboard_record(dashboard_stream, dashboard_snapshot(last_result, source, source_time, args.min_match_score))
                    next_dashboard_at = source_time + 1.0
                sample_count += 1
                while next_sample_at <= source_time:
                    next_sample_at += sample_interval
                if event is not None:
                    if continue_after_first_event and event_count > 0:
                        event["reason"] = "emotion_transition"
                    event_count += 1
                    print(json.dumps(event, ensure_ascii=False, separators=(",", ":")), flush=True)
                    dashboard_stream = write_dashboard_record(dashboard_stream, {
                        **event, "source_kind": "camera" if isinstance(source, int) else "video",
                        "source_seconds": round(source_time, 3),
                    })

            annotated_frame = (
                _overlay(
                    frame,
                    last_result,
                    face_box_scale=getattr(
                        args,
                        "face_box_scale",
                        DEFAULT_DISPLAY_FACE_BOX_SCALE,
                    ),
                )
                if last_result is not None
                else frame
            )
            if annotated_path is not None:
                if annotated_writer is None:
                    annotated_path.parent.mkdir(parents=True, exist_ok=True)
                    height, width = frame.shape[:2]
                    annotated_writer = cv2.VideoWriter(
                        str(annotated_path),
                        cv2.VideoWriter_fourcc(*"mp4v"),
                        source_fps,
                        (width, height),
                    )
                    if not annotated_writer.isOpened():
                        annotated_writer.release()
                        annotated_writer = None
                        raise EmotionDemoError("emotion_video_writer_open_failed")
                annotated_writer.write(annotated_frame)

            if args.display:
                if preview_window is None:
                    frame_height, frame_width = annotated_frame.shape[:2]
                    max_width, max_height = display_max_size(
                        getattr(args, "window_width", 0),
                        getattr(args, "window_height", 0),
                    )
                    display_size = display_frame_size(
                        frame_width,
                        frame_height,
                        max_width,
                        max_height,
                    )
                    preview_window = TkPreviewWindow(DISPLAY_WINDOW_NAME, display_size)
                if not preview_window.show(annotated_frame):
                    break
                if not isinstance(source, int):
                    time.sleep(1.0 / source_fps)
    finally:
        if dashboard_stream is not None:
            dashboard_stream.close()
        behavior_model.close()
        capture.release()
        if video_writer is not None:
            video_writer.release()
        if annotated_writer is not None:
            annotated_writer.release()
        if preview_window is not None:
            preview_window.close()

    print(
        json.dumps(
            {
                "kind": "emotion_demo_summary",
                "frames": frame_count,
                "inference_samples": sample_count,
                "strategy_events": event_count,
                "last_raw_label": None if last_result is None else last_result["raw_label"],
                "last_behavior_cues": (
                    [] if last_result is None else last_result["behavior_status"]["observed_cues"]
                ),
                "recorded_video_path": None if recording_path is None else str(recording_path),
                "annotated_video_path": None if annotated_writer is None else str(annotated_path),
                "physical_actions_emitted": 0,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    return 0


def run_self_check() -> None:
    filter_ = TemporalEmotionFilter(
        window_seconds=2.5,
        minimum_span_seconds=2.0,
        min_samples=5,
        enter_ratio=0.7,
        exit_ratio=0.35,
        cooldown_seconds=10.0,
    )
    events = [
        filter_.update("happy", 0.9, timestamp)[1]
        for timestamp in (0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0)
    ]
    emitted = [event for event in events if event is not None]
    assert len(emitted) == 1
    assert emitted[0]["strategy"]["strategy_id"] == "SHARE_POSITIVE"

    for timestamp in (4.0, 4.5, 5.0, 5.5, 6.0, 6.5):
        filter_.update("neutral", 0.9, timestamp)
    assert filter_.active_emotion is None
    for label in ("neutral", "fearful", None):
        assert filter_.update(label, 0.9, 7.0)[1] is None
    assert all(filter_.update("sad", 0.9, timestamp)[1] is None for timestamp in (8.0, 8.5, 9.0, 9.5, 10.0))

    later_events = []
    for emotion, start in (("sad", 13.0), ("angry", 26.0)):
        for offset in (0.0, 0.5, 1.0, 1.5, 2.0):
            _, event = filter_.update(emotion, 0.9, start + offset)
            if event is not None:
                later_events.append(event)
        for offset in (3.0, 3.5, 4.0, 4.5, 5.0):
            filter_.update("neutral", 0.9, start + offset)
    assert [event["emotion"] for event in later_events] == ["sad", "angry"]
    assert [STRATEGIES[name]["strategy_id"] for name in ("happy", "sad", "angry")] == [
        "SHARE_POSITIVE",
        "EMPATHIZE_AND_INVITE",
        "DEESCALATE_AND_GIVE_SPACE",
    ]
    try:
        FacialExpressionModel._alignment_transform(np.zeros((5, 2), dtype=np.float32))
    except EmotionFaceAlignmentError:
        pass
    else:
        raise AssertionError("degenerate landmarks must not produce an active emotion")
    print("emotion_self_check=PASS")


def parse_arguments(arguments: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", help="本地视频路径；USB/UVC 相机使用设备编号，如 0")
    parser.add_argument("--display", action="store_true", help="显示 OpenCV 窗口，按 q 或 Esc 退出")
    parser.add_argument(
        "--window-width",
        type=int,
        default=0,
        help="预览最大宽度；0 表示按当前屏幕约 90% 自动放大实际画面，窗口随后可拖",
    )
    parser.add_argument(
        "--window-height",
        type=int,
        default=0,
        help="预览最大高度；0 表示按当前屏幕约 90% 自动放大实际画面，窗口随后可拖",
    )
    parser.add_argument(
        "--face-box-scale",
        type=float,
        default=DEFAULT_DISPLAY_FACE_BOX_SCALE,
        help="显示用人脸检测框相对原始检测框的缩放倍数",
    )
    parser.add_argument("--max-seconds", type=float, default=180.0)
    parser.add_argument(
        "--continue-after-first-event",
        action="store_true",
        help="首个策略事件后继续显示预览；用于由外层对话进程结束的相机会话",
    )
    parser.add_argument("--inference-fps", type=float, default=20.0)
    parser.add_argument("--min-face-size", type=float, default=80.0)
    parser.add_argument("--min-match-score", type=float, default=0.45)
    parser.add_argument(
        "--record-dir",
        type=Path,
        help="显式录像目录；本地视频或相机均可使用",
    )
    parser.add_argument(
        "--record-camera",
        action="store_true",
        help="确认保存本次 USB/UVC 相机会话到项目 vedio/；仅设备编号输入可用",
    )
    parser.add_argument(
        "--export-annotated",
        type=Path,
        help="显式导出带检测叠加信息的 MP4；本地视频回放默认不写文件",
    )
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument(
        "--dashboard-log", type=Path, default=os.environ.get("G1_EMOTION_DASHBOARD_LOG"),
        help="护理工作台状态和策略日志；每秒最多一条状态、8 MiB 上限，拒绝覆盖已有文件",
    )
    args = parser.parse_args(arguments)
    if args.self_check:
        return args
    if not args.input:
        parser.error("--input is required unless --self-check is used")
    if not (
        0.0 < args.max_seconds <= 600.0
        and 5.0 <= args.inference_fps <= 20.0
        and args.min_face_size > 0.0
        and 0.0 <= args.min_match_score <= 1.0
        and math.isfinite(args.face_box_scale)
        and args.face_box_scale > 0.0
    ):
        parser.error("invalid numeric option")
    if args.window_width < 0 or args.window_height < 0:
        parser.error("invalid numeric option")
    if (args.window_width == 0) != (args.window_height == 0):
        parser.error("--window-width and --window-height must both be 0 or both positive")
    return args


def main(arguments: list[str]) -> int:
    args = parse_arguments(arguments)
    if args.self_check:
        run_self_check()
        return 0
    try:
        return run_demo(args)
    except (EmotionDemoError, OSError, cv2.error) as error:
        print(json.dumps({"error_code": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 70


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
