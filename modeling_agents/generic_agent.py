import json
from agents import Agent, RunHooks, Runner
from agents.mcp import MCPServerStdio

class PrintingHooks(RunHooks):

    def __init__(self):
        self.tool_calls = []

    async def on_tool_start(self, context, agent, tool_call):
        raw_args = getattr(context, "tool_arguments", None)
        arguments = json.loads(raw_args) if raw_args else None

        self.tool_calls.append({
            "api_name": tool_call.name,
            "arguments": arguments
        })

        print(f"\n --- Tool call: {tool_call.name}")
        print(f"-- Arguments: {arguments}")

    async def on_tool_end(self, context, agent, tool_call, result):
        print(f" Tool done: {tool_call.name}")


class GenericModelingAgent:

    BASE_PROMPT = """
    You are a modeling agent with access to Model-Based Engineering tools.
    Use the available tools to accomplish modeling tasks.
    When given a task:
    1. Identify which tools are relevant
    2. Execute them in the right order
    3. Return the result
    """

    def __init__(self, mcp_server_script: str, prompt: str = None):
        self.mcp_server_script = mcp_server_script
        self.current_prompt = prompt or self.BASE_PROMPT
        self.iteration = 0
        self.evaluation_history = []

    def build_agent(self) -> Agent:
        return Agent(
            name=f"ModelingAgent_v{self.iteration}",
            instructions=self.current_prompt,
            mcp_servers=[
                MCPServerStdio(
                    params={"command": "python3", "args": [self.mcp_server_script]}
                )
            ]
        )

    async def run(self, task: str, file: str) -> tuple[str, list[dict]]:
        """Returns (final_output, list of tool calls made)."""


        agent = self.build_agent()
        hooks = PrintingHooks()
        for server in agent.mcp_servers:
            await server.connect()
        try:
            result = await Runner.run(agent, task, hooks=hooks)
            return result.final_output, hooks.tool_calls
        finally:
            for server in agent.mcp_servers:
                await server.cleanup()