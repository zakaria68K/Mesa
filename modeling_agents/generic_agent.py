import json

from agents import Agent, RunHooks, Runner
from agents.mcp import MCPServerStdio
import sys

class PrintingHooks(RunHooks):
    async def on_tool_start(self, context, agent, tool_call):
        print(f"\n --- Tool call: {tool_call.name}")
        print(f"-- Description: {tool_call.description}")

    async def on_tool_end(self, context, agent, tool_call, result):
        print(f" Tool done: {tool_call.name}")
        print(f"   Output: {result}")
        self.tool_calls.append({
            "api_name": tool_call.name,
            "arguments": result  # raw result; override if you can extract input args
        })


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

    async def run(self, task: str) -> tuple[str, list[dict]]:
        """Returns (final_output, list of tool calls made)."""
        agent = self.build_agent()
        hooks = PrintingHooks()
        for server in agent.mcp_servers:
            await server.connect()
        try:
            result = await Runner.run(agent, task, hooks=PrintingHooks())
            return result.final_output
        finally:
            for server in agent.mcp_servers:
                await server.cleanup()

    def evaluate(self, actual_tool_calls: list[dict], expected_apis: list[dict]) -> float:
        """
        Returns:
            1.0 if ALL expected tool calls (with correct arguments and order) match
            0.0 otherwise
        """

        # No expected calls → automatically correct
        if not expected_apis:
            return 1.0

        # Must match number of calls exactly
        if len(actual_tool_calls) != len(expected_apis):
            return 0.0

        # Compare call-by-call in order
        for actual, expected in zip(actual_tool_calls, expected_apis):

            if actual["api_name"] != expected["api_name"]:
                return 0.0

            # Compare arguments exactly
            expected_args = expected.get("arguments")
            actual_args = actual.get("arguments")

            if expected_args != actual_args:
                return 0.0

        return 1.0

    def refine_prompt(self, task: str, actual_calls: list[dict], expected_apis: list[dict]):
        self.current_prompt = f"""
        {self.current_prompt}

        ## Refinement (iteration {self.iteration})
        For tasks like: "{task}"
        Expected API calls: {expected_apis}
        Actual API calls made: {actual_calls}
        Adjust your tool selection and ordering accordingly.
        """
        self.iteration += 1

    async def specialize(self, dataset: list[dict], threshold: float = 0.8):
        """
        dataset items: {{
            "instruction": str,
            "relevant_apis": [{{"api_name": str, "arguments": str}}],
            ...
        }}
        """
        while True:
            scores = []
            for sample in dataset:
                output, actual_calls = await self.run(sample["instruction"])
                expected_apis = sample["relevant_apis"]
                score = self.evaluate(actual_calls, expected_apis)
                print(f"  Score: {score:.2f} | Expected: {expected_apis} | Got: {actual_calls}")
                scores.append(score)
                if score < threshold:
                    self.refine_prompt(sample["instruction"], actual_calls, expected_apis)

            avg_score = sum(scores) / len(scores)
            print(f"Iteration {self.iteration} — avg score: {avg_score:.2f}")
            if avg_score >= threshold:
                print("Threshold met. Specialization complete.")
                break

        return self.build_agent()