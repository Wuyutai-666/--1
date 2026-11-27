"""美团技术服务合作中心 API 模拟端。"""

from .client import MeituanAPIError, MeituanClient
from .protocol import MeituanConfig, ProtocolError

__all__ = [
    "MeituanAPIError",
    "MeituanClient",
    "MeituanConfig",
    "ProtocolError",
    "build_server",
    "run_server",
]


def __getattr__(name: str):
    """延迟导入服务端，避免 python -m 启动时重复加载模块。"""
    if name in {"build_server", "run_server"}:
        from . import server

        return getattr(server, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
