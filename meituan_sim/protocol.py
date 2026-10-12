"""美团开放平台公共请求、签名和响应协议。"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Mapping


class ProtocolError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class MeituanConfig:
    developer_id: str
    sign_key: str
    app_auth_token: str | None = None
    business_id: int = 2
    max_timestamp_skew_seconds: int = 300


def compact_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )


def sign_params(
    params: Mapping[str, Any],
    sign_key: str,
) -> str:
    parts: list[str] = []
    for key in sorted(params):
        if key.lower() == "sign":
            continue
        value = params[key]
        if value is None or value == "":
            continue
        parts.append(f"{key}{value}")
    source = sign_key + "".join(parts)
    return hashlib.sha1(source.encode("utf-8")).hexdigest()


def build_signed_params(
    config: MeituanConfig,
    biz: Mapping[str, Any] | list[Any],
    *,
    timestamp: int | None = None,
    app_auth_token: str | None = None,
) -> dict[str, str]:
    params: dict[str, str] = {
        "developerId": str(config.developer_id),
        "charset": "UTF-8",
        "timestamp": str(timestamp or int(time.time())),
        "version": "2",
        "businessId": str(config.business_id),
        "biz": compact_json(biz),
    }
    token = config.app_auth_token if app_auth_token is None else app_auth_token
    if token:
        params["appAuthToken"] = token
    params["sign"] = sign_params(params, config.sign_key)
    return params


def parse_biz(params: Mapping[str, Any]) -> Any:
    value = params.get("biz")
    if value is None or value == "":
        raise ProtocolError("OP_SYSTEM_PARAM_ERROR", "缺少系统参数 biz")
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise ProtocolError(
            "OP_SYSTEM_PARAM_ERROR",
            f"biz 不是合法 JSON：{exc}",
        ) from exc


def verify_request(
    params: Mapping[str, Any],
    config: MeituanConfig,
    *,
    require_auth: bool = True,
) -> None:
    required = {
        "developerId",
        "charset",
        "timestamp",
        "version",
        "businessId",
        "biz",
        "sign",
    }
    missing = sorted(key for key in required if params.get(key) in (None, ""))
    if missing:
        raise ProtocolError(
            "OP_SYSTEM_PARAM_ERROR",
            f"缺少系统参数：{', '.join(missing)}",
        )

    if str(params["developerId"]) != str(config.developer_id):
        raise ProtocolError("OP_SYSTEM_PARAM_ERROR", "developerId 不匹配")
    if str(params["version"]) != "2":
        raise ProtocolError("OP_SYSTEM_PARAM_ERROR", "version 必须为 2")
    if str(params["businessId"]) != str(config.business_id):
        raise ProtocolError("OP_SYSTEM_PARAM_ERROR", "businessId 不匹配")
    if str(params["charset"]).lower() != "utf-8":
        raise ProtocolError("OP_SYSTEM_PARAM_ERROR", "charset 必须为 UTF-8")

    try:
        request_timestamp = int(params["timestamp"])
    except (TypeError, ValueError) as exc:
        raise ProtocolError(
            "OP_SYSTEM_PARAM_ERROR",
            "timestamp 必须为秒级整数",
        ) from exc

    current_timestamp = int(time.time())
    if abs(current_timestamp - request_timestamp) > (
        config.max_timestamp_skew_seconds
    ):
        raise ProtocolError("OP_SYSTEM_PARAM_ERROR", "timestamp 已过期")

    expected_sign = sign_params(params, config.sign_key)
    if str(params["sign"]).lower() != expected_sign:
        raise ProtocolError("OP_SIGN_ERROR", "签名校验失败")

    if require_auth:
        token = str(params.get("appAuthToken") or "")
        if not token:
            raise ProtocolError(
                "OP_SYSTEM_PARAM_ERROR",
                "缺少系统参数 appAuthToken",
            )
        if config.app_auth_token and token != config.app_auth_token:
            raise ProtocolError("OP_AUTH_ERROR", "appAuthToken 无效")


def success_response(
    data: Any,
    *,
    trace_id: str | None = None,
) -> dict[str, Any]:
    return {
        "code": "OP_SUCCESS",
        "msg": "成功",
        "traceId": trace_id or uuid.uuid4().hex,
        "data": data,
    }


def error_response(
    code: str,
    message: str,
    *,
    trace_id: str | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "msg": message,
        "traceId": trace_id or uuid.uuid4().hex,
    }
