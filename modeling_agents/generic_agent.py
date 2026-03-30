import json
import sys

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

    async def run(self, task: str) -> tuple[str, list[dict]]:
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

    def evaluate(self, actual_tool_calls, expected_apis):

        if not expected_apis:
            return 1.0
        
        for expected in expected_apis:
            match_found = False
#  Expected API calls [{'api_name': 'apply_Class2Relational_transformation_tool', 'arguments': '/Users/zakariahachm/Documents/Phd_Zakaria/Scripts/atl-server/sample sources/Class.xmi'}]
# Actual calls: [{'api_name': 'apply_Class2Relational_transformation_tool', 'arguments': {'file_path': '/Users/zaariahachm/Documents/Phd_Zakaria/Scripts/atl-server/sample sources/Class.xmi'}}].
            for actual in actual_tool_calls:
                if actual["api_name"] != expected["api_name"]:
                    continue

                expected_args = expected.get("arguments")
                actual_args = actual.get("arguments").get("file_path") if isinstance(actual.get("arguments"), dict) else actual.get("arguments")
                # normalize string JSON -> dict if needed
                if isinstance(expected_args, str):
                    try:
                        expected_args = json.loads(expected_args)
                    except:
                        pass

                if expected_args == actual_args:
                    match_found = True
                    break

            if not match_found:
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
                self.evaluation_history.append({
                    "instruction": sample["instruction"],
                    "score": score,
                    "expected": expected_apis,
                    "actual": actual_calls
                })
                if score < threshold:
                    self.refine_prompt(sample["instruction"], actual_calls, expected_apis)

            avg_score = sum(scores) / len(scores)
            print(f"Iteration {self.iteration} — avg score: {avg_score:.2f}")
            if avg_score >= threshold:
                print("Threshold met. Specialization complete.")
                break

        return self.build_agent()