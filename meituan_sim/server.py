"""美团开放平台菜品接口的本地模拟 HTTP 服务。

除了模拟美团开放平台的签名接口，本服务还提供新版前端所需的 JSON API
与静态资源，浏览器入口为 http://127.0.0.1:18080/ 。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, parse_qsl, unquote, urlencode, urlparse

from .protocol import (
    MeituanConfig,
    ProtocolError,
    error_response,
    parse_biz,
    success_response,
    verify_request,
)
from .repository import MeituanDishRepository
from storage import TakeoutStorage


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = ROOT_DIR / "data" / "agent.db"
WEB_DIR = Path(__file__).resolve().parent / "web"

STATIC_MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
}

APP_ROUTES = {"/", "/stores", "/menu", "/profile", "/search"}

PREFERENCE_KEYS = {
    "preferred_categories",
    "avoided_categories",
    "preferred_foods",
    "avoided_foods",
    "budget_max",
    "spicy_max",
    "min_rating",
    "delivery_fee_max",
    "notes",
}

LIST_PREFERENCE_KEYS = {
    "preferred_categories",
    "avoided_categories",
    "preferred_foods",
    "avoided_foods",
}


def is_open_now(business_hours: Any) -> bool | None:
    """根据营业时间判断当前是否营业，支持跨天营业时间。"""
    text = str(business_hours or "").strip()
    if "-" not in text:
        return None
    start_text, end_text = [part.strip() for part in text.split("-", 1)]
    try:
        start_hour, start_minute = [
            int(value) for value in start_text.split(":")[:2]
        ]
        end_hour, end_minute = [
            int(value) for value in end_text.split(":")[:2]
        ]
    except (TypeError, ValueError):
        return None

    now = datetime.now()
    current = now.hour * 60 + now.minute
    start = start_hour * 60 + start_minute
    end = end_hour * 60 + end_minute
    if end <= start:
        return current >= start or current < end
    return start <= current < end


class MeituanSimServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        config: MeituanConfig,
        repository: MeituanDishRepository,
        storage: TakeoutStorage,
        default_e_poi_id: str = "4213",
        default_user_id: str = "default",
    ):
        super().__init__(server_address, MeituanRequestHandler)
        self.meituan_config = config
        self.repository = repository
        self.storage = storage
        self.default_e_poi_id = default_e_poi_id
        self.default_user_id = default_user_id
        self.chat_lock = threading.Lock()


class MeituanRequestHandler(BaseHTTPRequestHandler):
    server: MeituanSimServer
    protocol_version = "HTTP/1.1"

    def handle_one_request(self) -> None:
        """浏览器刷新时常会主动断开连接，忽略这类正常的中断。"""
        try:
            super().handle_one_request()
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            self.close_connection = True

    # ------------------------------------------------------------------
    # 路由
    # ------------------------------------------------------------------
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/chat":
            self.send_response(302)
            self.send_header("Location", "/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path in APP_ROUTES:
            self._serve_app()
            return
        if path.startswith("/assets/"):
            self._serve_asset(unquote(path[len("/assets/") :]))
            return
        if path == "/health":
            self._send_json(
                200,
                success_response(
                    {
                        "service": "meituan-sim",
                        "status": "up",
                        "menuUrl": "/",
                        "chatUrl": "/",
                        "api": [
                            "/api/restaurants",
                            "/api/menu?ePoiId=4213",
                            "/api/recommendations",
                            "/api/profile",
                            "/api/search?q=面",
                            "/api/chat/status",
                            "/api/chat",
                        ],
                    }
                ),
            )
            return
        if path == "/api/restaurants":
            self._api_restaurants(parsed.query)
            return
        if path == "/api/menu":
            self._api_menu(parsed.query)
            return
        if path == "/api/recommendations":
            self._api_recommendations(parsed.query)
            return
        if path == "/api/profile":
            self._api_profile()
            return
        if path == "/api/search":
            self._api_search(parsed.query)
            return
        if path == "/api/chat/status":
            self._api_chat_status()
            return
        if path == "/api/chat/history":
            self._api_chat_history(parsed.query)
            return

        self._send_json(
            404,
            error_response("OP_NOT_FOUND", "接口不存在"),
        )

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/action":
            self._api_action()
            return
        if path == "/api/preferences":
            self._api_preferences()
            return
        if path == "/api/chat":
            self._api_chat()
            return
        if path == "/ui/action":
            self._handle_ui_action()
            return

        handler = self._route(path)
        if handler is None:
            self._send_json(
                404,
                error_response("OP_NOT_FOUND", f"接口不存在：{path}"),
            )
            return

        try:
            params = self._read_form_body()
            verify_request(params, self.server.meituan_config)
            biz = parse_biz(params)
            data = handler(biz)
            self._send_json(200, success_response(data))
        except ProtocolError as exc:
            self._send_json(
                400,
                error_response(exc.code, exc.message),
            )
        except Exception as exc:
            self._send_json(
                500,
                error_response(
                    "OP_SYSTEM_ERROR",
                    f"服务异常：{exc}",
                ),
            )

    # ------------------------------------------------------------------
    # 请求体读取
    # ------------------------------------------------------------------
    def _read_form_body(self) -> dict[str, str]:
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0:
            raise ProtocolError(
                "OP_SYSTEM_PARAM_ERROR",
                "POST 请求体不能为空",
            )
        if content_length > 2_000_000:
            raise ProtocolError(
                "OP_SYSTEM_PARAM_ERROR",
                "请求体超过 2 MB",
            )
        raw_body = self.rfile.read(content_length)
        return {
            key: value
            for key, value in parse_qsl(
                raw_body.decode("utf-8"),
                keep_blank_values=True,
            )
        }

    def _read_json_body(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0:
            raise ValueError("请求体不能为空")
        if content_length > 1_000_000:
            raise ValueError("请求体超过 1 MB")
        raw_body = self.rfile.read(content_length)
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("请求体必须是合法的 JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("请求体必须是 JSON 对象")
        return payload

    # ------------------------------------------------------------------
    # 行为记录（网页表单与前端 API 共用）
    # ------------------------------------------------------------------
    def _perform_ui_action(
        self,
        form: dict[str, str],
    ) -> dict[str, Any]:
        action = form.get("action", "")
        dish_name = form.get("dish_name", "")
        e_poi_id = form.get("e_poi_id") or self.server.default_e_poi_id
        user_id = self.server.default_user_id

        if action == "search":
            query = (form.get("query") or "").strip()
            if not query:
                raise ValueError("搜索内容不能为空")
            result = self.server.storage.record_event(
                user_id,
                "search",
                session_id="meituan_sim_web",
                search_query=query,
                context={
                    "source": "meituan_sim_web",
                    "ePoiId": e_poi_id,
                },
            )
            return {
                "message": f"已记录搜索：{query}",
                "redirect": "/search",
                "e_poi_id": e_poi_id,
                "event": result,
            }

        if action == "order":
            if not dish_name:
                raise ValueError("缺少菜品信息")
            result = self.server.storage.record_order(
                user_id,
                dish_name,
                source="meituan_sim_web",
            )
            return {
                "message": f"已下单：{dish_name}",
                "redirect": "/menu",
                "e_poi_id": e_poi_id,
                "order": result,
            }

        if action in {
            "favorite",
            "dismiss",
            "click",
            "detail_view",
            "cart_add",
            "not_interested",
        }:
            if not dish_name:
                raise ValueError("缺少菜品信息")
            result = self.server.storage.record_event(
                user_id,
                action,
                dish_name=dish_name,
                session_id="meituan_sim_web",
                context={
                    "source": "meituan_sim_web",
                    "ePoiId": e_poi_id,
                },
            )
            action_name = {
                "favorite": "已收藏",
                "dismiss": "已忽略",
                "click": "已记录点击",
                "detail_view": "已查看详情",
                "cart_add": "已加入购物车",
                "not_interested": "已标记不感兴趣",
            }[action]
            return {
                "message": f"{action_name}：{dish_name}",
                "redirect": "/menu",
                "e_poi_id": e_poi_id,
                "event": result,
            }

        if action == "rating":
            if not dish_name:
                raise ValueError("缺少菜品信息")
            try:
                rating = float(form.get("rating") or 0)
            except (TypeError, ValueError) as exc:
                raise ValueError("评分必须是数字") from exc
            if not 1 <= rating <= 5:
                raise ValueError("评分需要在 1-5 之间")
            result = self.server.storage.record_event(
                user_id,
                "rating",
                dish_name=dish_name,
                session_id="meituan_sim_web",
                context={
                    "source": "meituan_sim_web",
                    "rating": rating,
                    "ePoiId": e_poi_id,
                },
            )
            return {
                "message": f"已评分：{dish_name} {rating:g} 分",
                "redirect": "/menu",
                "e_poi_id": e_poi_id,
                "event": result,
            }

        raise ValueError(f"不支持的操作：{action}")

    def _handle_ui_action(self) -> None:
        form: dict[str, str] = {}
        try:
            form = self._read_form_body()
            outcome = self._perform_ui_action(form)
        except Exception as exc:
            outcome = {
                "message": f"操作失败：{exc}",
                "redirect": "/menu",
                "e_poi_id": self.server.default_e_poi_id,
            }

        if outcome["redirect"] == "/search":
            location = f"/search?{urlencode({'q': form.get('query', '')})}"
        elif outcome["redirect"] == "/profile":
            location = f"/profile?{urlencode({'message': outcome['message']})}"
        else:
            location = "/menu?" + urlencode(
                {
                    "ePoiId": outcome["e_poi_id"],
                    "message": outcome["message"],
                }
            )
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    # ------------------------------------------------------------------
    # 前端 JSON API
    # ------------------------------------------------------------------
    @staticmethod
    def _param(
        params: dict[str, list[str]],
        key: str,
        default: str = "",
    ) -> str:
        values = params.get(key)
        return str(values[0]).strip() if values else default

    @staticmethod
    def _optional_number(
        params: dict[str, list[str]],
        key: str,
    ) -> float | None:
        raw = MeituanRequestHandler._param(params, key)
        if not raw:
            return None
        try:
            return float(raw)
        except ValueError:
            return None

    def _api_restaurants(self, query_string: str) -> None:
        params = parse_qs(query_string)
        keyword = self._param(params, "q").casefold()
        category = self._param(params, "category")
        sort_key = self._param(params, "sort", "rating") or "rating"
        max_fee = self._optional_number(params, "max_fee")

        restaurants = self.server.repository.list_restaurants()
        category_buckets: dict[str, dict[str, Any]] = {}
        for item in restaurants:
            name = str(item.get("category") or "其他")
            bucket = category_buckets.setdefault(
                name,
                {"name": name, "count": 0, "dishes": 0},
            )
            bucket["count"] += 1
            bucket["dishes"] += int(item.get("dish_count") or 0)

        filtered: list[dict[str, Any]] = []
        for item in restaurants:
            if (
                category
                and category not in {"全部", "all"}
                and item["category"] != category
            ):
                continue
            if (
                max_fee is not None
                and float(item.get("delivery_fee") or 0) > max_fee
            ):
                continue
            if keyword:
                haystack = (
                    f'{item["name"]} {item["category"]}'
                ).casefold()
                if keyword not in haystack:
                    continue
            enriched = dict(item)
            enriched["is_open"] = is_open_now(
                item.get("business_hours")
            )
            filtered.append(enriched)

        sorters: dict[str, Callable[[dict[str, Any]], Any]] = {
            "rating": lambda item: (
                -float(item.get("rating") or 0),
                float(item.get("distance_km") or 0),
            ),
            "distance": lambda item: (
                float(item.get("distance_km") or 0),
                -float(item.get("rating") or 0),
            ),
            "delivery": lambda item: (
                float(item.get("delivery_fee") or 0),
                float(item.get("distance_km") or 0),
            ),
            "min_order": lambda item: (
                float(item.get("min_order") or 0),
                float(item.get("distance_km") or 0),
            ),
            "dishes": lambda item: (
                -int(item.get("dish_count") or 0),
                -float(item.get("rating") or 0),
            ),
        }
        filtered.sort(key=sorters.get(sort_key, sorters["rating"]))

        self._send_json(
            200,
            {
                "restaurants": filtered,
                "categories": sorted(
                    category_buckets.values(),
                    key=lambda item: (-item["count"], item["name"]),
                ),
                "stats": {
                    "restaurants": len(restaurants),
                    "dishes": sum(
                        int(item.get("dish_count") or 0)
                        for item in restaurants
                    ),
                    "categories": len(category_buckets),
                    "open_now": sum(
                        1
                        for item in restaurants
                        if is_open_now(item.get("business_hours"))
                    ),
                },
            },
        )

    def _api_menu(self, query_string: str) -> None:
        params = parse_qs(query_string)
        e_poi_id = (
            self._param(params, "ePoiId")
            or self._param(params, "epoiId")
            or self.server.default_e_poi_id
        )
        try:
            restaurant = self.server.repository.get_restaurant(e_poi_id)
            dishes = self.server.repository.menu_items(e_poi_id)
        except ProtocolError as exc:
            self._send_json(404, {"ok": False, "error": exc.message})
            return

        restaurant["is_open"] = is_open_now(
            restaurant.get("business_hours")
        )
        buckets: dict[str, int] = {}
        for dish in dishes:
            name = dish["category_name"] or "其他"
            buckets[name] = buckets.get(name, 0) + 1

        self._send_json(
            200,
            {
                "restaurant": restaurant,
                "dishes": dishes,
                "categories": [
                    {"name": name, "count": count}
                    for name, count in buckets.items()
                ],
                "preferences": self.server.storage.get_preferences(
                    self.server.default_user_id
                ),
            },
        )

    def _api_recommendations(self, query_string: str) -> None:
        params = parse_qs(query_string)
        raw_limit = self._param(params, "limit", "8")
        try:
            limit = max(1, min(int(raw_limit), 20))
        except ValueError:
            limit = 8
        max_spicy = self._optional_number(params, "max_spicy")
        try:
            recommendations = self.server.storage.recommend_dishes(
                self.server.default_user_id,
                limit=limit,
                max_price=self._optional_number(params, "max_price"),
                max_spicy=(
                    int(max_spicy) if max_spicy is not None else None
                ),
                category=self._param(params, "category") or None,
                min_rating=self._optional_number(params, "min_rating"),
            )
        except Exception as exc:
            self._send_json(
                500,
                {"ok": False, "error": f"推荐计算失败：{exc}"},
            )
            return

        self._send_json(
            200,
            {
                "recommendations": recommendations,
                "preferences": self.server.storage.get_preferences(
                    self.server.default_user_id
                ),
            },
        )

    def _api_profile(self) -> None:
        user_id = self.server.default_user_id
        summary = self.server.storage.get_profile_summary(
            user_id,
            limit=50,
        )
        events = self.server.storage.list_user_events(
            user_id,
            limit=200,
        )
        orders = self.server.storage.recent_orders(user_id, limit=20)
        stats = {
            "events": len(events),
            "favorites": sum(
                1
                for event in events
                if event["event_type"] == "favorite"
            ),
            "orders": len(orders),
            "tried_dishes": len(
                {
                    event["dish_id"]
                    for event in events
                    if event.get("dish_id")
                }
            ),
        }
        self._send_json(
            200,
            {
                "summary": summary,
                "events": events,
                "orders": orders,
                "stats": stats,
            },
        )

    def _api_search(self, query_string: str) -> None:
        params = parse_qs(query_string)
        query = self._param(params, "q")
        if not query:
            self._send_json(
                200,
                {"query": "", "restaurants": [], "dishes": []},
            )
            return

        needle = query.casefold()
        restaurants = []
        for item in self.server.repository.list_restaurants():
            haystack = (
                f'{item["name"]} {item["category"]}'
            ).casefold()
            if needle in haystack:
                enriched = dict(item)
                enriched["is_open"] = is_open_now(
                    item.get("business_hours")
                )
                restaurants.append(enriched)

        self._send_json(
            200,
            {
                "query": query,
                "restaurants": restaurants[:8],
                "dishes": self.server.repository.search_dishes(
                    query,
                    limit=24,
                ),
            },
        )

    @staticmethod
    def _chat_session_id(value: Any) -> str:
        text = str(value or "web_chat").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", text):
            raise ValueError("会话 ID 不合法")
        return text

    def _ollama_status(self) -> dict[str, Any]:
        model = os.getenv("MODEL_NAME", "qwen2:7b-instruct")
        try:
            with urllib.request.urlopen(
                "http://127.0.0.1:11434/api/tags",
                timeout=2,
            ) as response:
                payload = json.loads(
                    response.read().decode("utf-8")
                )
            names = [
                str(item.get("name") or "")
                for item in payload.get("models", [])
                if isinstance(item, dict)
            ]
            ready = any(
                name == model or name.startswith(f"{model}:")
                for name in names
            )
            return {
                "ollama": True,
                "ready": ready,
                "model": model,
                "models": names,
            }
        except Exception as exc:
            return {
                "ollama": False,
                "ready": False,
                "model": model,
                "models": [],
                "error": str(exc),
            }

    def _api_chat_status(self) -> None:
        self._send_json(200, self._ollama_status())

    def _api_chat_history(self, query_string: str) -> None:
        params = parse_qs(query_string)
        try:
            session_id = self._chat_session_id(
                self._param(params, "session_id", "web_chat")
            )
        except ValueError as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
            return
        messages = self.server.storage.list_chat_messages(
            session_id,
            limit=60,
        )
        self._send_json(
            200,
            {"ok": True, "session_id": session_id, "messages": messages},
        )

    def _api_chat(self) -> None:
        try:
            payload = self._read_json_body()
            message = str(payload.get("message") or "").strip()
            if not message:
                raise ValueError("消息不能为空")
            if len(message) > 2000:
                raise ValueError("单条消息不能超过 2000 个字符")
            session_id = self._chat_session_id(
                payload.get("session_id")
            )
        except ValueError as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
            return

        status = self._ollama_status()
        if not status["ready"]:
            if not status["ollama"]:
                error = (
                    "AI 后端未启动。请先双击“启动AI后端.bat”，"
                    "然后再试一次。"
                )
            else:
                error = (
                    f"模型 {status['model']} 未就绪。"
                    "请双击“拉取AI模型.bat”完成下载。"
                )
            self._send_json(
                503,
                {"ok": False, "error": error, **status},
            )
            return

        started = time.time()
        try:
            with self.server.chat_lock:
                from meituan_sim import MeituanClient
                from nl2sql import NL2SQLAgent, TakeoutDatabase

                database = TakeoutDatabase(
                    self.server.repository.db_path
                )
                agent = NL2SQLAgent(
                    database,
                    self.server.storage,
                    user_id=self.server.default_user_id,
                    session_id=session_id,
                    meituan_client=MeituanClient(
                        base_url=(
                            "http://127.0.0.1:"
                            f"{self.server.server_address[1]}"
                        )
                    ),
                )
                answer = agent.run(message, verbose=False)
            answer = str(answer or "").strip()
            if not answer:
                answer = "模型没有返回内容，请换一种问法再试。"
            self._send_json(
                200,
                {
                    "ok": True,
                    "answer": answer,
                    "session_id": session_id,
                    "model": status["model"],
                    "elapsed": round(time.time() - started, 2),
                },
            )
        except Exception as exc:
            detail = str(exc)
            low = detail.lower()
            if any(
                item in low
                for item in (
                    "connection",
                    "connect",
                    "11434",
                    "refused",
                    "timed out",
                    "timeout",
                )
            ):
                message = (
                    "连接本地模型失败。请检查 Ollama 是否运行："
                    "双击“查看AI状态.bat”，或重新启动 AI 后端。"
                )
                code = 503
            else:
                message = f"AI 回答失败：{detail}"
                code = 500
            self._send_json(
                code,
                {"ok": False, "error": message, "detail": detail[:500]},
            )

    def _api_action(self) -> None:
        try:
            payload = self._read_json_body()
            form = {
                str(key): "" if value is None else str(value)
                for key, value in payload.items()
                if key != "rating"
            }
            if payload.get("rating") is not None:
                form["rating"] = str(payload["rating"])
            outcome = self._perform_ui_action(form)
            self._send_json(200, {"ok": True, **outcome})
        except ValueError as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
        except Exception as exc:
            self._send_json(
                500,
                {"ok": False, "error": f"操作失败：{exc}"},
            )

    def _api_preferences(self) -> None:
        try:
            payload = self._read_json_body()
            key = str(payload.get("key") or "").strip()
            if key not in PREFERENCE_KEYS:
                raise ValueError(f"不支持的偏好字段：{key}")
            user_id = self.server.default_user_id
            if payload.get("delete") is True:
                self.server.storage.delete_preference(user_id, key)
            else:
                value = self._coerce_preference(key, payload.get("value"))
                self.server.storage.set_preference(user_id, key, value)
            self._send_json(
                200,
                {
                    "ok": True,
                    "preferences": self.server.storage.get_preferences(
                        user_id
                    ),
                },
            )
        except ValueError as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
        except Exception as exc:
            self._send_json(
                500,
                {"ok": False, "error": f"保存失败：{exc}"},
            )

    @staticmethod
    def _coerce_preference(key: str, value: Any) -> Any:
        if key in LIST_PREFERENCE_KEYS:
            if isinstance(value, str):
                items = [
                    part.strip()
                    for part in value.replace("，", ",").split(",")
                ]
            elif isinstance(value, (list, tuple, set)):
                items = [str(part).strip() for part in value]
            else:
                raise ValueError("该偏好需要传入数组")
            cleaned: list[str] = []
            for item in items:
                if item and item not in cleaned:
                    cleaned.append(item)
            return cleaned

        if key == "notes":
            text = str(value or "").strip()
            if len(text) > 200:
                raise ValueError("备注不能超过 200 个字符")
            return text

        try:
            numeric = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{key} 必须是数字") from exc

        if key == "spicy_max":
            if not 0 <= numeric <= 5:
                raise ValueError("辣度上限需要在 0-5 之间")
            return int(numeric)
        if key == "min_rating":
            if not 0 <= numeric <= 5:
                raise ValueError("最低评分需要在 0-5 之间")
            return round(numeric, 1)
        if key == "budget_max":
            if numeric <= 0:
                raise ValueError("预算上限需要大于 0")
            return round(numeric, 1)
        if key == "delivery_fee_max":
            if numeric < 0:
                raise ValueError("配送费上限不能为负数")
            return round(numeric, 1)
        raise ValueError(f"不支持的偏好字段：{key}")

    # ------------------------------------------------------------------
    # 静态资源
    # ------------------------------------------------------------------
    def _serve_app(self) -> None:
        index = WEB_DIR / "index.html"
        if not index.is_file():
            self._send_json(
                500,
                {
                    "ok": False,
                    "error": "前端资源缺失：meituan_sim/web/index.html",
                },
            )
            return
        self._send_bytes(
            200,
            index.read_bytes(),
            "text/html; charset=utf-8",
            cache_control="no-store",
        )

    def _serve_asset(self, relative: str) -> None:
        relative = relative.replace("\\", "/")
        base = WEB_DIR.resolve()
        try:
            target = (base / relative).resolve()
            target.relative_to(base)
        except (OSError, ValueError):
            self._send_json(
                404,
                error_response("OP_NOT_FOUND", "资源不存在"),
            )
            return
        if not relative or not target.is_file():
            self._send_json(
                404,
                error_response("OP_NOT_FOUND", "资源不存在"),
            )
            return

        self._send_bytes(
            200,
            target.read_bytes(),
            STATIC_MIME_TYPES.get(
                target.suffix.lower(),
                "application/octet-stream",
            ),
            cache_control="no-cache",
        )

    # ------------------------------------------------------------------
    # 美团模拟接口
    # ------------------------------------------------------------------
    def _route(
        self,
        path: str,
    ) -> Callable[[dict[str, Any]], Any] | None:
        routes: dict[str, Callable[[dict[str, Any]], Any]] = {
            "/waimai/dish/batchUpload": self._batch_upload,
            "/waimai/dish/queryListByEPoiId": self._query_dishes,
            "/waimai/ng/dish/queryFoodList": self._query_food_list,
            "/waimai/dish/queryCatList": self._query_categories,
            "/waimai/dish/updatePrice": self._update_price,
            "/waimai/dish/updateStock": self._update_stock,
            "/waimai/dish/delete": self._delete_dish,
        }
        return routes.get(path)

    def _epoi(self, biz: dict[str, Any]) -> str:
        return str(
            biz.get("ePoiId")
            or biz.get("epoiId")
            or self.server.default_e_poi_id
        )

    def _batch_upload(self, biz: dict[str, Any]) -> Any:
        dishes = biz.get("dishes")
        if isinstance(dishes, list) and dishes:
            first_epoi = dishes[0].get("ePoiId") or dishes[0].get(
                "epoiId"
            )
        else:
            first_epoi = None
        e_poi_id = str(first_epoi or self._epoi(biz))
        return self.server.repository.upsert_dishes(e_poi_id, dishes)

    def _query_dishes(self, biz: dict[str, Any]) -> Any:
        return self.server.repository.query_dishes(
            self._epoi(biz),
            offset=int(biz.get("offset") or 0),
            limit=int(biz.get("limit") or 100),
        )

    def _query_food_list(self, biz: dict[str, Any]) -> Any:
        return self.server.repository.query_food_list(
            self._epoi(biz),
            offset=int(biz.get("offset") or 0),
            limit=int(biz.get("limit") or 10),
        )

    def _query_categories(self, biz: dict[str, Any]) -> Any:
        return self.server.repository.query_categories(self._epoi(biz))

    def _update_price(self, biz: dict[str, Any]) -> Any:
        return self.server.repository.update_price(
            biz.get("dishSkuPrices"),
            self._epoi(biz),
        )

    def _update_stock(self, biz: dict[str, Any]) -> Any:
        return self.server.repository.update_stock(
            biz.get("dishSkuStocks"),
            self._epoi(biz),
        )

    def _delete_dish(self, biz: dict[str, Any]) -> Any:
        return self.server.repository.delete_dish(
            str(biz.get("eDishCode") or ""),
            self._epoi(biz),
        )

    # ------------------------------------------------------------------
    # 响应输出
    # ------------------------------------------------------------------
    def _send_bytes(
        self,
        status: int,
        body: bytes,
        content_type: str,
        *,
        cache_control: str | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if cache_control:
            self.send_header("Cache-Control", cache_control)
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        self._send_bytes(
            status,
            body,
            "application/json; charset=utf-8",
            cache_control="no-store",
        )

    def log_message(self, format: str, *args: Any) -> None:
        print(
            f"[meituan-sim] {self.address_string()} "
            f"{format % args}"
        )


def build_server(
    *,
    host: str = "127.0.0.1",
    port: int = 18080,
    db_path: Path = DEFAULT_DB_PATH,
    config: MeituanConfig | None = None,
    default_e_poi_id: str = "4213",
    default_user_id: str | None = None,
) -> MeituanSimServer:
    return MeituanSimServer(
        (host, port),
        config
        or MeituanConfig(
            developer_id=os.getenv("MEITUAN_DEVELOPER_ID", "108999"),
            sign_key=os.getenv("MEITUAN_SIGN_KEY", "test-sign-key"),
            app_auth_token=os.getenv(
                "MEITUAN_APP_AUTH_TOKEN",
                "test-app-auth-token",
            ),
        ),
        MeituanDishRepository(db_path),
        TakeoutStorage(db_path),
        default_e_poi_id,
        default_user_id or os.getenv("NL2SQL_USER_ID", "default"),
    )


def run_server(
    *,
    host: str = "127.0.0.1",
    port: int = 18080,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    server = build_server(
        host=host,
        port=port,
        db_path=db_path,
    )
    print(
        f"美团模拟端已启动：http://{host}:{port} "
        f"(developerId={server.meituan_config.developer_id})"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在停止美团模拟端...")
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="启动本地美团开放平台菜品接口模拟端"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    args = parser.parse_args()
    run_server(
        host=args.host,
        port=args.port,
        db_path=args.db,
    )


if __name__ == "__main__":
    main()
