"""统一工具注册表和可复用工具实现。"""

from __future__ import annotations

import ast
import json
import operator
from pathlib import Path
from typing import Any, Callable


ToolHandler = Callable[..., Any]
TextCallback = Callable[[str], None]


class ToolExecutionError(RuntimeError):
    pass


def stream_chat_completion(
    client: Any,
    *,
    on_text: TextCallback | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """聚合流式响应，并实时返回正文 token。"""
    stream = client.chat.completions.create(stream=True, **kwargs)
    content_parts: list[str] = []
    tool_calls: dict[int, dict[str, Any]] = {}

    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta

        text = getattr(delta, "content", None)
        if text:
            content_parts.append(text)
            if on_text is not None:
                on_text(text)

        for tool_delta in getattr(delta, "tool_calls", None) or []:
            index = getattr(tool_delta, "index", None)
            if index is None:
                index = len(tool_calls)
            entry = tool_calls.setdefault(
                index,
                {
                    "id": "",
                    "type": "function",
                    "function": {
                        "name": "",
                        "arguments": "",
                    },
                },
            )
            if getattr(tool_delta, "id", None):
                entry["id"] += tool_delta.id
            if getattr(tool_delta, "type", None):
                entry["type"] = tool_delta.type

            function_delta = getattr(tool_delta, "function", None)
            if function_delta is not None:
                name = getattr(function_delta, "name", None)
                arguments = getattr(function_delta, "arguments", None)
                if name:
                    entry["function"]["name"] += name
                if arguments:
                    entry["function"]["arguments"] += arguments

    result: dict[str, Any] = {
        "role": "assistant",
        "content": "".join(content_parts),
    }
    if tool_calls:
        result["tool_calls"] = [
            tool_calls[index]
            for index in sorted(tool_calls)
        ]
    return result


class ToolRegistry:
    def __init__(self):
        self._definitions: dict[str, dict[str, Any]] = {}
        self._handlers: dict[str, ToolHandler] = {}

    def register(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        handler: ToolHandler,
    ) -> None:
        if name in self._handlers:
            raise ValueError(f"工具重复注册：{name}")
        self._definitions[name] = {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters,
            },
        }
        self._handlers[name] = handler

    def definitions(self) -> list[dict[str, Any]]:
        return [
            json.loads(json.dumps(definition, ensure_ascii=False))
            for definition in self._definitions.values()
        ]

    def execute(self, name: str, arguments: dict[str, Any]) -> str:
        handler = self._handlers.get(name)
        if handler is None:
            raise ToolExecutionError(f"未知工具：{name}")
        try:
            result = handler(**arguments)
        except TypeError as exc:
            raise ToolExecutionError(
                f"工具参数不正确：{name}，{exc}"
            ) from exc
        except Exception as exc:
            raise ToolExecutionError(
                f"工具执行失败：{name}，{exc}"
            ) from exc

        if isinstance(result, str):
            return result
        return json.dumps(result, ensure_ascii=False, default=str)


_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_UNARY_OPERATORS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def _evaluate_expression(node: ast.AST) -> int | float:
    if isinstance(node, ast.Expression):
        return _evaluate_expression(node.body)
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
        return _BINARY_OPERATORS[type(node.op)](
            _evaluate_expression(node.left),
            _evaluate_expression(node.right),
        )
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
        return _UNARY_OPERATORS[type(node.op)](
            _evaluate_expression(node.operand)
        )
    raise ValueError("表达式仅支持数字和基本数学运算符")


def safe_calculator(expr: str) -> str:
    tree = ast.parse(expr, mode="eval")
    result = _evaluate_expression(tree)
    return f"计算结果：{expr} = {result}"


def write_workspace_file(
    workspace: Path,
    filename: str,
    content: str,
) -> dict[str, Any]:
    root = Path(workspace).resolve()
    candidate = Path(filename)
    target = (
        candidate.resolve()
        if candidate.is_absolute()
        else (root / candidate).resolve()
    )
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError("只允许写入项目目录内的文件") from exc

    if len(content.encode("utf-8")) > 1_000_000:
        raise ValueError("单次写入内容不能超过 1 MB")

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {
        "filename": str(target.relative_to(root)),
        "bytes_written": len(content.encode("utf-8")),
    }


def register_calculator(
    registry: ToolRegistry,
    prefix: str = "",
) -> None:
    registry.register(
        f"{prefix}calculator",
        "计算基础数学表达式，只支持数字和基本运算符",
        {
            "type": "object",
            "required": ["expr"],
            "properties": {
                "expr": {
                    "type": "string",
                    "description": "例如 100*2+50",
                }
            },
        },
        safe_calculator,
    )


def register_file_writer(
    registry: ToolRegistry,
    workspace: Path,
    prefix: str = "",
) -> None:
    registry.register(
        f"{prefix}write_file",
        "把文本写入项目目录内的文件",
        {
            "type": "object",
            "required": ["filename", "content"],
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "相对于项目根目录的文件路径",
                },
                "content": {
                    "type": "string",
                    "description": "写入的 UTF-8 文本内容",
                },
            },
        },
        lambda filename, content: write_workspace_file(
            workspace,
            filename,
            content,
        ),
    )
