"""美团开放平台菜品接口的本地模拟 HTTP 服务。"""

from __future__ import annotations

import argparse
import html
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, parse_qsl, quote, urlencode, urlparse

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


def format_rating(value: Any) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "暂无"
    return "暂无" if numeric <= 0 else f"{numeric:g}"


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


class MeituanRequestHandler(BaseHTTPRequestHandler):
    server: MeituanSimServer
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send_json(
                200,
                success_response(
                    {
                        "service": "meituan-sim",
                        "status": "up",
                        "menuUrl": "/stores",
                    }
                ),
            )
            return
        if parsed.path == "/stores":
            restaurants = self.server.repository.list_restaurants()
            self._send_html(
                200,
                self._render_stores(restaurants),
            )
            return
        if parsed.path == "/profile":
            query = parse_qs(parsed.query)
            message = (query.get("message") or [""])[0]
            summary = self.server.storage.get_profile_summary(
                self.server.default_user_id,
                limit=20,
            )
            events = self.server.storage.list_user_events(
                self.server.default_user_id,
                limit=30,
            )
            self._send_html(
                200,
                self._render_profile(summary, events, message),
            )
            return
        if parsed.path == "/menu":
            query = parse_qs(parsed.query)
            message = (query.get("message") or [""])[0]
            e_poi_id = (
                query.get("ePoiId")
                or query.get("epoiId")
                or [self.server.default_e_poi_id]
            )[0]
            try:
                dishes = self.server.repository.query_food_list(
                    e_poi_id,
                    offset=0,
                    limit=199,
                )
                self._send_html(
                    200,
                    self._render_menu(e_poi_id, dishes, message),
                )
            except ProtocolError as exc:
                self._send_html(
                    404,
                    self._render_error(exc.code, exc.message),
                )
            except Exception as exc:
                self._send_html(
                    500,
                    self._render_error("OP_SYSTEM_ERROR", str(exc)),
                )
            return
        self._send_json(
            404,
            error_response("OP_NOT_FOUND", "接口不存在"),
        )

    def do_POST(self) -> None:
        path = urlparse(self.path).path
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

    def _handle_ui_action(self) -> None:
        try:
            form = self._read_form_body()
            action = form.get("action", "")
            dish_id = form.get("dish_id", "")
            dish_name = form.get("dish_name", "")
            e_poi_id = (
                form.get("e_poi_id")
                or self.server.default_e_poi_id
            )

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
                message = f"已记录搜索：{query}"
                redirect_path = "/profile"
            elif action == "order":
                if not dish_name:
                    raise ValueError("缺少菜品信息")
                result = self.server.storage.record_order(
                    user_id,
                    dish_name,
                    source="meituan_sim_web",
                )
                message = f"已下单：{dish_name}"
                redirect_path = "/menu"
            elif action in {
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
                message = f"{action_name}：{dish_name}"
                redirect_path = "/menu"
            elif action == "rating":
                if not dish_name:
                    raise ValueError("缺少菜品信息")
                rating = float(form.get("rating") or 0)
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
                message = f"已评分：{dish_name} {rating:g} 分"
                redirect_path = "/menu"
            else:
                raise ValueError(f"不支持的操作：{action}")
        except Exception as exc:
            e_poi_id = locals().get(
                "e_poi_id",
                self.server.default_e_poi_id,
            )
            message = f"操作失败：{exc}"
            redirect_path = "/menu"

        if redirect_path == "/profile":
            location = f"/profile?{urlencode({'message': message})}"
        else:
            location = (
                f"/menu?{urlencode({'ePoiId': e_poi_id, 'message': message})}"
            )
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

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
            first_epoi = dishes[0].get("ePoiId") or dishes[0].get("epoiId")
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

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        import json

        body = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        self.send_response(status)
        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8",
        )
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, status: int, body: str) -> None:
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header(
            "Content-Type",
            "text/html; charset=utf-8",
        )
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    @staticmethod
    def _page_shell(title: str, content: str) -> str:
        return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    body {{
      margin: 0;
      background: #f5f6f8;
      color: #222;
      font: 15px/1.5 "Microsoft YaHei", sans-serif;
    }}
    main {{
      width: min(1120px, calc(100% - 40px));
      margin: 36px auto;
      background: #fff;
      border: 1px solid #e5e7eb;
      border-radius: 8px;
      overflow: hidden;
    }}
    header {{
      padding: 22px 26px;
      border-bottom: 1px solid #eceff3;
    }}
    h1 {{ margin: 0; font-size: 22px; }}
    .meta {{ margin-top: 8px; color: #667085; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{
      padding: 12px 14px;
      border-bottom: 1px solid #eef0f3;
      text-align: left;
      vertical-align: top;
    }}
    th {{ background: #fafbfc; color: #475467; }}
    .price {{ color: #d4380d; font-weight: 700; }}
    .tag {{
      display: inline-block;
      padding: 2px 7px;
      border-radius: 4px;
      background: #e8f5e9;
      color: #2e7d32;
      font-size: 12px;
    }}
    .actions {{ display: flex; flex-wrap: wrap; gap: 6px; }}
    .actions form {{ display: inline-flex; gap: 4px; }}
    .search-form {{
      display: flex;
      gap: 8px;
      padding: 18px 26px 0;
    }}
    .search-form input {{
      flex: 1;
      min-width: 180px;
      border: 1px solid #d0d5dd;
      border-radius: 5px;
      padding: 7px 9px;
    }}
    button, select {{
      border: 1px solid #d0d5dd;
      border-radius: 5px;
      background: #fff;
      color: #344054;
      padding: 5px 8px;
      cursor: pointer;
    }}
    button:hover {{ border-color: #1677ff; color: #1677ff; }}
    .flash {{
      margin: 18px 26px 0;
      padding: 10px 12px;
      background: #edf7ed;
      border: 1px solid #b7dfb8;
      border-radius: 6px;
      color: #246b2a;
    }}
    .profile-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
      gap: 16px;
      padding: 20px 26px;
    }}
    .profile-card {{
      border: 1px solid #e4e7ec;
      border-radius: 7px;
      padding: 14px;
      background: #fff;
    }}
    .profile-card h2 {{ margin: 0 0 10px; font-size: 17px; }}
    pre {{
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      font: 13px/1.55 Consolas, monospace;
      color: #344054;
    }}
    .error {{ padding: 30px; color: #b42318; }}
  </style>
</head>
<body><main>{content}</main></body>
</html>"""

    def _render_menu(
        self,
        e_poi_id: str,
        dishes: list[dict[str, Any]],
        message: str = "",
    ) -> str:
        rows = []
        for dish in dishes:
            status = "上架" if dish["is_sold_out"] == 0 else "下架"
            dish_name = html.escape(str(dish["name"]))
            dish_code = html.escape(str(dish["app_food_code"]))
            epoi_value = html.escape(str(e_poi_id))
            hidden = (
                f'<input type="hidden" name="dish_id" value="{dish_code}">'
                f'<input type="hidden" name="dish_name" value="{dish_name}">'
                f'<input type="hidden" name="e_poi_id" value="{epoi_value}">'
            )
            actions = (
                '<div class="actions">'
                '<form method="post" action="/ui/action">'
                f"{hidden}"
                '<button name="action" value="favorite">收藏</button>'
                '<button name="action" value="click">点击</button>'
                '<button name="action" value="detail_view">详情</button>'
                '<button name="action" value="cart_add">加购</button>'
                '<button name="action" value="dismiss">忽略</button>'
                '<button name="action" value="not_interested">'
                "不感兴趣</button>"
                '<button name="action" value="order">下单</button>'
                "</form>"
                '<form method="post" action="/ui/action">'
                f"{hidden}"
                '<select name="rating">'
                '<option value="5">5分</option>'
                '<option value="4">4分</option>'
                '<option value="3">3分</option>'
                '<option value="2">2分</option>'
                '<option value="1">1分</option>'
                "</select>"
                '<button name="action" value="rating">评分</button>'
                "</form>"
                "</div>"
            )
            rows.append(
                "<tr>"
                f"<td>{html.escape(str(dish['sequence']))}</td>"
                f"<td>{dish_name}</td>"
                f"<td>{html.escape(str(dish['category_name']))}</td>"
                f"<td class=\"price\">¥{dish['price']:.2f}</td>"
                f"<td>{html.escape(str(dish['unit']))}</td>"
                f"<td><span class=\"tag\">{status}</span></td>"
                f"<td>{dish_code}</td>"
                f"<td>{html.escape(str(dish['mt_spu_id']))}</td>"
                f"<td>{actions}</td>"
                "</tr>"
            )
        if not rows:
            rows.append(
                '<tr><td colspan="9">该门店暂无菜品</td></tr>'
            )

        content = (
            "<header>"
            "<h1>美团模拟端菜单</h1>"
            f'<div class="meta">ePoiId：'
            f"{html.escape(e_poi_id)}，共 {len(dishes)} 道菜 · "
            '<a href="/stores">返回商家目录</a> · '
            '<a href="/profile">查看用户画像</a></div>'
            "</header>"
            '<form class="search-form" method="post" action="/ui/action">'
            '<input type="hidden" name="action" value="search">'
            f'<input type="hidden" name="e_poi_id" value="{epoi_value}">'
            '<input name="query" placeholder="搜索菜品或口味" required>'
            "<button>搜索</button>"
            "</form>"
            + (
                f'<div class="flash">{html.escape(message)}</div>'
                if message
                else ""
            )
            + "<table>"
            "<thead><tr>"
            "<th>排序</th><th>菜品</th><th>分类</th><th>价格</th>"
            "<th>单位</th><th>状态</th><th>ERP 菜品编码</th>"
            "<th>美团 SPU</th><th>操作</th>"
            "</tr></thead>"
            f"<tbody>{''.join(rows)}</tbody>"
            "</table>"
        )
        return self._page_shell("美团模拟端菜单", content)

    def _render_stores(
        self,
        restaurants: list[dict[str, Any]],
    ) -> str:
        groups: dict[str, list[dict[str, Any]]] = {}
        for restaurant in restaurants:
            groups.setdefault(
                str(restaurant["category"] or "其他"),
                [],
            ).append(restaurant)

        sections: list[str] = []
        for category, stores in groups.items():
            rows = []
            for store in stores:
                menu_url = (
                    f"/menu?ePoiId={quote(str(store['e_poi_id']))}"
                )
                rows.append(
                    "<tr>"
                    f"<td><a href=\"{menu_url}\">"
                    f"{html.escape(str(store['name']))}</a></td>"
                    f"<td>{format_rating(store['rating'])}</td>"
                    f"<td>¥{store['min_order']:.2f}</td>"
                    f"<td>¥{store['delivery_fee']:.2f}</td>"
                    f"<td>{store['distance_km']} km</td>"
                    f"<td>{store['dish_count']}</td>"
                    f"<td><a href=\"{menu_url}\">{menu_url}</a></td>"
                    "</tr>"
                )
            sections.append(
                f"<h2>{html.escape(category)}</h2>"
                "<table><thead><tr>"
                "<th>商家</th><th>评分</th><th>起送价</th>"
                "<th>配送费</th><th>距离</th><th>菜品数</th>"
                "<th>菜单链接</th>"
                "</tr></thead>"
                f"<tbody>{''.join(rows)}</tbody></table>"
            )

        content = (
            "<header>"
            "<h1>美团模拟端商家目录</h1>"
            f'<div class="meta">共 {len(restaurants)} 家商家，'
            f"{len(groups)} 个菜系 · "
            '<a href="/profile">查看用户画像</a></div>'
            "</header>"
            '<form class="search-form" method="post" action="/ui/action">'
            '<input type="hidden" name="action" value="search">'
            f'<input type="hidden" name="e_poi_id" '
            f'value="{self.server.default_e_poi_id}">'
            '<input name="query" placeholder="搜索菜品或口味" required>'
            "<button>搜索</button>"
            "</form>"
            f"<div style=\"padding:20px 26px\">{''.join(sections)}</div>"
        )
        return self._page_shell("美团模拟端商家目录", content)

    def _render_profile(
        self,
        summary: dict[str, Any],
        events: list[dict[str, Any]],
        message: str = "",
    ) -> str:
        explicit = json.dumps(
            summary.get("explicit_preferences", {}),
            ensure_ascii=False,
            indent=2,
        )
        learned = json.dumps(
            {
                "categories": summary.get("categories", []),
                "dishes": summary.get("dishes", []),
                "restaurants": summary.get("restaurants", []),
                "metrics": summary.get("metrics", {}),
            },
            ensure_ascii=False,
            indent=2,
        )
        event_rows = []
        for event in events:
            event_rows.append(
                "<tr>"
                f"<td>{html.escape(str(event['event_type']))}</td>"
                f"<td>{html.escape(str(event.get('dish_id') or '-'))}</td>"
                f"<td>{html.escape(str(event.get('restaurant_id') or '-'))}</td>"
                f"<td>{html.escape(str(event['created_at']))}</td>"
                "</tr>"
            )
        if not event_rows:
            event_rows.append(
                '<tr><td colspan="4">暂无行为记录</td></tr>'
            )

        content = (
            "<header>"
            "<h1>本地单用户画像</h1>"
            f'<div class="meta">用户：'
            f"{html.escape(str(summary.get('user_id', 'default')))} · "
            f"行为特征：{summary.get('feature_count', 0)} 条 · "
            '<a href="/stores">返回商家目录</a></div>'
            "</header>"
            + (
                f'<div class="flash">{html.escape(message)}</div>'
                if message
                else ""
            )
            + '<div class="profile-grid">'
            '<section class="profile-card">'
            "<h2>明确偏好</h2>"
            f"<pre>{html.escape(explicit)}</pre>"
            "</section>"
            '<section class="profile-card">'
            "<h2>行为推断画像</h2>"
            f"<pre>{html.escape(learned)}</pre>"
            "</section>"
            "</div>"
            "<div style=\"padding:0 26px 24px\">"
            "<h2>最近行为</h2>"
            "<table><thead><tr>"
            "<th>行为</th><th>菜品 ID</th><th>商家 ID</th><th>时间</th>"
            "</tr></thead>"
            f"<tbody>{''.join(event_rows)}</tbody></table>"
            "</div>"
        )
        return self._page_shell("本地用户画像", content)

    def _render_error(self, code: str, message: str) -> str:
        content = (
            '<div class="error">'
            f"<h2>{html.escape(code)}</h2>"
            f"<p>{html.escape(message)}</p>"
            "</div>"
        )
        return self._page_shell("菜单加载失败", content)

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
        config or MeituanConfig(
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
