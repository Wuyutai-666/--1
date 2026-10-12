"""在 VSCode 终端中手工产生用户画像行为事件。"""

from __future__ import annotations

import argparse
import json
import os

from data.init_db import init
from storage import TakeoutStorage


ACTION_TO_EVENT = {
    "click": "click",
    "view": "detail_view",
    "favorite": "favorite",
    "cart": "cart_add",
    "dismiss": "dismiss",
    "not-interested": "not_interested",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="记录点击、收藏、下单、评分等画像行为"
    )
    parser.add_argument(
        "action",
        choices=[
            *ACTION_TO_EVENT.keys(),
            "order",
            "rating",
            "search",
        ],
    )
    parser.add_argument("dish_name", nargs="?")
    parser.add_argument("--rating", type=float)
    parser.add_argument("--dwell-sec", type=float, default=0.0)
    parser.add_argument("--query")
    parser.add_argument(
        "--user-id",
        default=os.getenv("NL2SQL_USER_ID", "default"),
    )
    parser.add_argument(
        "--session-id",
        default=os.getenv("NL2SQL_SESSION_ID", "local-event-cli"),
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    init(verbose=False)
    storage = TakeoutStorage()

    if args.action == "search":
        query = args.query or args.dish_name
        if not query:
            raise SystemExit("search 需要 --query 或位置参数")
        result = storage.record_event(
            args.user_id,
            "search",
            session_id=args.session_id,
            search_query=query,
            context={"source": "event_cli"},
        )
    elif args.action == "order":
        if not args.dish_name:
            raise SystemExit("order 需要菜品名称")
        result = storage.record_order(
            args.user_id,
            args.dish_name,
            rating=args.rating,
            source="local_cli",
        )
    elif args.action == "rating":
        if not args.dish_name or args.rating is None:
            raise SystemExit("rating 需要菜品名称和 --rating")
        result = storage.record_event(
            args.user_id,
            "rating",
            dish_name=args.dish_name,
            session_id=args.session_id,
            context={"rating": args.rating, "source": "event_cli"},
        )
    else:
        if not args.dish_name:
            raise SystemExit(f"{args.action} 需要菜品名称")
        result = storage.record_event(
            args.user_id,
            ACTION_TO_EVENT[args.action],
            dish_name=args.dish_name,
            session_id=args.session_id,
            context={
                "source": "event_cli",
                "dwell_sec": args.dwell_sec,
            },
        )

    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )


if __name__ == "__main__":
    main()
