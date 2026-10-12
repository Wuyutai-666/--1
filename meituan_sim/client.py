"""按美团开放平台协议调用本地模拟端的客户端。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .protocol import MeituanConfig, build_signed_params


ROOT_DIR = Path(__file__).resolve().parents[1]


class MeituanAPIError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        trace_id: str | None = None,
    ):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.trace_id = trace_id


class MeituanClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        config: MeituanConfig | None = None,
        timeout_seconds: float = 10.0,
    ):
        self.base_url = (
            base_url
            or os.getenv(
                "MEITUAN_SIM_BASE_URL",
                "http://127.0.0.1:18080",
            )
        ).rstrip("/")
        self.config = config or MeituanConfig(
            developer_id=os.getenv("MEITUAN_DEVELOPER_ID", "108999"),
            sign_key=os.getenv("MEITUAN_SIGN_KEY", "test-sign-key"),
            app_auth_token=os.getenv(
                "MEITUAN_APP_AUTH_TOKEN",
                "test-app-auth-token",
            ),
        )
        self.timeout_seconds = timeout_seconds

    def invoke(
        self,
        path: str,
        biz: dict[str, Any],
        *,
        app_auth_token: str | None = None,
    ) -> Any:
        if not path.startswith("/"):
            path = "/" + path
        params = build_signed_params(
            self.config,
            biz,
            app_auth_token=app_auth_token,
        )
        body = urlencode(params).encode("utf-8")
        request = Request(
            f"{self.base_url}{path}",
            data=body,
            headers={
                "Content-Type": (
                    "application/x-www-form-urlencoded;charset=utf-8"
                ),
                "Accept": "application/json",
            },
            method="POST",
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))

        if payload.get("code") != "OP_SUCCESS":
            raise MeituanAPIError(
                str(payload.get("code") or "OP_UNKNOWN_ERROR"),
                str(payload.get("msg") or "接口调用失败"),
                payload.get("traceId"),
            )
        return payload.get("data")

    def batch_upload(
        self,
        e_poi_id: str,
        dishes: list[dict[str, Any]],
    ) -> Any:
        return self.invoke(
            "/waimai/dish/batchUpload",
            {
                "ePoiId": e_poi_id,
                "dishes": json.dumps(
                    dishes,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            },
        )

    def query_dishes(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> Any:
        return self.invoke(
            "/waimai/dish/queryListByEPoiId",
            {"offset": offset, "limit": limit},
        )

    def query_food_list(
        self,
        *,
        offset: int = 0,
        limit: int = 10,
    ) -> Any:
        return self.invoke(
            "/waimai/ng/dish/queryFoodList",
            {"offset": offset, "limit": limit},
        )

    def query_categories(self, e_poi_id: str | None = None) -> Any:
        biz: dict[str, Any] = {}
        if e_poi_id:
            biz["ePoiId"] = e_poi_id
        return self.invoke(
            "/waimai/dish/queryCatList",
            biz,
        )

    def update_price(
        self,
        dish_sku_prices: list[dict[str, Any]],
        e_poi_id: str | None = None,
    ) -> Any:
        biz: dict[str, Any] = {
            "dishSkuPrices": dish_sku_prices,
        }
        if e_poi_id:
            biz["ePoiId"] = e_poi_id
        return self.invoke("/waimai/dish/updatePrice", biz)

    def update_stock(
        self,
        dish_sku_stocks: list[dict[str, Any]],
        e_poi_id: str | None = None,
    ) -> Any:
        biz: dict[str, Any] = {
            "dishSkuStocks": dish_sku_stocks,
        }
        if e_poi_id:
            biz["ePoiId"] = e_poi_id
        return self.invoke("/waimai/dish/updateStock", biz)

    def delete_dish(self, e_dish_code: str) -> Any:
        return self.invoke(
            "/waimai/dish/delete",
            {"eDishCode": e_dish_code},
        )
