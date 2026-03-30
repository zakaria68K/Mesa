from agents import Agent, RunHooks, Runner
from agents.mcp import MCPServerStdio
from langsmith import traceable


class PrintingHooks(RunHooks):
    async def on_tool_start(self, context, agent, tool_call):
        print(f"\n --- Tool call: {tool_call.name}")
        print(f"-- Description: {tool_call.description}")

    async def on_tool_end(self, context, agent, tool_call, result):
        print(f" Tool done: {tool_call.name}")
        print(f"   Output: {result}")

class GenericModelingAgent:
    """
    Generic agent before specialization.
    Prompt is refined iteratively based on evaluation results.
    """

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


    async def run(self, task: str) -> str:
        agent = self.build_agent()
        # Connect to available MCP servers 
        for server in agent.mcp_servers:
            await server.connect()
        try:
            result = await Runner.run(agent, task, hooks=PrintingHooks())
            return result.final_output
        finally:
            for server in agent.mcp_servers:
                await server.cleanup()

    def evaluate(self, output: str, expected: str) -> float:
        """
        Simple evaluation — replace with other metrics (e.g. model similarity, exact match).
        Returns score between 0 and 1.
        """
        # placeholder: exact match
        score = 1.0 if output.strip() == expected.strip() else 0.0
        self.evaluation_history.append({"iteration": self.iteration, "score": score})
        return score

    def refine_prompt(self, task: str, output: str, expected: str):
        """
        Refines the prompt based on the gap between output and expected.
        In practice: call an LLM to rewrite the prompt.
        """
        self.current_prompt = f"""
        {self.current_prompt}

        ## Refinement (iteration {self.iteration})
        For tasks like: "{task}"
        Previous output was not accurate. Expected: "{expected}", got: "{output}".
        Adjust your approach accordingly.
        """
        self.iteration += 1

    async def specialize(self, dataset: list[dict], threshold: float = 0.8):
        """
        Core loop:
        Run -> Evaluate -> Threshold met? -> yes: return / no: refine -> repeat
        
        dataset: list of {"task": str, "expected": str}
        """
        while True:
            scores = []
            for sample in dataset:
                output = await self.run(sample["task"])
                score = self.evaluate(output, sample["expected"])
                scores.append(score)
                if score < threshold:
                    self.refine_prompt(sample["task"], output, sample["expected"])
            avg_score = sum(scores) / len(scores)
            print(f"Iteration {self.iteration} — avg score: {avg_score:.2f}")
            if avg_score >= threshold:
                print("Threshold met. Specialization complete.")
                break

        return self.build_agent()  