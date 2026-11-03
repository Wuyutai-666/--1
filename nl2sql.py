"""基于云模型和 SQLite 的只读 NL2SQL 查询助手。"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

from dotenv import load_dotenv
from openai import OpenAI

from data.init_db import init as initialize_database
from meituan_sim import MeituanClient
from storage import TakeoutStorage
from toolkit import (
    TextCallback,
    ToolRegistry,
    register_calculator,
    register_file_writer,
    stream_chat_completion,
)


ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = ROOT_DIR / "data" / "agent.db"
MAX_ROWS = 100
MAX_LOOPS = 6
MAX_CONTEXT_MESSAGES = 20
MAX_CONTEXT_CHARS = 4000
SUMMARY_KEEP_LAST = 6

load_dotenv(ROOT_DIR / ".env")

MODEL = os.getenv("MODEL_NAME", "qwen2:7b-instruct")
CLIENT = OpenAI(
    base_url=os.getenv("LLM_BASE_URL", "http://localhost:11434/v1"),
    api_key=os.getenv("LLM_API_KEY") or os.getenv("LM_API_KEY") or "ollama",
)

FORBIDDEN_SQL = re.compile(
    r"\b("
    r"INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|TRUNCATE|"
    r"ATTACH|DETACH|PRAGMA|VACUUM|REINDEX|GRANT|REVOKE"
    r")\b",
    re.IGNORECASE,
)


class ThinkingIndicator:
    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        if not sys.stdout.isatty():
            return
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run,
                daemon=True,
            )
            self._thread.start()

    def _run(self) -> None:
        frames = [
            "AI 正在思考",
            "AI 正在思考.",
            "AI 正在思考..",
            "AI 正在思考...",
        ]
        index = 0
        while not self._stop_event.wait(0.35):
            sys.stdout.write(f"\r{frames[index]:<28}")
            sys.stdout.flush()
            index = (index + 1) % len(frames)

    def stop(self) -> None:
        with self._lock:
            thread = self._thread
            self._thread = None
            self._stop_event.set()
        if thread is None:
            return
        thread.join(timeout=1.0)
        if sys.stdout.isatty():
            sys.stdout.write("\r" + " " * 28 + "\r")
            sys.stdout.flush()

    def set_phase(self, phase: str) -> None:
        if phase == "thinking":
            self.start()
        else:
            self.stop()


class PacedTextPrinter:
    """将流式文本限制为指定字符数/秒。"""

    def __init__(
        self,
        chars_per_second: float = 30.0,
        stream: Any | None = None,
    ) -> None:
        self.chars_per_second = max(0.0, float(chars_per_second))
        self.stream = stream or sys.stdout
        self._next_allowed = time.perf_counter()

    def write(self, text: str) -> None:
        if not text:
            return
        if self.chars_per_second <= 0:
            self.stream.write(text)
            self.stream.flush()
            return

        interval = 1.0 / self.chars_per_second
        for character in text:
            delay = self._next_allowed - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            self.stream.write(character)
            self.stream.flush()
            self._next_allowed = max(
                self._next_allowed + interval,
                time.perf_counter(),
            )


class SQLSafetyError(ValueError):
    """生成的 SQL 不符合只读查询规则。"""


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[list[Any]]
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "columns": self.columns,
            "rows": self.rows,
            "row_count": len(self.rows),
            "truncated": self.truncated,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)


def validate_read_only_sql(sql: str) -> str:
    """只允许单条 SELECT 或 WITH 查询。"""
    if not isinstance(sql, str) or not sql.strip():
        raise SQLSafetyError("SQL 不能为空")

    cleaned = sql.strip()
    if cleaned.endswith(";"):
        cleaned = cleaned[:-1].rstrip()

    if ";" in cleaned:
        raise SQLSafetyError("只允许执行一条 SQL")
    if "--" in cleaned or "/*" in cleaned or "*/" in cleaned:
        raise SQLSafetyError("SQL 中不允许使用注释")
    if not re.match(r"^(SELECT|WITH)\b", cleaned, re.IGNORECASE):
        raise SQLSafetyError("只允许 SELECT 或 WITH 查询")
    if FORBIDDEN_SQL.search(cleaned):
        raise SQLSafetyError("SQL 包含被禁止的写操作关键字")

    return cleaned


def quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


class TakeoutDatabase:
    def __init__(self, db_path: Path = DEFAULT_DB_PATH):
        self.db_path = Path(db_path).resolve()
        if not self.db_path.is_file():
            raise FileNotFoundError(f"数据库不存在：{self.db_path}")

    def _connect(self) -> sqlite3.Connection:
        uri = f"{self.db_path.as_uri()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")
        return conn

    def schema_text(self) -> str:
        conn = self._connect()
        try:
            tables = conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                  AND name IN ('restaurants', 'dishes', 'order_history')
                ORDER BY name
                """
            ).fetchall()

            definitions: list[str] = []
            for table_row in tables:
                table = table_row["name"]
                quoted_table = quote_identifier(table)
                columns = conn.execute(
                    f"PRAGMA table_info({quoted_table})"
                ).fetchall()
                foreign_keys = conn.execute(
                    f"PRAGMA foreign_key_list({quoted_table})"
                ).fetchall()

                fk_map: dict[str, str] = {}
                for fk in foreign_keys:
                    fk_map[fk["from"]] = f'{fk["table"]}.{fk["to"]}'

                column_lines: list[str] = []
                for column in columns:
                    flags = []
                    if column["pk"]:
                        flags.append("PRIMARY KEY")
                    if column["notnull"]:
                        flags.append("NOT NULL")
                    if column["name"] in fk_map:
                        flags.append(f'REFERENCES {fk_map[column["name"]]}')
                    suffix = f" {' '.join(flags)}" if flags else ""
                    column_lines.append(
                        f"  {column['name']} {column['type']}{suffix}"
                    )

                row_count = conn.execute(
                    f"SELECT COUNT(*) AS count FROM {quoted_table}"
                ).fetchone()["count"]
                definitions.append(
                    f"{table} ({row_count} rows)\n"
                    + ",\n".join(column_lines)
                )

            return "\n\n".join(definitions)
        finally:
            conn.close()

    def execute_read_only(self, sql: str) -> QueryResult:
        query = validate_read_only_sql(sql)
        conn = self._connect()

        def authorizer(action: int, *_args: Any) -> int:
            allowed_actions = {
                sqlite3.SQLITE_SELECT,
                sqlite3.SQLITE_READ,
                sqlite3.SQLITE_FUNCTION,
            }
            recursive_action = getattr(sqlite3, "SQLITE_RECURSIVE", None)
            if recursive_action is not None:
                allowed_actions.add(recursive_action)
            return (
                sqlite3.SQLITE_OK
                if action in allowed_actions
                else sqlite3.SQLITE_DENY
            )

        try:
            conn.set_authorizer(authorizer)
            cursor = conn.execute(query)
            columns = (
                [item[0] for item in cursor.description]
                if cursor.description
                else []
            )
            fetched = cursor.fetchmany(MAX_ROWS + 1)
            truncated = len(fetched) > MAX_ROWS
            rows = [list(row) for row in fetched[:MAX_ROWS]]
            return QueryResult(
                columns=columns,
                rows=rows,
                truncated=truncated,
            )
        finally:
            conn.close()


def format_table(result: QueryResult) -> str:
    if not result.columns:
        return "(无列)"
    if not result.rows:
        return "(0 行)"

    def render_cell(value: Any) -> str:
        if value is None:
            return "NULL"
        text = str(value)
        return text if len(text) <= 36 else text[:33] + "..."

    rendered_rows = [
        [render_cell(value) for value in row]
        for row in result.rows
    ]
    widths = [
        max(
            len(result.columns[index]),
            *(len(row[index]) for row in rendered_rows),
        )
        for index in range(len(result.columns))
    ]

    def render_row(values: list[str]) -> str:
        cells = [
            value.ljust(widths[index])
            for index, value in enumerate(values)
        ]
        return " | ".join(cells)

    separator = "-+-".join("-" * width for width in widths)
    lines = [
        render_row(result.columns),
        separator,
        *(render_row(row) for row in rendered_rows),
    ]
    if result.truncated:
        lines.append(f"... 结果已截断，最多显示 {MAX_ROWS} 行")
    return "\n".join(lines)


class NL2SQLAgent:
    def __init__(
        self,
        database: TakeoutDatabase,
        storage: TakeoutStorage,
        *,
        user_id: str = "default",
        session_id: str = "default",
        meituan_client: MeituanClient | None = None,
    ):
        self.database = database
        self.storage = storage
        self.user_id = user_id
        self.session_id = session_id
        self.meituan_client = meituan_client or MeituanClient()
        self.storage.ensure_session(session_id, user_id)
        self.schema = database.schema_text()
        self.tool_registry = self._build_tool_registry()
        self.messages: list[dict[str, Any]] = []
        self._rebuild_messages()

    @staticmethod
    def _coerce_preference_value(key: str, value: Any) -> Any:
        if key in {"spicy_max"}:
            return int(value)
        if key in {
            "budget_max",
            "min_rating",
            "delivery_fee_max",
        }:
            return float(value)
        if key in {
            "preferred_categories",
            "avoided_categories",
            "preferred_foods",
            "avoided_foods",
        }:
            if isinstance(value, list):
                return value
            return [
                item.strip()
                for item in str(value).replace("，", ",").split(",")
                if item.strip()
            ]
        return str(value)

    def _save_preference(
        self,
        key: str,
        value: Any,
        confidence: float = 1.0,
    ) -> dict[str, Any]:
        coerced = self._coerce_preference_value(key, value)
        result = self.storage.set_preference(
            self.user_id,
            key,
            coerced,
            confidence=confidence,
            source="conversation",
        )
        self._refresh_system_message()
        return result

    def _record_user_feedback(
        self,
        dish_name: str,
        event_type: str,
        rating: float | None = None,
        dwell_sec: float | None = None,
    ) -> dict[str, Any]:
        return self.storage.record_event(
            self.user_id,
            event_type,
            dish_name=dish_name,
            session_id=self.session_id,
            context={
                "rating": rating,
                "dwell_sec": dwell_sec,
            },
        )

    def _build_tool_registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        registry.register(
            "execute_sql",
            "在外卖业务数据库中执行一条只读 SQL 查询",
            {
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "单条 SQLite SELECT 或 WITH 查询",
                    }
                },
            },
            lambda query: self.database.execute_read_only(query).to_dict(),
        )
        register_calculator(registry)
        register_file_writer(registry, ROOT_DIR)
        registry.register(
            "meituan_batch_upload",
            "通过美团官方 batchUpload 接口批量新增或更新菜品",
            {
                "type": "object",
                "required": ["e_poi_id", "dishes"],
                "properties": {
                    "e_poi_id": {
                        "type": "string",
                        "description": "ERP 门店 ID，例如 4213",
                    },
                    "dishes": {
                        "type": "array",
                        "description": "美团菜品数组",
                        "items": {
                            "type": "object",
                            "additionalProperties": True,
                        },
                    },
                },
            },
            lambda e_poi_id, dishes: self.meituan_client.batch_upload(
                e_poi_id,
                dishes,
            ),
        )
        registry.register(
            "meituan_query_dishes",
            "通过美团官方接口查询门店菜品",
            {
                "type": "object",
                "properties": {
                    "offset": {
                        "type": "integer",
                        "description": "分页偏移量，默认 0",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "每页数量，默认 100",
                    },
                },
            },
            lambda offset=0, limit=100: self.meituan_client.query_dishes(
                offset=offset,
                limit=limit,
            ),
        )
        registry.register(
            "meituan_query_categories",
            "通过美团官方接口查询门店菜品分类",
            {
                "type": "object",
                "properties": {
                    "e_poi_id": {
                        "type": "string",
                        "description": "ERP 门店 ID，可省略",
                    }
                },
            },
            lambda e_poi_id=None: self.meituan_client.query_categories(
                e_poi_id
            ),
        )
        registry.register(
            "meituan_update_price",
            "通过美团官方接口更新菜品 SKU 价格",
            {
                "type": "object",
                "required": ["dish_sku_prices"],
                "properties": {
                    "dish_sku_prices": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": True,
                        },
                    },
                    "e_poi_id": {
                        "type": "string",
                        "description": "ERP 门店 ID，可省略",
                    },
                },
            },
            lambda dish_sku_prices, e_poi_id=None: (
                self.meituan_client.update_price(
                    dish_sku_prices,
                    e_poi_id,
                )
            ),
        )
        registry.register(
            "meituan_update_stock",
            "通过美团官方接口更新菜品 SKU 库存",
            {
                "type": "object",
                "required": ["dish_sku_stocks"],
                "properties": {
                    "dish_sku_stocks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": True,
                        },
                    },
                    "e_poi_id": {
                        "type": "string",
                        "description": "ERP 门店 ID，可省略",
                    },
                },
            },
            lambda dish_sku_stocks, e_poi_id=None: (
                self.meituan_client.update_stock(
                    dish_sku_stocks,
                    e_poi_id,
                )
            ),
        )
        registry.register(
            "meituan_delete_dish",
            "通过美团官方接口删除菜品",
            {
                "type": "object",
                "required": ["e_dish_code"],
                "properties": {
                    "e_dish_code": {
                        "type": "string",
                        "description": "ERP 方菜品 ID",
                    }
                },
            },
            lambda e_dish_code: self.meituan_client.delete_dish(
                e_dish_code
            ),
        )
        registry.register(
            "save_user_preference",
            "保存用户的长期饮食偏好或预算",
            {
                "type": "object",
                "required": ["key", "value"],
                "properties": {
                    "key": {
                        "type": "string",
                        "enum": [
                            "spicy_max",
                            "budget_max",
                            "preferred_categories",
                            "avoided_categories",
                            "preferred_foods",
                            "avoided_foods",
                            "min_rating",
                            "delivery_fee_max",
                            "notes",
                        ],
                    },
                    "value": {
                        "type": "string",
                        "description": (
                            "偏好值。数字直接填写；多个菜系使用逗号分隔"
                        ),
                    },
                    "confidence": {
                        "type": "number",
                        "description": "0 到 1，默认 1",
                    },
                },
            },
            self._save_preference,
        )
        registry.register(
            "record_order",
            "记录用户已经点过或吃过的菜品，用于后续个性化推荐",
            {
                "type": "object",
                "required": ["dish_name"],
                "properties": {
                    "dish_name": {
                        "type": "string",
                        "description": "菜品名称",
                    },
                    "rating": {
                        "type": "number",
                        "description": "可选，用户评分 0 到 5",
                    },
                },
            },
            lambda dish_name, rating=None: self.storage.record_order(
                self.user_id,
                dish_name,
                rating=rating,
            ),
        )
        registry.register(
            "recommend_dishes",
            "按百分制多维度得分推荐约12道菜品；菜系不存在时自动放宽菜系条件",
            {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "推荐数量，默认 12，最多 20",
                    },
                    "max_price": {
                        "type": "number",
                        "description": "可选，本次最高价格",
                    },
                    "max_spicy": {
                        "type": "integer",
                        "description": "可选，本次最高辣度 0-5",
                    },
                    "category": {
                        "type": "string",
                        "description": "可选，菜系",
                    },
                    "min_rating": {
                        "type": "number",
                        "description": "可选，最低商家评分",
                    },
                    "requested_dish": {
                        "type": "string",
                        "description": (
                            "用户本次明确指定的菜品，优先推荐并可"
                            "临时覆盖长期忌口"
                        ),
                    },
                },
            },
            lambda limit=12, max_price=None, max_spicy=None, category=None,
            min_rating=None, requested_dish=None: self.storage.recommend_dishes(
                self.user_id,
                limit=limit,
                max_price=max_price,
                max_spicy=max_spicy,
                category=category,
                min_rating=min_rating,
                session_id=self.session_id,
                requested_dish=requested_dish,
            ),
        )
        registry.register(
            "record_user_feedback",
            "记录点击、收藏、加购、下单、忽略或评分行为并更新用户画像",
            {
                "type": "object",
                "required": ["dish_name", "event_type"],
                "properties": {
                    "dish_name": {"type": "string"},
                    "event_type": {
                        "type": "string",
                        "enum": [
                            "click",
                            "detail_view",
                            "favorite",
                            "cart_add",
                            "order",
                            "dismiss",
                            "not_interested",
                            "rating",
                        ],
                    },
                    "rating": {"type": "number"},
                    "dwell_sec": {
                        "type": "number",
                        "description": (
                            "查看详情停留秒数，仅 detail_view 使用"
                        ),
                    },
                },
            },
            self._record_user_feedback,
        )
        registry.register(
            "get_user_profile",
            "查看当前单用户画像",
            {"type": "object", "properties": {}},
            lambda: self.storage.get_profile_summary(
                self.user_id,
                limit=20,
            ),
        )
        registry.register(
            "clear_user_profile",
            "清空当前用户行为画像",
            {
                "type": "object",
                "properties": {
                    "include_preferences": {"type": "boolean"}
                },
            },
            lambda include_preferences=False: (
                self.storage.clear_user_profile(
                    self.user_id,
                    include_preferences=include_preferences,
                )
            ),
        )
        return registry

    def _profile_text(self) -> str:
        preferences = self.storage.get_preferences(self.user_id)
        recent_orders = self.storage.recent_orders(self.user_id, limit=5)
        learned_profile = self.storage.get_profile_summary(
            self.user_id,
            limit=5,
        )
        preference_text = (
            json.dumps(preferences, ensure_ascii=False, default=str)
            if preferences
            else "暂无长期偏好"
        )
        order_text = (
            json.dumps(recent_orders, ensure_ascii=False, default=str)
            if recent_orders
            else "暂无历史订单"
        )
        learned_text = json.dumps(
            {
                "categories": learned_profile["categories"],
                "dishes": learned_profile["dishes"],
                "restaurants": learned_profile["restaurants"],
                "metrics": learned_profile["metrics"],
            },
            ensure_ascii=False,
            default=str,
        )
        return (
            f"用户 ID：{self.user_id}\n"
            f"明确偏好：{preference_text}\n"
            f"行为画像：{learned_text}\n"
            f"最近订单：{order_text}"
        )

    def _build_system_message(self) -> dict[str, Any]:
        return {
            "role": "system",
            "content": (
                "你是具备长期记忆和推荐闭环的外卖 NL2SQL 助手。"
                "请使用工具完成任务，不要声称执行了未调用的工具。\n\n"
                f"数据库结构：\n{self.schema}\n\n"
                f"用户画像：\n{self._profile_text()}\n\n"
                "工具规则：\n"
                "1. 查询、筛选和统计使用 execute_sql，只允许单条 SELECT 或 WITH。\n"
                "2. 用户表达长期偏好时调用 save_user_preference，例如"
                "“我不吃辣”“预算 30”“喜欢川菜”“不吃猪脚饭”；"
                "具体忌口保存到 avoided_foods，具体喜好保存到 "
                "preferred_foods。\n"
                "3. 用户表示已经点过或吃过某菜时调用 record_order，"
                "成功记录后才能确认。\n"
                "4. 用户请求个性化推荐时优先调用 recommend_dishes；"
                "该工具默认返回约 12 条，并综合长期偏好和历史订单。\n"
                "5. 新增或更新菜品必须调用 meituan_batch_upload，"
                "接口字段使用 dishName、eDishCode、categoryName、"
                "price、unit、isSoldOut、skus 等美团标准字段。\n"
                "6. 查询美团菜品信息使用 meituan_query_dishes；"
                "修改价格和库存分别使用 meituan_update_price、"
                "meituan_update_stock；删除菜品使用 meituan_delete_dish。\n"
                "7. 数学计算使用 calculator，写入项目文件使用 write_file。\n"
                "8. 推荐得分采用 100 × (0.20 × 菜品热度分 + "
                "0.10 × 商家评分分 + 0.20 × 价格适配分 + "
                "0.10 × 距离便利分 + 0.05 × 配送成本分 + "
                "0.20 × 辣度匹配分 + 0.15 × 菜系偏好分)。\n"
                "9. 推荐结果必须按商家分组：商家标题显示商家名，"
                "下一行必须展示完整菜单链接，并写成 "
                "[完整URL](完整URL)；同一商家的多个菜品合并在该商家下，"
                "菜品按 rank 排列，必须保留分类、价格、辣度、月售、"
                "商家评分、距离、配送费、推荐分、各维度得分、历史点单、"
                "偏好匹配和推荐理由；数据足够时不要减少到 10 条以下。\n"
                "10. “不辣”严格表示 spicy_level = 0；"
                "微辣、中辣、重辣分别对应 1、3、5。\n"
                "11. 多表查询必须使用清晰别名；查询结果最多 100 行。\n"
                "12. 回答使用简洁中文，并说明关键偏好或筛选条件。\n"
                "13. 用户本轮明确指定某道菜时，该菜优先推荐，并临时"
                "覆盖长期忌口；本轮结束后仍保留 avoided_foods，"
                "不得删除或改写长期画像。\n"
                "14. 用户点击、收藏、加购、忽略、评分时调用 "
                "record_user_feedback；查看画像调用 get_user_profile；"
                "只有用户明确要求重置时才调用 clear_user_profile。\n"
            ),
        }

    def _refresh_system_message(self) -> None:
        if self.messages:
            self.messages[0] = self._build_system_message()

    def _rebuild_messages(self) -> None:
        messages = [self._build_system_message()]
        summary = self.storage.get_session_summary(self.session_id)
        if summary:
            messages.append(
                {
                    "role": "system",
                    "content": f"之前会话的长期摘要：\n{summary}",
                }
            )
        messages.extend(
            self.storage.load_pending_messages(self.session_id)
        )
        self.messages = messages

    def _append_message(
        self,
        message: dict[str, Any],
    ) -> None:
        self.messages.append(message)
        self.storage.append_message(
            self.session_id,
            message["role"],
            message.get("content", ""),
            tool_call_id=message.get("tool_call_id"),
            tool_calls=message.get("tool_calls"),
            tool_name=message.get("name"),
        )

    def _capture_explicit_preferences(self, question: str) -> None:
        changed = False
        if re.search(r"不吃辣|不要辣|忌辣|不能吃辣", question):
            self.storage.set_preference(
                self.user_id,
                "spicy_max",
                0,
                source="inferred",
            )
            changed = True

        budget_match = re.search(
            r"(?:预算|最多|不超过)\s*(\d+(?:\.\d+)?)\s*元?",
            question,
        )
        if not budget_match:
            budget_match = re.search(
                r"(\d+(?:\.\d+)?)\s*元(?:以内|以下)",
                question,
            )
        if budget_match:
            self.storage.set_preference(
                self.user_id,
                "budget_max",
                float(budget_match.group(1)),
                source="inferred",
            )
            changed = True

        categories = [
            category
            for category in [
                "川菜",
                "粤菜",
                "湘菜",
                "鲁菜",
                "苏菜",
                "浙菜",
                "闽菜",
                "徽菜",
                "东北菜",
                "火锅",
                "烧烤",
                "韩餐",
                "日料",
                "西餐",
                "轻食",
                "面食",
            ]
            if category in question
        ]

        negative_terms = self._extract_terms(
            question,
            r"(?:不吃|不要吃|不能吃|忌口|忌|讨厌)"
            r"([\u4e00-\u9fffA-Za-z0-9]{1,12}?)"
            r"(?=[，。！？、,\s；;]|$)",
        )
        positive_terms = self._extract_terms(
            question,
            r"(?:喜欢|爱吃|偏好)(?:吃)?"
            r"([\u4e00-\u9fffA-Za-z0-9]{1,12}?)"
            r"(?=[，。！？、,\s；;]|$)",
        )

        avoided_categories = [
            term for term in negative_terms if term in categories
        ]
        avoided_foods = [
            term
            for term in negative_terms
            if term not in categories and term not in {"辣", "辣椒"}
        ]
        preferred_categories = [
            term for term in positive_terms if term in categories
        ]
        preferred_foods = [
            term for term in positive_terms if term not in categories
        ]
        if self._merge_preference_values(
            "avoided_categories",
            avoided_categories,
        ):
            changed = True
        if self._merge_preference_values(
            "avoided_foods",
            avoided_foods,
        ):
            changed = True
        if self._merge_preference_values(
            "preferred_categories",
            preferred_categories,
        ):
            changed = True
        if self._merge_preference_values(
            "preferred_foods",
            preferred_foods,
        ):
            changed = True

        if changed:
            self._refresh_system_message()

    @staticmethod
    def _extract_terms(
        question: str,
        pattern: str,
    ) -> list[str]:
        terms: list[str] = []
        for match in re.finditer(pattern, question):
            term = match.group(1).strip("的了吧呢 ")
            if term and term not in terms:
                terms.append(term)
        return terms

    def _merge_preference_values(
        self,
        key: str,
        values: list[str],
    ) -> bool:
        if not values:
            return False
        preferences = self.storage.get_preferences(self.user_id)
        existing = preferences.get(key, [])
        if isinstance(existing, str):
            existing = [existing]
        merged = list(dict.fromkeys([*existing, *values]))
        if merged == existing:
            return False
        self.storage.set_preference(
            self.user_id,
            key,
            merged,
            source="conversation",
        )
        return True

    @staticmethod
    def _print_tool_result(
        tool_name: str,
        arguments: dict[str, Any],
        result: str,
    ) -> None:
        if tool_name == "execute_sql":
            print(f"\n[SQL]\n{arguments.get('query', '')}")
            payload = json.loads(result)
            query_result = QueryResult(
                columns=payload.get("columns", []),
                rows=payload.get("rows", []),
                truncated=payload.get("truncated", False),
            )
            print(
                f"\n[数据库结果] {query_result.to_dict()['row_count']} 行"
                + ("（已截断）" if query_result.truncated else "")
            )
            print(format_table(query_result))
            return

        if tool_name == "recommend_dishes":
            payload = json.loads(result)
            fallback = bool(
                payload and payload[0].get("category_fallback")
            )
            suffix = "，数据库暂无请求菜系，已启用回退模式" if fallback else ""
            print(f"[已生成 {len(payload)} 条推荐{suffix}]")
            return

        display = result if len(result) <= 2000 else result[:2000] + "..."
        print(f"\n[工具 {tool_name}]\n{display}")

    def _serialize_for_summary(
        self,
        messages: list[dict[str, Any]],
    ) -> str:
        lines: list[str] = []
        for message in messages:
            role = message["role"]
            content = str(message.get("content") or "")
            if len(content) > 1200:
                content = content[:1200] + "..."
            if message.get("tool_calls"):
                tool_names = [
                    item.get("function", {}).get("name", "unknown")
                    for item in message["tool_calls"]
                ]
                content += f" [调用工具：{', '.join(tool_names)}]"
            lines.append(f"{role}: {content}")
        return "\n".join(lines)

    @staticmethod
    def _render_recommendation_markdown(
        recommendations: list[dict[str, Any]],
    ) -> str:
        def cell(value: Any) -> str:
            return str(value).replace("|", "\\|").replace("\n", " ")

        def rating_text(value: Any) -> str:
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                return "暂无"
            return "暂无" if numeric <= 0 else f"{numeric:g}"

        base_url = os.getenv(
            "MEITUAN_SIM_BASE_URL",
            "http://127.0.0.1:18080",
        ).rstrip("/")

        groups: dict[str, list[dict[str, Any]]] = {}
        for item in recommendations:
            key = str(
                item.get("e_poi_id")
                or item.get("restaurant_id")
                or item.get("restaurant_name")
            )
            groups.setdefault(key, []).append(item)

        ordered_groups = sorted(
            groups.values(),
            key=lambda group: min(
                int(item.get("rank") or 999999)
                for item in group
            ),
        )

        headers = [
            "排名",
            "菜品",
            "分类",
            "价格",
            "辣度",
            "月售",
            "商家评分",
            "距离",
            "配送费",
            "推荐分",
            "维度得分",
            "历史点单",
            "偏好匹配",
            "推荐理由",
        ]
        lines: list[str] = []

        for merchant_index, group in enumerate(ordered_groups, start=1):
            first = group[0]
            merchant_name = str(first.get("restaurant_name") or "")
            e_poi_id = first.get("e_poi_id")
            if e_poi_id:
                menu_url = (
                    f"{base_url}/menu?ePoiId="
                    f"{quote(str(e_poi_id), safe='')}"
                )
                merchant_heading = f"### {merchant_index}. {merchant_name}"
                merchant_link = f"[{menu_url}]({menu_url})"
            else:
                merchant_heading = f"### {merchant_index}. {merchant_name}"
                merchant_link = "暂无菜单链接"

            lines.append(
                merchant_heading
                + (
                    f" · 评分 {rating_text(first.get('rating'))}"
                    f" · 距离 {first.get('distance_km')} km"
                    f" · 配送费 {first.get('delivery_fee')} 元"
                )
            )
            lines.append(f"**商家链接：** {merchant_link}")
            lines.append("")
            lines.append("| " + " | ".join(headers) + " |")
            lines.append(
                "|" + "|".join(["---"] * len(headers)) + "|"
            )
            for item in sorted(
                group,
                key=lambda entry: int(entry.get("rank") or 999999),
            ):
                values = [
                    item.get("rank"),
                    item.get("dish_name"),
                    item.get("category"),
                    f'{item.get("price")} 元',
                    item.get("spicy_level"),
                    item.get("month_sales"),
                    rating_text(item.get("rating")),
                    f'{item.get("distance_km")} km',
                    f'{item.get("delivery_fee")} 元',
                    item.get("score"),
                    (
                        f'热度 {item.get("hot_score")}；'
                        f'评分 {item.get("rating_score")}；'
                        f'价格 {item.get("price_score")}；'
                        f'距离 {item.get("distance_score")}；'
                        f'配送 {item.get("delivery_score")}；'
                        f'辣度 {item.get("spicy_score")}；'
                        f'菜系 {item.get("cuisine_score")}'
                    ),
                    f'{item.get("user_order_count", 0)} 次',
                    (
                        f'预算：'
                        f'{"符合" if item.get("meets_budget") else "超出"}；'
                        f'辣度：'
                        f'{"符合" if item.get("meets_spicy_preference") else "超出"}'
                    ),
                    "；".join(item.get("reasons", [])),
                ]
                lines.append(
                    "| "
                    + " | ".join(cell(value) for value in values)
                    + " |"
                )
            lines.append("")

        return "\n".join(lines).rstrip()

    def _maybe_summarize(self) -> bool:
        stats = self.storage.pending_message_stats(self.session_id)
        if (
            stats["message_count"] < MAX_CONTEXT_MESSAGES
            and stats["content_length"] < MAX_CONTEXT_CHARS
        ):
            return False

        messages = self.storage.load_messages_to_summarize(
            self.session_id,
            keep_last=SUMMARY_KEEP_LAST,
        )
        if not messages:
            return False

        existing_summary = self.storage.get_session_summary(
            self.session_id
        )
        transcript = self._serialize_for_summary(messages)
        response = CLIENT.chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "压缩外卖助手的历史对话。保留用户长期偏好、"
                        "订单事实、已推荐内容、未解决问题和重要约束。"
                        "不要添加对话中没有的信息，只输出摘要正文。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"已有摘要：\n{existing_summary or '无'}\n\n"
                        f"新增历史：\n{transcript}"
                    ),
                },
            ],
            temperature=0.0,
        )
        summary = (response.choices[0].message.content or "").strip()
        if not summary:
            return False

        self.storage.update_session_summary(self.session_id, summary)
        self.storage.mark_messages_summarized(
            self.session_id,
            keep_last=SUMMARY_KEEP_LAST,
        )
        self._rebuild_messages()
        return True

    @staticmethod
    def _is_recommendation_request(question: str) -> bool:
        return bool(
            re.search(
                r"推荐|来一份|想要一份|给我一份|(?<!不)想吃|"
                r"吃什么|挑选|外卖|就要|指定",
                question,
            )
            and not re.search(
                r"公式|怎么算|算法|得分|为什么",
                question,
            )
        )

    @staticmethod
    def _requested_category(question: str) -> str | None:
        categories = [
            "川菜",
            "粤菜",
            "湘菜",
            "鲁菜",
            "苏菜",
            "浙菜",
            "闽菜",
            "徽菜",
            "东北菜",
            "火锅",
            "烧烤",
            "韩餐",
            "日料",
            "西餐",
            "轻食",
            "面食",
        ]
        return next(
            (category for category in categories if category in question),
            None,
        )

    def _build_recommendation_content(
        self,
        recommendations: list[dict[str, Any]],
    ) -> str:
        recommendation_table = self._render_recommendation_markdown(
            recommendations
        )
        if (
            recommendations
            and recommendations[0].get("category_fallback")
        ):
            requested_category = recommendations[0].get(
                "requested_category"
            )
            heading = (
                f"数据库中暂无“{requested_category}”，"
                "已放宽菜系条件，并保留预算和辣度偏好参与评分。"
                "以下结果按推荐得分从高到低排列："
            )
        else:
            heading = "按推荐得分从高到低排列："
        return f"{heading}\n\n{recommendation_table}"

    def run(
        self,
        question: str,
        verbose: bool = True,
        on_token: TextCallback | None = None,
        on_phase: Callable[[str], None] | None = None,
    ) -> str:
        wants_recommendation = self._is_recommendation_request(question)
        recommendation_tool_used = False

        def emit_text(text: str) -> None:
            if on_phase is not None:
                on_phase("streaming")
            if on_token is not None:
                on_token(text)

        self._capture_explicit_preferences(question)
        self.storage.record_event(
            self.user_id,
            "search",
            session_id=self.session_id,
            search_query=question,
            context={"source": "nl2sql_cli"},
        )
        self._append_message({"role": "user", "content": question})

        requested_dish = (
            self.storage.find_dish_name_in_text(question)
            if wants_recommendation
            else None
        )
        if requested_dish:
            preferences = self.storage.get_preferences(self.user_id)
            recommendations = self.storage.recommend_dishes(
                self.user_id,
                limit=12,
                max_price=preferences.get("budget_max"),
                max_spicy=preferences.get("spicy_max"),
                session_id=self.session_id,
                requested_dish=requested_dish,
            )
            content = self._build_recommendation_content(recommendations)
            emit_text(content)
            self._append_message(
                {"role": "assistant", "content": content}
            )
            return content

        for _ in range(MAX_LOOPS):
            if on_phase is not None:
                on_phase("thinking")

            message = stream_chat_completion(
                CLIENT,
                on_text=None if wants_recommendation else emit_text,
                model=MODEL,
                messages=self.messages,
                tools=self.tool_registry.definitions(),
                tool_choice=(
                    {
                        "type": "function",
                        "function": {"name": "recommend_dishes"},
                    }
                    if wants_recommendation
                    and not recommendation_tool_used
                    else "auto"
                ),
                temperature=0.0,
            )

            if not message.get("tool_calls"):
                if wants_recommendation and not recommendation_tool_used:
                    preferences = self.storage.get_preferences(
                        self.user_id
                    )
                    recommendations = self.storage.recommend_dishes(
                        self.user_id,
                        limit=12,
                        max_price=preferences.get("budget_max"),
                        max_spicy=preferences.get("spicy_max"),
                        category=self._requested_category(question),
                        session_id=self.session_id,
                        requested_dish=requested_dish,
                    )
                    content = self._build_recommendation_content(
                        recommendations
                    )
                    emit_text(content)
                    self._append_message(
                        {"role": "assistant", "content": content}
                    )
                    return content

                content = message.get("content") or ""
                self._append_message(
                    {"role": "assistant", "content": content}
                )
                self._maybe_summarize()
                return content

            assistant_tool_calls = message["tool_calls"]
            self._append_message(
                {
                    "role": "assistant",
                    "content": message.get("content") or "",
                    "tool_calls": assistant_tool_calls,
                }
            )

            recommendation_table: str | None = None
            if on_phase is not None:
                on_phase("tool")
            for tool_call in message["tool_calls"]:
                tool_name = tool_call["function"]["name"]
                if tool_name == "recommend_dishes":
                    recommendation_tool_used = True
                try:
                    arguments = json.loads(
                        tool_call["function"]["arguments"]
                    )
                    tool_content = self.tool_registry.execute(
                        tool_name,
                        arguments,
                    )
                except Exception as exc:
                    arguments = {}
                    tool_content = json.dumps(
                        {"error": str(exc)},
                        ensure_ascii=False,
                    )

                if verbose:
                    self._print_tool_result(
                        tool_name,
                        arguments,
                        tool_content,
                    )

                if (
                    tool_name == "recommend_dishes"
                    and "error" not in json.loads(tool_content)
                ):
                    recommendations = json.loads(tool_content)
                    recommendation_table = (
                        self._render_recommendation_markdown(
                            recommendations
                        )
                    )

                self._append_message(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "content": tool_content,
                    }
                )

            if recommendation_table is not None:
                recommendations = json.loads(tool_content)
                content = self._build_recommendation_content(
                    recommendations
                )
                emit_text(content)
                self._append_message(
                    {"role": "assistant", "content": content}
                )
                self._maybe_summarize()
                return content

        content = "查询步骤过多，已停止执行。"
        emit_text(content)
        return content


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="使用本地模型查询、记忆和推荐外卖"
    )
    parser.add_argument(
        "question",
        nargs="*",
        help="直接提交一个自然语言问题；不填则进入交互模式",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"SQLite 数据库路径，默认：{DEFAULT_DB_PATH}",
    )
    parser.add_argument(
        "--schema",
        action="store_true",
        help="只显示模型可见的数据库结构",
    )
    parser.add_argument(
        "--no-sql",
        action="store_true",
        help="不在终端显示实际执行的 SQL 和查询结果",
    )
    parser.add_argument(
        "--user-id",
        default=os.getenv("NL2SQL_USER_ID", "default"),
        help="用户 ID，用于恢复该用户的偏好和订单",
    )
    parser.add_argument(
        "--session-id",
        default=os.getenv("NL2SQL_SESSION_ID", "default"),
        help="会话 ID，用于恢复持久化对话记忆",
    )
    parser.add_argument(
        "--chars-per-second",
        type=float,
        default=30.0,
        help="流式文字打印速度，默认每秒 30 个字符；设为 0 不限制",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.db.resolve() == DEFAULT_DB_PATH:
        initialize_database(verbose=False)

    database = TakeoutDatabase(args.db)

    if args.schema:
        print(database.schema_text())
        return

    storage = TakeoutStorage(args.db)
    agent = NL2SQLAgent(
        database,
        storage,
        user_id=args.user_id,
        session_id=args.session_id,
    )
    verbose = not args.no_sql
    thinking = ThinkingIndicator()
    paced_printer = PacedTextPrinter(args.chars_per_second)

    def emit_output(text: str) -> None:
        thinking.stop()
        paced_printer.write(text)

    def stream_answer(question: str) -> str:
        print("\n[回答]\n", end="", flush=True)
        thinking.start()
        try:
            return agent.run(
                question,
                verbose=verbose,
                on_token=emit_output,
                on_phase=thinking.set_phase,
            )
        finally:
            thinking.stop()
            print()

    if args.question:
        question = " ".join(args.question).strip()
        stream_answer(question)
        return

    stats = storage.pending_message_stats(args.session_id)
    summary_loaded = bool(
        storage.get_session_summary(args.session_id)
    )
    print("===== 外卖智能助手 =====")
    print(
        f"用户：{args.user_id}，会话：{args.session_id}，"
        f"已恢复消息：{stats['message_count']} 条，"
        f"摘要：{'有' if summary_loaded else '无'}"
    )
    print("输入自然语言问题，输入 quit 或 exit 退出。")
    while True:
        question = input("\n请输入问题：").strip()
        if question.lower() in {"quit", "exit"}:
            print("已退出。")
            break
        if not question:
            continue
        stream_answer(question)


if __name__ == "__main__":
    main()
