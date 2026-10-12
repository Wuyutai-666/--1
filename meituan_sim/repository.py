"""美团菜品接口对应的 SQLite 仓储实现。"""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from .protocol import ProtocolError, compact_json


def parse_json_array(
    value: Any,
    field_name: str,
    *,
    required: bool = False,
) -> list[dict[str, Any]]:
    if value is None or value == "":
        if required:
            raise ProtocolError(
                "OP_BIZ_PARAM_ERROR",
                f"缺少业务参数：{field_name}",
            )
        return []

    parsed = value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ProtocolError(
                "OP_BIZ_PARAM_ERROR",
                f"{field_name} 不是合法 JSON 数组",
            ) from exc
    if not isinstance(parsed, list):
        raise ProtocolError(
            "OP_BIZ_PARAM_ERROR",
            f"{field_name} 必须为 JSON 数组",
        )
    return [item for item in parsed if isinstance(item, dict)]


class MeituanDishRepository:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path).resolve()
        if not self.db_path.is_file():
            raise FileNotFoundError(f"数据库不存在：{self.db_path}")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @staticmethod
    def _restaurant(
        conn: sqlite3.Connection,
        e_poi_id: str,
    ) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM restaurants WHERE e_poi_id = ?",
            (e_poi_id,),
        ).fetchone()
        if row is None:
            raise ProtocolError(
                "OP_BIZ_PARAM_ERROR",
                f"未找到门店映射：ePoiId={e_poi_id}",
            )
        return row

    @staticmethod
    def _price_from_skus(
        skus: list[dict[str, Any]],
        fallback: float = 0.0,
    ) -> float:
        prices: list[float] = []
        for sku in skus:
            try:
                prices.append(float(sku.get("price")))
            except (TypeError, ValueError):
                continue
        return min(prices) if prices else fallback

    def upsert_dishes(
        self,
        e_poi_id: str,
        dishes: Any,
    ) -> dict[str, Any]:
        dish_items = parse_json_array(
            dishes,
            "dishes",
            required=True,
        )
        if not dish_items:
            raise ProtocolError(
                "OP_BIZ_PARAM_ERROR",
                "dishes 不能为空",
            )

        stored: list[dict[str, Any]] = []
        with self._connect() as conn:
            restaurant = self._restaurant(conn, e_poi_id)
            for item in dish_items:
                e_dish_code = str(item.get("eDishCode") or "").strip()
                dish_name = str(item.get("dishName") or "").strip()
                if not e_dish_code or not dish_name:
                    raise ProtocolError(
                        "OP_BIZ_PARAM_ERROR",
                        "dishes 中 eDishCode 和 dishName 必填",
                    )

                current = conn.execute(
                    """
                    SELECT * FROM meituan_dishes
                    WHERE e_poi_id = ? AND e_dish_code = ?
                    """,
                    (e_poi_id, e_dish_code),
                ).fetchone()
                spu_id = (
                    current["spu_id"]
                    if current
                    else f"spu_{uuid.uuid4().hex[:16]}"
                )

                skus = item.get("skus") or []
                if isinstance(skus, str):
                    try:
                        skus = json.loads(skus)
                    except json.JSONDecodeError as exc:
                        raise ProtocolError(
                            "OP_BIZ_PARAM_ERROR",
                            f"{e_dish_code} 的 skus 不是合法 JSON",
                        ) from exc
                if not isinstance(skus, list):
                    raise ProtocolError(
                        "OP_BIZ_PARAM_ERROR",
                        f"{e_dish_code} 的 skus 必须为数组",
                    )

                try:
                    price = float(item.get("price"))
                except (TypeError, ValueError) as exc:
                    raise ProtocolError(
                        "OP_BIZ_PARAM_ERROR",
                        f"{e_dish_code} 的 price 必须为数字",
                    ) from exc
                if skus:
                    price = self._price_from_skus(skus, price)

                category_name = str(item.get("categoryName") or "")
                description = str(item.get("description") or "")
                picture = str(item.get("picture") or "")
                unit = str(item.get("unit") or "份")
                is_sold_out = int(item.get("isSoldOut") or 0)
                min_order_count = int(item.get("minOrderCount") or 1)
                sequence = int(item.get("sequence") or 0)
                skus_json = compact_json(skus)

                conn.execute(
                    """
                    INSERT INTO meituan_dishes (
                        spu_id, e_poi_id, e_dish_code, dish_name,
                        category_name, description, price, picture,
                        unit, is_sold_out, min_order_count, sequence,
                        skus_json, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(e_poi_id, e_dish_code) DO UPDATE SET
                        dish_name = excluded.dish_name,
                        category_name = excluded.category_name,
                        description = excluded.description,
                        price = excluded.price,
                        picture = excluded.picture,
                        unit = excluded.unit,
                        is_sold_out = excluded.is_sold_out,
                        min_order_count = excluded.min_order_count,
                        sequence = excluded.sequence,
                        skus_json = excluded.skus_json,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        spu_id,
                        e_poi_id,
                        e_dish_code,
                        dish_name,
                        category_name,
                        description,
                        price,
                        picture,
                        unit,
                        is_sold_out,
                        min_order_count,
                        sequence,
                        skus_json,
                    ),
                )

                local = conn.execute(
                    """
                    SELECT *
                    FROM dishes
                    WHERE meituan_spu_id = ?
                       OR (
                           restaurant_id = ?
                           AND e_dish_code = ?
                       )
                       OR id = ?
                    LIMIT 1
                    """,
                    (
                        spu_id,
                        restaurant["id"],
                        e_dish_code,
                        e_dish_code,
                    ),
                ).fetchone()

                local_id = (
                    local["id"]
                    if local
                    else f"mt_{uuid.uuid4().hex[:16]}"
                )
                spicy_level = (
                    int(local["spicy_level"] or 0)
                    if local
                    else 0
                )
                month_sales = (
                    int(local["month_sales"] or 0)
                    if local
                    else 0
                )

                conn.execute(
                    """
                    INSERT INTO dishes (
                        id, restaurant_id, name, price, spicy_level,
                        month_sales, tags, meituan_spu_id, e_dish_code,
                        category_name, description, picture, unit,
                        is_sold_out, min_order_count, sequence,
                        skus_json, source, updated_at
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, 'meituan_sim', CURRENT_TIMESTAMP
                    )
                    ON CONFLICT(id) DO UPDATE SET
                        restaurant_id = excluded.restaurant_id,
                        name = excluded.name,
                        price = excluded.price,
                        tags = excluded.tags,
                        meituan_spu_id = excluded.meituan_spu_id,
                        e_dish_code = excluded.e_dish_code,
                        category_name = excluded.category_name,
                        description = excluded.description,
                        picture = excluded.picture,
                        unit = excluded.unit,
                        is_sold_out = excluded.is_sold_out,
                        min_order_count = excluded.min_order_count,
                        sequence = excluded.sequence,
                        skus_json = excluded.skus_json,
                        source = 'meituan_sim',
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        local_id,
                        restaurant["id"],
                        dish_name,
                        price,
                        spicy_level,
                        month_sales,
                        category_name,
                        spu_id,
                        e_dish_code,
                        category_name,
                        description,
                        picture,
                        unit,
                        is_sold_out,
                        min_order_count,
                        sequence,
                        skus_json,
                    ),
                )
                stored.append(
                    {
                        "spu_id": spu_id,
                        "local_dish_id": local_id,
                        "eDishCode": e_dish_code,
                        "dishName": dish_name,
                    }
                )
            conn.commit()
        return {"stored": stored, "count": len(stored)}

    @staticmethod
    def _dish_payload(row: sqlite3.Row) -> dict[str, Any]:
        skus = []
        if row["skus_json"]:
            try:
                skus = json.loads(row["skus_json"])
            except json.JSONDecodeError:
                skus = []
        return {
            "boxNum": 0.0,
            "boxPrice": 0.0,
            "categoryName": row["category_name"] or "",
            "description": row["description"] or "",
            "dishName": row["dish_name"],
            "eDishCode": row["e_dish_code"],
            "epoiId": row["e_poi_id"],
            "isNotSingle": 0,
            "isSoldOut": int(row["is_sold_out"] or 0),
            "minOrderCount": int(row["min_order_count"] or 1),
            "picture": row["picture"] or "",
            "pictures": row["picture"] or "",
            "price": float(row["price"] or 0),
            "sequence": int(row["sequence"] or 0),
            "skus": skus,
            "mt_spu_id": row["spu_id"],
            "origin_spu_id": row["spu_id"],
        }

    def query_dishes(
        self,
        e_poi_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        offset = max(0, int(offset))
        limit = max(1, min(int(limit), 199))
        with self._connect() as conn:
            self._restaurant(conn, e_poi_id)
            rows = conn.execute(
                """
                SELECT *
                FROM meituan_dishes
                WHERE e_poi_id = ?
                ORDER BY sequence, dish_name
                LIMIT ? OFFSET ?
                """,
                (e_poi_id, limit, offset),
            ).fetchall()
        return [self._dish_payload(row) for row in rows]

    def query_food_list(
        self,
        e_poi_id: str,
        *,
        offset: int = 0,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        offset = max(0, int(offset))
        limit = max(1, min(int(limit), 199))
        with self._connect() as conn:
            self._restaurant(conn, e_poi_id)
            rows = conn.execute(
                """
                SELECT *
                FROM meituan_dishes
                WHERE e_poi_id = ?
                ORDER BY sequence, dish_name
                LIMIT ? OFFSET ?
                """,
                (e_poi_id, limit, offset),
            ).fetchall()

        result: list[dict[str, Any]] = []
        for row in rows:
            result.append(
                {
                    "epoiId": row["e_poi_id"],
                    "app_food_code": row["e_dish_code"],
                    "name": row["dish_name"],
                    "description": row["description"] or "",
                    "price": float(row["price"] or 0),
                    "min_order_count": int(row["min_order_count"] or 1),
                    "unit": row["unit"] or "份",
                    "box_num": 0.0,
                    "box_price": 0.0,
                    "category_name": row["category_name"] or "",
                    "is_sold_out": int(row["is_sold_out"] or 0),
                    "picture": row["picture"] or "",
                    "sequence": int(row["sequence"] or 0),
                    "skus": row["skus_json"] or "[]",
                    "mt_spu_id": row["spu_id"],
                    "origin_spu_id": row["spu_id"],
                    "monthSaled": 0,
                }
            )
        return result

    def query_categories(self, e_poi_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            self._restaurant(conn, e_poi_id)
            rows = conn.execute(
                """
                SELECT category_name, COUNT(*) AS dish_count
                FROM meituan_dishes
                WHERE e_poi_id = ? AND category_name IS NOT NULL
                GROUP BY category_name
                ORDER BY category_name
                """,
                (e_poi_id,),
            ).fetchall()
        return [
            {
                "categoryName": row["category_name"],
                "dishCount": row["dish_count"],
            }
            for row in rows
        ]

    def list_restaurants(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    r.id,
                    r.name,
                    r.category,
                    r.rating,
                    r.min_order,
                    r.delivery_fee,
                    r.distance_km,
                    r.e_poi_id,
                    COUNT(md.spu_id) AS dish_count
                FROM restaurants AS r
                LEFT JOIN meituan_dishes AS md
                    ON md.e_poi_id = r.e_poi_id
                WHERE r.e_poi_id IS NOT NULL
                GROUP BY
                    r.id, r.name, r.category, r.rating,
                    r.min_order, r.delivery_fee, r.distance_km,
                    r.e_poi_id
                ORDER BY r.category, r.rating DESC, r.name
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def _require_dish(
        self,
        conn: sqlite3.Connection,
        e_dish_code: str,
        e_poi_id: str | None = None,
    ) -> sqlite3.Row:
        params: list[Any] = [e_dish_code]
        sql = "SELECT * FROM meituan_dishes WHERE e_dish_code = ?"
        if e_poi_id:
            sql += " AND e_poi_id = ?"
            params.append(e_poi_id)
        row = conn.execute(sql + " LIMIT 1", params).fetchone()
        if row is None:
            raise ProtocolError(
                "OP_BIZ_PARAM_ERROR",
                f"菜品不存在：eDishCode={e_dish_code}",
            )
        return row

    def update_price(
        self,
        dish_sku_prices: Any,
        e_poi_id: str | None = None,
    ) -> dict[str, Any]:
        items = parse_json_array(
            dish_sku_prices,
            "dishSkuPrices",
            required=True,
        )
        updated = 0
        with self._connect() as conn:
            for item in items:
                code = str(item.get("eDishCode") or "")
                row = self._require_dish(conn, code, e_poi_id)
                skus = json.loads(row["skus_json"] or "[]")
                requested = {
                    str(sku.get("skuId")): sku.get("price")
                    for sku in item.get("skus") or []
                }
                for sku in skus:
                    sku_id = str(sku.get("skuId"))
                    if sku_id in requested:
                        sku["price"] = str(requested[sku_id])
                new_price = self._price_from_skus(
                    skus,
                    float(row["price"] or 0),
                )
                conn.execute(
                    """
                    UPDATE meituan_dishes
                    SET price = ?, skus_json = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE spu_id = ?
                    """,
                    (new_price, compact_json(skus), row["spu_id"]),
                )
                conn.execute(
                    """
                    UPDATE dishes
                    SET price = ?, skus_json = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE meituan_spu_id = ?
                    """,
                    (new_price, compact_json(skus), row["spu_id"]),
                )
                updated += 1
            conn.commit()
        return {"updated": updated}

    def update_stock(
        self,
        dish_sku_stocks: Any,
        e_poi_id: str | None = None,
    ) -> dict[str, Any]:
        items = parse_json_array(
            dish_sku_stocks,
            "dishSkuStocks",
            required=True,
        )
        updated = 0
        with self._connect() as conn:
            for item in items:
                code = str(item.get("eDishCode") or "")
                row = self._require_dish(conn, code, e_poi_id)
                skus = json.loads(row["skus_json"] or "[]")
                requested = {
                    str(sku.get("skuId")): str(sku.get("stock"))
                    for sku in item.get("skus") or []
                }
                for sku in skus:
                    sku_id = str(sku.get("skuId"))
                    if sku_id in requested:
                        sku["stock"] = requested[sku_id]
                conn.execute(
                    """
                    UPDATE meituan_dishes
                    SET skus_json = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE spu_id = ?
                    """,
                    (compact_json(skus), row["spu_id"]),
                )
                conn.execute(
                    """
                    UPDATE dishes
                    SET skus_json = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE meituan_spu_id = ?
                    """,
                    (compact_json(skus), row["spu_id"]),
                )
                updated += 1
            conn.commit()
        return {"updated": updated}

    def delete_dish(
        self,
        e_dish_code: str,
        e_poi_id: str | None = None,
    ) -> dict[str, Any]:
        if not e_dish_code:
            raise ProtocolError(
                "OP_BIZ_PARAM_ERROR",
                "缺少业务参数：eDishCode",
            )
        with self._connect() as conn:
            row = self._require_dish(conn, e_dish_code, e_poi_id)
            conn.execute(
                "DELETE FROM meituan_dishes WHERE spu_id = ?",
                (row["spu_id"],),
            )
            conn.execute(
                """
                DELETE FROM dishes
                WHERE meituan_spu_id = ? AND source = 'meituan_sim'
                """,
                (row["spu_id"],),
            )
            conn.commit()
        return {"deleted": 1, "eDishCode": e_dish_code}
