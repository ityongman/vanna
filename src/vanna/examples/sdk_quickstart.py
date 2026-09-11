"""
Minimal SDK quickstart for consuming this package as a dependency.

安装（私有源或本地 wheel）：
  pip install vanna-agent-sdk[openai]           # 纯文本转 SQL
  pip install vanna-agent-sdk[openai,visualize] # 需要图表可视化时

运行：
  PYTHONPATH=. python vanna/examples/sdk_quickstart.py

要点：
- import 名仍是 ``vanna``（发行包名 vanna-agent-sdk 仅用于 pip）
- ``create_basic_agent`` 是 SDK 主入口，依赖全部注入式可选
- 配置 ``AgentConfig.database`` 后自动注册 run_sql（plotly 存在时
  再注册 visualize_data），无需手工建 ToolRegistry
"""

import asyncio
import importlib.util
import os
import sys


def ensure_env() -> None:
    if importlib.util.find_spec("dotenv") is not None:
        from dotenv import load_dotenv

        load_dotenv(dotenv_path=os.path.join(os.getcwd(), ".env"), override=False)

    if not os.getenv("OPENAI_API_KEY"):
        print(
            "[error] OPENAI_API_KEY is not set. Add it to your environment or .env file."
        )
        sys.exit(1)


async def main() -> None:
    ensure_env()

    try:
        from vanna.integrations.llm.openai import OpenAILlmService
    except ImportError:
        print(
            "[error] openai extra not installed. "
            "Install with: pip install vanna-agent-sdk[openai]"
        )
        raise

    from vanna import AgentConfig, User
    from vanna.agents import create_basic_agent
    from vanna.core.agent.config import DatabaseConfig

    llm = OpenAILlmService(model=os.getenv("OPENAI_MODEL", "gpt-5"))

    config = AgentConfig(
        stream_responses=True,
        # 设置 database 后，Agent 自动派生 SqlRunner 并注册 run_sql 工具
        database=DatabaseConfig(url="sqlite:///demo.db"),
    )

    agent = create_basic_agent(llm_service=llm, config=config)

    user = User(id="sdk-user", username="developer")
    conversation_id = "sdk-quickstart-demo"

    question = "这个库里有几张表？每张表各有多少行？"
    print(f"User: {question}\n")
    async for component in agent.send_message(
        user=user, message=question, conversation_id=conversation_id
    ):
        if hasattr(component, "content") and component.content:
            print("Assistant:", component.content)


if __name__ == "__main__":
    asyncio.run(main())
