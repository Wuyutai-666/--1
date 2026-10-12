"""用户行为画像的工业界常用权重公式。"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any


class BehaviorWeights:
    BASE = {
        "click": 1.0,
        "view_detail": 3.0,
        "favorite": 4.0,
        "add_cart": 6.0,
        "order": 15.0,
        "ignore": 0.0,
        "disinterest": -10.0,
    }
    HALF_LIFE_DAYS = 7.0
    ALIASES = {
        "detail_view": "view_detail",
        "cart_add": "add_cart",
        "dismiss": "ignore",
        "not_interested": "disinterest",
        "rating_positive": "rating",
        "rating_negative": "rating",
    }

    @classmethod
    def normalize_behavior(cls, behavior: str) -> str:
        return cls.ALIASES.get(behavior, behavior)

    @staticmethod
    def rating_weight(score: float) -> float:
        return (float(score) - 3.0) * 4.0

    @classmethod
    def event_contribution(
        cls,
        behavior: str,
        days_ago: float,
        *,
        score: float | None = None,
        dwell_sec: float = 0.0,
    ) -> float:
        behavior = cls.normalize_behavior(behavior)
        if behavior == "rating" and score is not None:
            base = cls.rating_weight(score)
        else:
            base = cls.BASE.get(behavior, 0.0)

        if behavior == "view_detail" and dwell_sec > 0:
            base *= min(float(dwell_sec) / 30.0, 3.0)

        decay = math.exp(
            -math.log(2)
            / cls.HALF_LIFE_DAYS
            * max(float(days_ago), 0.0)
        )
        return base * decay

    @classmethod
    def aggregate_tag_weights(
        cls,
        events: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        """按标签和行为聚合，再应用次数平滑。"""
        grouped: dict[
            tuple[str, str],
            list[dict[str, Any]],
        ] = defaultdict(list)

        for event in events:
            behavior = cls.normalize_behavior(
                str(event["event_type"])
            )
            for tag in event.get("tags", []):
                grouped[(tag, behavior)].append(event)

        weights: dict[str, dict[str, Any]] = {}
        for (tag, behavior), items in grouped.items():
            count = len(items)
            contributions = [
                cls.event_contribution(
                    behavior,
                    float(item["days_ago"]),
                    score=item.get("rating"),
                    dwell_sec=float(item.get("dwell_sec") or 0),
                )
                for item in items
            ]
            average_contribution = (
                sum(contributions) / count if count else 0.0
            )
            contribution = average_contribution * math.log2(1 + count)
            record = weights.setdefault(
                tag,
                {
                    "raw_weight": 0.0,
                    "event_count": 0,
                    "behaviors": {},
                },
            )
            record["raw_weight"] += contribution
            record["event_count"] += count
            record["behaviors"][behavior] = {
                "count": count,
                "raw_weight": contribution,
            }

        positive_total = sum(
            max(record["raw_weight"], 0.0)
            for record in weights.values()
        )
        for record in weights.values():
            raw_weight = float(record["raw_weight"])
            record["normalized_weight"] = (
                max(raw_weight, 0.0) / positive_total
                if positive_total > 0
                else 0.0
            )
            record["direction"] = (
                "positive"
                if raw_weight > 0
                else "negative"
                if raw_weight < 0
                else "neutral"
            )
        return weights
