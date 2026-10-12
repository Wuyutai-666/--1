"""单用户本地画像查看与管理工具。"""

from __future__ import annotations

import argparse
import json
import os

from data.init_db import init
from storage import TakeoutStorage


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="查看和管理本地单用户画像"
    )
    parser.add_argument(
        "action",
        choices=["show", "events", "reset"],
        help="show=查看画像，events=查看行为，reset=清空画像",
    )
    parser.add_argument(
        "--user-id",
        default=os.getenv("NL2SQL_USER_ID", "default"),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
    )
    parser.add_argument(
        "--include-preferences",
        action="store_true",
        help="reset 时同时清除明确设置的偏好",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="确认执行 reset",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    init(verbose=False)
    storage = TakeoutStorage()

    if args.action == "show":
        result = storage.get_profile_summary(
            args.user_id,
            limit=args.limit,
        )
    elif args.action == "events":
        result = storage.list_user_events(
            args.user_id,
            limit=args.limit,
        )
    else:
        if not args.yes:
            raise SystemExit(
                "reset 会删除行为画像，请追加 --yes 确认执行。"
            )
        result = storage.clear_user_profile(
            args.user_id,
            include_preferences=args.include_preferences,
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
