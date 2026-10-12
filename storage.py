"""外卖 Agent 的持久化存储层。"""

from __future__ import annotations

import json
import math
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from profile_weights import BehaviorWeights


ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = ROOT_DIR / "data" / "agent.db"

SUPPORTED_EVENTS = {
    *BehaviorWeights.BASE.keys(),
    *BehaviorWeights.ALIASES.keys(),
    "rating",
    "search",
}


class StorageError(RuntimeError):
    pass


class TakeoutStorage:
    def __init__(self, db_path: Path = DEFAULT_DB_PATH):
        self.db_path = Path(db_path).resolve()
        if not self.db_path.is_file():
            raise FileNotFoundError(f"数据库不存在：{self.db_path}")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def ensure_user(
        self,
        user_id: str,
        display_name: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO users (user_id, display_name)
                VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    display_name = COALESCE(excluded.display_name, users.display_name),
                    updated_at = CURRENT_TIMESTAMP
                """,
                (user_id, display_name),
            )

    def ensure_session(self, session_id: str, user_id: str) -> None:
        self.ensure_user(user_id)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO chat_sessions (session_id, user_id)
                VALUES (?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    updated_at = CURRENT_TIMESTAMP
                """,
                (session_id, user_id),
            )

    def get_session_summary(self, session_id: str) -> str:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT summary FROM chat_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return row["summary"] if row and row["summary"] else ""

    def update_session_summary(
        self,
        session_id: str,
        summary: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE chat_sessions
                SET summary = ?, updated_at = CURRENT_TIMESTAMP
                WHERE session_id = ?
                """,
                (summary, session_id),
            )

    def append_message(
        self,
        session_id: str,
        role: str,
        content: str | None = "",
        *,
        tool_call_id: str | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
        tool_name: str | None = None,
    ) -> int:
        tool_calls_json = (
            json.dumps(tool_calls, ensure_ascii=False)
            if tool_calls
            else None
        )
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO chat_messages (
                    session_id, role, content, tool_call_id,
                    tool_calls_json, tool_name
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    role,
                    content or "",
                    tool_call_id,
                    tool_calls_json,
                    tool_name,
                ),
            )
            message_id = int(cursor.lastrowid)
            conn.execute(
                """
                UPDATE chat_sessions
                SET updated_at = CURRENT_TIMESTAMP
                WHERE session_id = ?
                """,
                (session_id,),
            )
        return message_id

    @staticmethod
    def _row_to_message(row: sqlite3.Row) -> dict[str, Any]:
        message: dict[str, Any] = {
            "role": row["role"],
            "content": row["content"] or "",
        }
        if row["tool_call_id"]:
            message["tool_call_id"] = row["tool_call_id"]
        if row["tool_name"]:
            message["name"] = row["tool_name"]
        if row["tool_calls_json"]:
            message["tool_calls"] = json.loads(row["tool_calls_json"])
        return message

    def load_pending_messages(self, session_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT role, content, tool_call_id, tool_calls_json, tool_name
                FROM chat_messages
                WHERE session_id = ? AND is_summarized = 0
                ORDER BY id
                """,
                (session_id,),
            ).fetchall()
        return [self._row_to_message(row) for row in rows]

    def load_messages_to_summarize(
        self,
        session_id: str,
        keep_last: int = 6,
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, role, content, tool_call_id,
                       tool_calls_json, tool_name
                FROM chat_messages
                WHERE session_id = ? AND is_summarized = 0
                ORDER BY id
                """,
                (session_id,),
            ).fetchall()

        cutoff_id = self._summary_cutoff_id(rows, keep_last)
        if cutoff_id is None:
            return []

        return [
            self._row_to_message(row)
            for row in rows
            if row["id"] < cutoff_id
        ]

    @staticmethod
    def _summary_cutoff_id(
        rows: list[sqlite3.Row],
        keep_last: int,
    ) -> int | None:
        if len(rows) <= keep_last:
            return None
        for row in rows[-keep_last:]:
            if row["role"] == "user":
                return int(row["id"])
        return None

    def mark_messages_summarized(
        self,
        session_id: str,
        keep_last: int = 6,
    ) -> int:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, role
                FROM chat_messages
                WHERE session_id = ? AND is_summarized = 0
                ORDER BY id
                """,
                (session_id,),
            ).fetchall()
            cutoff_id = self._summary_cutoff_id(rows, keep_last)
            if cutoff_id is None:
                return 0
            cursor = conn.execute(
                """
                UPDATE chat_messages
                SET is_summarized = 1
                WHERE session_id = ? AND is_summarized = 0 AND id < ?
                """,
                (session_id, cutoff_id),
            )
        return cursor.rowcount

    def pending_message_stats(self, session_id: str) -> dict[str, int]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS message_count,
                    COALESCE(SUM(
                        LENGTH(COALESCE(content, '')) +
                        LENGTH(COALESCE(tool_calls_json, ''))
                    ), 0) AS content_length
                FROM chat_messages
                WHERE session_id = ? AND is_summarized = 0
                """,
                (session_id,),
            ).fetchone()
        return {
            "message_count": int(row["message_count"]),
            "content_length": int(row["content_length"]),
        }

    def set_preference(
        self,
        user_id: str,
        key: str,
        value: Any,
        *,
        confidence: float = 1.0,
        source: str = "user",
    ) -> dict[str, Any]:
        self.ensure_user(user_id)
        value_json = json.dumps(value, ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO user_preferences (
                    user_id, key, value, confidence, source, updated_at
                ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id, key) DO UPDATE SET
                    value = excluded.value,
                    confidence = excluded.confidence,
                    source = excluded.source,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    user_id,
                    key,
                    value_json,
                    max(0.0, min(float(confidence), 1.0)),
                    source,
                ),
            )
            observation = 0.0
            if key in {"avoided_categories", "avoided_foods"}:
                observation = -1.0
            elif key in {"preferred_categories", "preferred_foods"}:
                observation = 1.0
            elif key == "spicy_max":
                try:
                    observation = float(value) / 5.0
                except (TypeError, ValueError):
                    observation = 0.0
            elif key == "budget_max":
                try:
                    observation = min(float(value) / 100.0, 1.0)
                except (TypeError, ValueError):
                    observation = 0.0
            elif key == "min_rating":
                try:
                    observation = float(value) / 5.0
                except (TypeError, ValueError):
                    observation = 0.0
            elif key == "delivery_fee_max":
                try:
                    observation = min(float(value) / 10.0, 1.0)
                except (TypeError, ValueError):
                    observation = 0.0
            self._upsert_profile_feature(
                conn,
                user_id,
                f"preference:{key}",
                observation=observation,
                feature_value=value,
                alpha=1.0,
                source=source,
            )
        return {"user_id": user_id, "key": key, "value": value}

    def get_preferences(self, user_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT key, value
                FROM user_preferences
                WHERE user_id = ?
                ORDER BY key
                """,
                (user_id,),
            ).fetchall()

        preferences: dict[str, Any] = {}
        for row in rows:
            try:
                preferences[row["key"]] = json.loads(row["value"])
            except json.JSONDecodeError:
                preferences[row["key"]] = row["value"]
        return preferences

    def delete_preference(self, user_id: str, key: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM user_preferences WHERE user_id = ? AND key = ?",
                (user_id, key),
            )
        return cursor.rowcount > 0

    @staticmethod
    def _decode_feature_value(value: Any) -> Any:
        if value is None:
            return None
        try:
            return json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return value

    @staticmethod
    def _upsert_profile_feature(
        conn: sqlite3.Connection,
        user_id: str,
        feature_key: str,
        *,
        observation: float,
        feature_value: Any,
        alpha: float,
        source: str = "behavior",
        numeric_value: bool = False,
    ) -> None:
        current = conn.execute(
            """
            SELECT score, confidence, feature_value
            FROM user_profile_features
            WHERE user_id = ? AND feature_key = ?
            """,
            (user_id, feature_key),
        ).fetchone()
        observation = max(-1.0, min(float(observation), 1.0))
        alpha = max(0.0, min(float(alpha), 1.0))

        stored_value = feature_value
        if numeric_value:
            try:
                observed_value = float(feature_value)
                if current is None:
                    stored_value = observed_value
                else:
                    current_value = float(
                        TakeoutStorage._decode_feature_value(
                            current["feature_value"]
                        )
                    )
                    stored_value = (
                        current_value * (1.0 - alpha)
                        + observed_value * alpha
                    )
            except (TypeError, ValueError):
                stored_value = feature_value

        if current is None:
            score = observation
            confidence = alpha
        else:
            score = (
                float(current["score"] or 0) * (1.0 - alpha)
                + observation * alpha
            )
            old_confidence = float(current["confidence"] or 0)
            confidence = old_confidence + alpha * (1.0 - old_confidence)

        conn.execute(
            """
            INSERT INTO user_profile_features (
                user_id, feature_key, feature_value, score, confidence,
                source, update_count, first_seen_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id, feature_key) DO UPDATE SET
                feature_value = excluded.feature_value,
                score = excluded.score,
                confidence = excluded.confidence,
                source = excluded.source,
                update_count = user_profile_features.update_count + 1,
                last_seen_at = CURRENT_TIMESTAMP
            """,
            (
                user_id,
                feature_key,
                json.dumps(stored_value, ensure_ascii=False),
                max(-1.0, min(score, 1.0)),
                max(0.0, min(confidence, 1.0)),
                source,
            ),
        )

    @staticmethod
    def _dish_by_id(
        conn: sqlite3.Connection,
        dish_id: str,
    ) -> sqlite3.Row | None:
        return conn.execute(
            """
            SELECT
                d.id, d.name, d.price, d.spicy_level, d.month_sales,
                d.restaurant_id, r.name AS restaurant_name, r.category,
                r.delivery_fee, r.distance_km
            FROM dishes AS d
            JOIN restaurants AS r ON r.id = d.restaurant_id
            WHERE d.id = ?
            LIMIT 1
            """,
            (dish_id,),
        ).fetchone()

    def _rebuild_behavior_profile(
        self,
        conn: sqlite3.Connection,
        user_id: str,
    ) -> None:
        rows = conn.execute(
            """
            SELECT
                e.id,
                e.event_type,
                e.dish_id,
                e.restaurant_id,
                e.context_json,
                MAX(
                    julianday('now') - julianday(e.created_at),
                    0
                ) AS days_ago,
                d.name AS dish_name,
                d.spicy_level,
                d.price,
                r.category,
                r.name AS restaurant_name,
                r.delivery_fee,
                r.distance_km
            FROM user_events AS e
            LEFT JOIN dishes AS d ON d.id = e.dish_id
            LEFT JOIN restaurants AS r ON r.id = e.restaurant_id
            WHERE e.user_id = ?
            ORDER BY e.id
            """,
            (user_id,),
        ).fetchall()

        events: list[dict[str, Any]] = []
        tag_labels: dict[str, str] = {}
        metric_acc: dict[str, list[tuple[float, float]]] = {
            "spicy_preference": [],
            "price_preference": [],
            "delivery_fee_preference": [],
            "distance_preference": [],
        }

        for row in rows:
            context = self._decode_feature_value(row["context_json"])
            if not isinstance(context, dict):
                context = {}
            rating = context.get("rating")
            dwell_sec = context.get("dwell_sec")
            tags: list[str] = []
            if row["category"]:
                tags.append(f"category:{row['category']}")
                tag_labels[f"category:{row['category']}"] = str(
                    row["category"]
                )
            if row["restaurant_id"]:
                tags.append(f"restaurant:{row['restaurant_id']}")
                tag_labels[f"restaurant:{row['restaurant_id']}"] = str(
                    row["restaurant_name"] or row["restaurant_id"]
                )
            if row["dish_id"]:
                tags.append(f"dish:{row['dish_id']}")
                tag_labels[f"dish:{row['dish_id']}"] = str(
                    row["dish_name"] or row["dish_id"]
                )

            event = {
                "event_type": row["event_type"],
                "days_ago": float(row["days_ago"] or 0),
                "rating": rating,
                "dwell_sec": dwell_sec,
                "tags": tags,
            }
            events.append(event)

            contribution = BehaviorWeights.event_contribution(
                row["event_type"],
                float(row["days_ago"] or 0),
                score=rating,
                dwell_sec=float(dwell_sec or 0),
            )
            if (
                contribution <= 0
                or not row["dish_id"]
            ):
                continue
            metrics = {
                "spicy_preference": float(row["spicy_level"] or 0),
                "price_preference": float(row["price"] or 0),
                "delivery_fee_preference": float(
                    row["delivery_fee"] or 0
                ),
                "distance_preference": float(
                    row["distance_km"] or 0
                ),
            }
            for key, value in metrics.items():
                metric_acc[key].append((value, contribution))

        tag_weights = BehaviorWeights.aggregate_tag_weights(events)
        conn.execute(
            """
            DELETE FROM user_profile_features
            WHERE user_id = ? AND source = 'behavior'
            """,
            (user_id,),
        )

        for feature_key, record in tag_weights.items():
            count = int(record["event_count"])
            confidence = min(
                1.0,
                math.log2(1 + count) / 5.0,
            )
            record["label"] = tag_labels.get(feature_key, feature_key)
            conn.execute(
                """
                INSERT INTO user_profile_features (
                    user_id, feature_key, feature_value, score,
                    confidence, source, update_count,
                    first_seen_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, 'behavior', ?,
                          CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                (
                    user_id,
                    feature_key,
                    json.dumps(record, ensure_ascii=False),
                    float(record["raw_weight"]),
                    confidence,
                    count,
                ),
            )

        metric_scales = {
            "spicy_preference": 5.0,
            "price_preference": 100.0,
            "delivery_fee_preference": 10.0,
            "distance_preference": 5.0,
        }
        for key, observations in metric_acc.items():
            if not observations:
                continue
            total_weight = sum(weight for _, weight in observations)
            if total_weight <= 0:
                continue
            average_value = sum(
                value * weight
                for value, weight in observations
            ) / total_weight
            conn.execute(
                """
                INSERT INTO user_profile_features (
                    user_id, feature_key, feature_value, score,
                    confidence, source, update_count,
                    first_seen_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, 'behavior', ?,
                          CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                (
                    user_id,
                    key,
                    json.dumps(average_value, ensure_ascii=False),
                    min(average_value / metric_scales[key], 1.0),
                    min(
                        1.0,
                        math.log2(1 + len(observations)) / 5.0,
                    ),
                    len(observations),
                ),
            )

    def record_event(
        self,
        user_id: str,
        event_type: str,
        *,
        dish_id: str | None = None,
        dish_name: str | None = None,
        restaurant_id: str | None = None,
        session_id: str | None = None,
        search_query: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if event_type not in SUPPORTED_EVENTS:
            raise StorageError(f"不支持的事件类型：{event_type}")

        self.ensure_user(user_id)
        with self._connect() as conn:
            dish = None
            if dish_id:
                dish = self._dish_by_id(conn, dish_id)
            elif dish_name:
                dish = self._resolve_dish(conn, dish_name)

            if dish:
                dish_id = dish["id"]
                restaurant_id = dish["restaurant_id"]

            cursor = conn.execute(
                """
                INSERT INTO user_events (
                    user_id, event_type, dish_id, restaurant_id,
                    session_id, search_query, context_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    event_type,
                    dish_id,
                    restaurant_id,
                    session_id,
                    search_query,
                    json.dumps(context or {}, ensure_ascii=False),
                ),
            )
            event_id = int(cursor.lastrowid)

            self._rebuild_behavior_profile(conn, user_id)

        return {
            "event_id": event_id,
            "user_id": user_id,
            "event_type": event_type,
            "dish_id": dish_id,
            "restaurant_id": restaurant_id,
        }

    def get_profile_features(
        self,
        user_id: str,
    ) -> dict[str, dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    feature_key, feature_value, score, confidence,
                    source, update_count, first_seen_at, last_seen_at
                FROM user_profile_features
                WHERE user_id = ?
                ORDER BY confidence DESC, feature_key
                """,
                (user_id,),
            ).fetchall()

        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            result[row["feature_key"]] = {
                "value": self._decode_feature_value(row["feature_value"]),
                "score": round(float(row["score"] or 0), 4),
                "confidence": round(
                    float(row["confidence"] or 0),
                    4,
                ),
                "source": row["source"],
                "update_count": int(row["update_count"] or 0),
                "first_seen_at": row["first_seen_at"],
                "last_seen_at": row["last_seen_at"],
            }
        return result

    def rebuild_user_profile(self, user_id: str) -> None:
        self.ensure_user(user_id)
        with self._connect() as conn:
            self._rebuild_behavior_profile(conn, user_id)

    def get_profile_summary(
        self,
        user_id: str,
        *,
        limit: int = 10,
    ) -> dict[str, Any]:
        self.rebuild_user_profile(user_id)
        features = self.get_profile_features(user_id)

        def label(key: str, value: dict[str, Any]) -> str:
            payload = value.get("value")
            if isinstance(payload, dict):
                return str(payload.get("label") or key)
            return key

        categories = sorted(
            (
                (
                    label(
                        key.removeprefix("category:"),
                        value,
                    ),
                    value,
                )
                for key, value in features.items()
                if key.startswith("category:")
            ),
            key=lambda item: item[1]["score"],
            reverse=True,
        )[:limit]
        dishes = sorted(
            (
                (label(key, value), value)
                for key, value in features.items()
                if key.startswith("dish:")
            ),
            key=lambda item: item[1]["score"],
            reverse=True,
        )[:limit]
        restaurants = sorted(
            (
                (label(key, value), value)
                for key, value in features.items()
                if key.startswith("restaurant:")
            ),
            key=lambda item: item[1]["score"],
            reverse=True,
        )[:limit]
        metrics = {
            key: value
            for key, value in features.items()
            if key in {
                "spicy_preference",
                "price_preference",
                "delivery_fee_preference",
                "distance_preference",
            }
        }
        return {
            "user_id": user_id,
            "feature_count": len(features),
            "explicit_preferences": self.get_preferences(user_id),
            "categories": categories,
            "dishes": dishes,
            "restaurants": restaurants,
            "metrics": metrics,
        }

    def list_user_events(
        self,
        user_id: str,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    id, event_type, dish_id, restaurant_id,
                    session_id, search_query, context_json, created_at
                FROM user_events
                WHERE user_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["context"] = self._decode_feature_value(
                item.pop("context_json")
            )
            result.append(item)
        return result

    def record_recommendation_batch(
        self,
        user_id: str,
        recommendations: list[dict[str, Any]],
        *,
        session_id: str | None = None,
        context: dict[str, Any] | None = None,
        algorithm_version: str = "weighted-v1",
    ) -> str:
        if not recommendations:
            return ""
        self.ensure_user(user_id)
        batch_id = f"rec_{uuid.uuid4().hex}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO recommendation_batches (
                    batch_id, user_id, session_id,
                    algorithm_version, context_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    batch_id,
                    user_id,
                    session_id,
                    algorithm_version,
                    json.dumps(context or {}, ensure_ascii=False),
                ),
            )
            conn.executemany(
                """
                INSERT INTO recommendation_impressions (
                    batch_id, user_id, dish_id, restaurant_id, rank, score
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        batch_id,
                        user_id,
                        item["dish_id"],
                        item.get("restaurant_id"),
                        int(item.get("rank") or 0),
                        float(item.get("score") or 0),
                    )
                    for item in recommendations
                ],
            )
        for item in recommendations:
            item["recommendation_batch_id"] = batch_id
        return batch_id

    def clear_user_profile(
        self,
        user_id: str,
        *,
        include_preferences: bool = False,
    ) -> dict[str, int]:
        with self._connect() as conn:
            impressions = conn.execute(
                "DELETE FROM recommendation_impressions WHERE user_id = ?",
                (user_id,),
            ).rowcount
            batches = conn.execute(
                "DELETE FROM recommendation_batches WHERE user_id = ?",
                (user_id,),
            ).rowcount
            events = conn.execute(
                "DELETE FROM user_events WHERE user_id = ?",
                (user_id,),
            ).rowcount
            features = conn.execute(
                "DELETE FROM user_profile_features WHERE user_id = ?",
                (user_id,),
            ).rowcount
            preferences = 0
            if include_preferences:
                preferences = conn.execute(
                    "DELETE FROM user_preferences WHERE user_id = ?",
                    (user_id,),
                ).rowcount
        return {
            "events": events,
            "features": features,
            "recommendation_impressions": impressions,
            "recommendation_batches": batches,
            "preferences": preferences,
        }

    def _resolve_dish(
        self,
        conn: sqlite3.Connection,
        dish_name: str,
    ) -> sqlite3.Row:
        exact = conn.execute(
            """
            SELECT
                d.id, d.name, d.price, d.spicy_level, d.month_sales,
                d.restaurant_id, r.name AS restaurant_name, r.category,
                r.delivery_fee, r.distance_km
            FROM dishes AS d
            JOIN restaurants AS r ON r.id = d.restaurant_id
            WHERE d.name = ?
            LIMIT 1
            """,
            (dish_name,),
        ).fetchone()
        if exact:
            return exact

        matches = conn.execute(
            """
            SELECT
                d.id, d.name, d.price, d.spicy_level, d.month_sales,
                d.restaurant_id, r.name AS restaurant_name, r.category,
                r.delivery_fee, r.distance_km
            FROM dishes AS d
            JOIN restaurants AS r ON r.id = d.restaurant_id
            WHERE d.name LIKE ?
            ORDER BY LENGTH(d.name)
            LIMIT 2
            """,
            (f"%{dish_name}%",),
        ).fetchall()
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise StorageError(f"未找到菜品：{dish_name}")
        names = "、".join(row["name"] for row in matches)
        raise StorageError(f"菜品名称不唯一：{dish_name}，可能包括 {names}")

    def record_order(
        self,
        user_id: str,
        dish_name: str,
        *,
        rating: float | None = None,
        source: str = "assistant",
    ) -> dict[str, Any]:
        self.ensure_user(user_id)
        with self._connect() as conn:
            dish = self._resolve_dish(conn, dish_name)
            cursor = conn.execute(
                """
                INSERT INTO order_history (
                    dish_name, restaurant_name, price, category,
                    user_id, dish_id, restaurant_id, rating, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    dish["name"],
                    dish["restaurant_name"],
                    dish["price"],
                    dish["category"],
                    user_id,
                    dish["id"],
                    dish["restaurant_id"],
                    rating,
                    source,
                ),
            )
            order_id = int(cursor.lastrowid)

        self.record_event(
            user_id,
            "order",
            dish_id=dish["id"],
            restaurant_id=dish["restaurant_id"],
            context={
                "order_id": order_id,
                "rating": rating,
                "source": source,
            },
        )
        if rating is not None:
            self.record_event(
                user_id,
                "rating",
                dish_id=dish["id"],
                restaurant_id=dish["restaurant_id"],
                context={
                    "rating": rating,
                    "order_id": order_id,
                    "source": source,
                },
            )

        return {
            "order_id": order_id,
            "user_id": user_id,
            "dish_id": dish["id"],
            "dish_name": dish["name"],
            "restaurant_id": dish["restaurant_id"],
            "restaurant_name": dish["restaurant_name"],
            "category": dish["category"],
            "price": dish["price"],
            "rating": rating,
        }

    def recent_orders(
        self,
        user_id: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 50))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    id, dish_name, restaurant_name, price, category,
                    rating, source, created_at
                FROM order_history
                WHERE user_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def find_dish_name_in_text(self, text: str) -> str | None:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT name
                FROM dishes
                WHERE is_sold_out IS NULL OR is_sold_out = 0
                ORDER BY LENGTH(name) DESC
                """
            ).fetchall()
        return next(
            (
                row["name"]
                for row in rows
                if row["name"] and row["name"] in text
            ),
            None,
        )

    def recommend_dishes(
        self,
        user_id: str,
        *,
        limit: int = 12,
        max_price: float | None = None,
        max_spicy: int | None = None,
        category: str | None = None,
        min_rating: float | None = None,
        session_id: str | None = None,
        requested_dish: str | None = None,
    ) -> list[dict[str, Any]]:
        preferences = self.get_preferences(user_id)
        self.rebuild_user_profile(user_id)
        profile_features = self.get_profile_features(user_id)
        limit = max(1, min(int(limit), 20))
        if max_price is None:
            max_price = preferences.get("budget_max")
            if max_price is None:
                profile_price = profile_features.get(
                    "price_preference"
                )
                if profile_price and float(profile_price["confidence"]) >= 0.1:
                    try:
                        max_price = (
                            float(profile_price["value"]) * 1.25
                        )
                    except (TypeError, ValueError):
                        max_price = None
        if max_spicy is None:
            max_spicy = preferences.get("spicy_max")
        profile_spicy = profile_features.get("spicy_preference")
        profile_category_scores = {
            key.removeprefix("category:"): float(
                value["value"].get("raw_weight", value["score"])
                if isinstance(value["value"], dict)
                else value["score"]
            )
            for key, value in profile_features.items()
            if key.startswith("category:")
            and float(value["confidence"]) >= 0.1
        }
        max_delivery_fee = preferences.get("delivery_fee_max")

        preferred_categories = preferences.get("preferred_categories", [])
        if isinstance(preferred_categories, str):
            preferred_categories = [preferred_categories]
        preferred_categories = {
            str(item).strip()
            for item in preferred_categories
            if str(item).strip()
        }

        avoided_categories = preferences.get("avoided_categories", [])
        if isinstance(avoided_categories, str):
            avoided_categories = [avoided_categories]
        avoided_categories = {
            str(item).strip()
            for item in avoided_categories
            if str(item).strip()
        }
        avoided_foods = preferences.get("avoided_foods", [])
        if isinstance(avoided_foods, str):
            avoided_foods = [avoided_foods]
        avoided_foods = [
            str(item).strip()
            for item in avoided_foods
            if str(item).strip()
        ]
        preferred_foods = preferences.get("preferred_foods", [])
        if isinstance(preferred_foods, str):
            preferred_foods = [preferred_foods]
        preferred_foods = [
            str(item).strip()
            for item in preferred_foods
            if str(item).strip()
        ]

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    d.id AS dish_id,
                    d.name AS dish_name,
                    r.id AS restaurant_id,
                    r.name AS restaurant_name,
                    r.e_poi_id AS e_poi_id,
                    r.category,
                    d.price,
                    d.spicy_level,
                    d.month_sales,
                    r.rating,
                    r.delivery_fee,
                    r.distance_km,
                    COUNT(oh.id) AS user_order_count
                FROM dishes AS d
                JOIN restaurants AS r ON r.id = d.restaurant_id
                LEFT JOIN order_history AS oh
                    ON oh.user_id = ? AND oh.dish_id = d.id
                GROUP BY
                    d.id, d.name, r.id, r.name, r.e_poi_id, r.category,
                    d.price, d.spicy_level, d.month_sales,
                    r.rating, r.delivery_fee, r.distance_km
                """,
                (user_id,),
            ).fetchall()
            category_rows = conn.execute(
                """
                SELECT category, COUNT(*) AS order_count
                FROM order_history
                WHERE user_id = ? AND category IS NOT NULL
                GROUP BY category
                """,
                (user_id,),
            ).fetchall()

        exact_category_matches = [
            row
            for row in rows
            if not category or row["category"] == category
        ]
        category_fallback = bool(
            category
            and rows
            and not any(
                row["category"] == category
                for row in rows
            )
        )

        candidates = [
            dict(row)
            for row in (
                rows if category_fallback else exact_category_matches
            )
            if (
                (
                    min_rating is None
                    or float(row["rating"] or 0) >= float(min_rating)
                )
                and row["category"] not in avoided_categories
                and not any(
                    food in str(row["dish_name"])
                    or str(row["dish_name"]) in food
                    for food in avoided_foods
                    if not (
                        requested_dish
                        and (
                            food in str(row["dish_name"])
                            or str(row["dish_name"]) in food
                        )
                    )
                )
                and (
                    max_delivery_fee is None
                    or float(row["delivery_fee"] or 0)
                    <= float(max_delivery_fee)
                )
            )
        ]
        if not candidates:
            return []

        history_counts = {
            row["category"]: int(row["order_count"])
            for row in category_rows
        }
        max_history_count = max(history_counts.values(), default=0)
        max_sales = max(
            float(item["month_sales"] or 0)
            for item in candidates
        )
        prices = [float(item["price"] or 0) for item in candidates]
        profile_price_value = None
        profile_price_feature = profile_features.get("price_preference")
        if profile_price_feature:
            try:
                profile_price_value = float(
                    profile_price_feature["value"]
                )
            except (TypeError, ValueError):
                profile_price_value = None
        profile_distance_value = None
        profile_distance_feature = profile_features.get(
            "distance_preference"
        )
        if profile_distance_feature:
            try:
                profile_distance_value = float(
                    profile_distance_feature["value"]
                )
            except (TypeError, ValueError):
                profile_distance_value = None
        profile_fee_value = None
        profile_fee_feature = profile_features.get(
            "delivery_fee_preference"
        )
        if profile_fee_feature:
            try:
                profile_fee_value = float(profile_fee_feature["value"])
            except (TypeError, ValueError):
                profile_fee_value = None
        if max_price is not None:
            budget = float(max_price)
            ideal_price = budget * 0.7
            price_scale = max(ideal_price, budget - ideal_price, 1.0)
        else:
            budget = None
            if profile_price_value is not None:
                ideal_price = profile_price_value
            else:
                sorted_prices = sorted(prices)
                ideal_price = sorted_prices[len(sorted_prices) // 2]
            price_scale = max(
                max(prices) - ideal_price,
                ideal_price - min(prices),
                1.0,
            )

        distances = [
            float(item["distance_km"] or 0)
            for item in candidates
        ]
        delivery_fees = [
            float(item["delivery_fee"] or 0)
            for item in candidates
        ]
        min_distance, max_distance = min(distances), max(distances)
        min_fee, max_fee = min(delivery_fees), max(delivery_fees)

        recommendations: list[dict[str, Any]] = []
        for item in candidates:
            month_sales = float(item["month_sales"] or 0)
            hot_score = (
                month_sales / max_sales if max_sales > 0 else 0.0
            )
            rating_score = float(item["rating"] or 0) / 5.0

            price = float(item["price"] or 0)
            if budget is None:
                price_score = max(
                    0.0,
                    1.0 - abs(price - ideal_price) / price_scale,
                )
            elif price > budget:
                price_score = 0.0
            else:
                price_score = max(
                    0.0,
                    1.0 - abs(price - ideal_price) / price_scale,
                )

            distance = float(item["distance_km"] or 0)
            if profile_distance_value is not None:
                distance_score = max(
                    0.0,
                    1.0
                    - max(
                        distance - profile_distance_value,
                        0.0,
                    )
                    / max(profile_distance_value, 1.0),
                )
            elif max_distance > min_distance:
                distance_score = 1.0 - (
                    (distance - min_distance)
                    / (max_distance - min_distance)
                )
            else:
                distance_score = 1.0

            delivery_fee = float(item["delivery_fee"] or 0)
            if profile_fee_value is not None:
                delivery_score = max(
                    0.0,
                    1.0
                    - max(
                        delivery_fee - profile_fee_value,
                        0.0,
                    )
                    / max(profile_fee_value, 1.0),
                )
            elif max_fee > min_fee:
                delivery_score = 1.0 - (
                    (delivery_fee - min_fee) / (max_fee - min_fee)
                )
            else:
                delivery_score = 1.0

            spicy_level = int(item["spicy_level"] or 0)
            if max_spicy is None:
                if profile_spicy and float(
                    profile_spicy["confidence"]
                ) >= 0.1:
                    preferred_spicy = float(profile_spicy["score"])
                    spicy_score = max(
                        0.0,
                        1.0
                        - abs((spicy_level / 5.0) - preferred_spicy),
                    )
                else:
                    spicy_score = 0.5
            elif spicy_level <= int(max_spicy):
                spicy_score = 1.0
            else:
                spicy_score = 0.0

            item_category = str(item["category"] or "")
            requested_cuisine_preferences = (
                {str(category)} if category else preferred_categories
            )
            if requested_cuisine_preferences:
                cuisine_score = (
                    1.0
                    if item_category in requested_cuisine_preferences
                    else 0.0
                )
            elif profile_category_scores:
                raw_category_weight = profile_category_scores.get(
                    item_category,
                    0.0,
                )
                if raw_category_weight >= 0:
                    cuisine_score = min(
                        1.0,
                        0.5 + raw_category_weight / 40.0,
                    )
                else:
                    cuisine_score = max(
                        0.0,
                        0.5 + raw_category_weight / 20.0,
                    )
            elif max_history_count > 0:
                cuisine_score = (
                    history_counts.get(item_category, 0)
                    / max_history_count
                )
            else:
                cuisine_score = 0.5

            preferred_food_match = next(
                (
                    food
                    for food in preferred_foods
                    if food in str(item["dish_name"])
                    or str(item["dish_name"]) in food
                ),
                None,
            )
            if preferred_food_match:
                cuisine_score = max(cuisine_score, 0.9)

            score = 100.0 * (
                0.20 * hot_score
                + 0.10 * rating_score
                + 0.20 * price_score
                + 0.10 * distance_score
                + 0.05 * delivery_score
                + 0.20 * spicy_score
                + 0.15 * cuisine_score
            )

            reasons: list[str] = []
            if category_fallback:
                reasons.append(
                    f"数据库中暂无“{category}”，已放宽菜系条件"
                )
            if item["user_order_count"]:
                reasons.append(
                    f'以前点过 {item["user_order_count"]} 次'
                )
            if budget is not None and price > budget:
                reasons.append(f"超出预算 {budget:.0f} 元")
            if max_spicy is not None and spicy_level > int(max_spicy):
                reasons.append("辣度高于偏好")
            if month_sales >= 1000:
                reasons.append(f'月售 {int(month_sales)} 份')
            if rating_score >= 0.9:
                reasons.append(f'商家评分 {item["rating"]}')
            if distance_score >= 0.8:
                reasons.append(f'距离 {distance:.1f} 公里')
            if delivery_score >= 0.8:
                reasons.append(f"配送费 {delivery_fee:.0f} 元")
            if requested_cuisine_preferences and cuisine_score == 1.0:
                reasons.append(f"符合偏好菜系 {item_category}")
            elif profile_category_scores.get(item_category, 0.0) > 0.2:
                reasons.append(f"画像偏好菜系 {item_category}")
            if preferred_food_match:
                reasons.append(f"符合明确喜好：{preferred_food_match}")

            item.update(
                {
                    "score": round(score, 2),
                    "hot_score": round(hot_score, 4),
                    "rating_score": round(rating_score, 4),
                    "price_score": round(price_score, 4),
                    "distance_score": round(distance_score, 4),
                    "delivery_score": round(delivery_score, 4),
                    "spicy_score": round(spicy_score, 4),
                    "cuisine_score": round(cuisine_score, 4),
                    "meets_budget": (
                        budget is None or price <= budget
                    ),
                    "meets_spicy_preference": (
                        max_spicy is None
                        or spicy_level <= int(max_spicy)
                    ),
                    "requested_category": category,
                    "category_fallback": category_fallback,
                    "category_match": (
                        item_category == category if category else None
                    ),
                    "reasons": reasons or ["多维度得分较均衡"],
                }
            )
            recommendations.append(item)

        recommendations.sort(
            key=lambda item: (
                item["score"],
                item["month_sales"],
                item["rating"],
            ),
            reverse=True,
        )
        if requested_dish:
            requested_items = [
                item
                for item in recommendations
                if requested_dish in str(item["dish_name"])
                or str(item["dish_name"]) in requested_dish
            ]
            if requested_items:
                requested_ids = {item["dish_id"] for item in requested_items}
                recommendations = [
                    *requested_items,
                    *(
                        item
                        for item in recommendations
                        if item["dish_id"] not in requested_ids
                    ),
                ]
                for item in requested_items:
                    item["reasons"].insert(
                        0,
                        "本次明确指定，临时覆盖长期忌口",
                    )
                    item["explicit_request_override"] = True
        for index, item in enumerate(recommendations, start=1):
            item["rank"] = index
        results = recommendations[:limit]
        self.record_recommendation_batch(
            user_id,
            results,
            session_id=session_id,
            context={
                "category": category,
                "max_price": max_price,
                "max_spicy": max_spicy,
                "profile_feature_count": len(profile_features),
                "requested_dish": requested_dish,
            },
        )
        return results
