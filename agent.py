import os
import json
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from toolkit import (
    ToolRegistry,
    register_calculator,
    register_file_writer,
    safe_calculator,
    write_workspace_file,
)

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parent

client = OpenAI(
    base_url=os.getenv("LLM_BASE_URL", "http://localhost:11434/v1"),
    api_key=os.getenv("LLM_API_KEY") or os.getenv("LM_API_KEY") or "ollama"
)
MODEL = os.getenv("MODEL_NAME", "qwen2:7b-instruct")

def calculator(expr: str) -> str:
    return safe_calculator(expr)


def write_file(filename: str, content: str) -> str:
    result = write_workspace_file(ROOT_DIR, filename, content)
    return f"文件 {result['filename']} 写入成功"


def build_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_calculator(registry)
    register_file_writer(registry, ROOT_DIR)
    return registry

# ==========记忆模块==========
class AgentMemory:
    def __init__(self):
        self.short_memory = []

    def add_msg(self, role: str, content: str = "", **extra):
        message = {"role": role, "content": content}
        message.update(extra)
        self.short_memory.append(message)

    def get_history(self):
        return self.short_memory.copy()

    def clear(self):
        self.short_memory.clear()

# ==========Agent主循环==========
class SimpleAgent:
    def __init__(
        self,
        system_prompt: str,
        tool_registry: ToolRegistry | None = None,
    ):
        self.memory = AgentMemory()
        self.system_prompt = system_prompt
        self.tool_registry = tool_registry or build_tool_registry()
        self.memory.add_msg("system", self.system_prompt)

    def run(self, user_query: str, max_loop=5):
        self.memory.add_msg("user", user_query)
        loop_count = 0

        while loop_count < max_loop:
            loop_count +=1
            resp = client.chat.completions.create(
                model=MODEL,
                messages=self.memory.get_history(),
                tools=self.tool_registry.definitions(),
                tool_choice="auto",
                temperature=0.2
            )
            msg = resp.choices[0].message

            if msg.tool_calls:
                assistant_tool_calls = [
                    {
                        "id": tool_call.id,
                        "type": "function",
                        "function": {
                            "name": tool_call.function.name,
                            "arguments": tool_call.function.arguments
                        }
                    }
                    for tool_call in msg.tool_calls
                ]
                self.memory.add_msg(
                    "assistant",
                    msg.content or "",
                    tool_calls=assistant_tool_calls
                )
                for tool_call in msg.tool_calls:
                    func_name = tool_call.function.name
                    try:
                        args = json.loads(tool_call.function.arguments)
                        print(f"\n【Agent调用工具】{func_name}, 参数:{args}")
                        result = self.tool_registry.execute(func_name, args)
                    except Exception as e:
                        result = f"工具调用失败：{str(e)}"
                    print(f"【工具返回结果】{result}")
                    self.memory.add_msg(
                        "tool",
                        result,
                        tool_call_id=tool_call.id
                    )
                continue

            self.memory.add_msg("assistant", msg.content)
            return msg.content

        return "达到最大循环次数，任务终止"

if __name__ == "__main__":
    system_prompt = """
你是自主智能助手Agent。
规则：
1.遇到数学计算必须调用calculator工具，禁止口算。
2.需要保存文本，调用write_file工具。
3.调用完工具后，整理结果输出最终答案。
4.不要重复调用同一个工具。
"""
    agent = SimpleAgent(system_prompt)

    print("===== 自定义智能体启动 =====")
    while True:
        user_input = input("\n请输入你的指令：")
        if user_input in ["exit","quit"]:
            print("退出智能体")
            break
        ans = agent.run(user_input)
        print(f"\n【智能体回答】{ans}")
