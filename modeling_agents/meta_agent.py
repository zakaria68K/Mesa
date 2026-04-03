import json
from pathlib import Path
from openai import OpenAI
from modeling_agents.generic_agent import GenericModelingAgent


class MetaAgent:

    def __init__(self, agent_class=GenericModelingAgent,
        apply_skill=".opencode/skills/mde-apply/SKILL.md",
        get_skill=".opencode/skills/mde-get/SKILL.md",
        iteration=0):
        self.apply_skill = apply_skill
        self.get_skill = get_skill
        self.iteration = iteration
        self.agent = agent_class(mcp_server_script="mcp_servers/atl/atl_server.py")

    def _skill_for(self, expected_apis: list[dict]) -> str:
        if any("list" in e["api_name"] for e in expected_apis):
            return self.get_skill
        return self.apply_skill

    def specialize_agent(self, dataset: list[dict], threshold: float = 0.5):
        while True:
            scores = []
            for sample in dataset:
                output, actual_calls = self.agent.run(sample["instruction"], None)
                expected_apis = sample["relevant_apis"]
                score = self.evaluate(actual_calls, expected_apis)
                print(f"  Score: {score:.2f} | Expected: {expected_apis} | Got: {actual_calls}")
                scores.append(score)
                self.agent.evaluation_history.append({
                    "instruction": sample["instruction"],
                    "score": score,
                    "expected": expected_apis,
                    "actual": actual_calls
                })

            avg_score = sum(scores) / len(scores)
            print(f"Iteration {self.iteration} — avg score: {avg_score:.2f}")

            if avg_score >= threshold:
                print("Threshold met. Specialization complete.")
                break

            # Refine only samples that scored below threshold
            for sample, score in zip(dataset, scores):
                if score < threshold:
                    skill_file = self._skill_for(sample["relevant_apis"])
                    self.refine_agent_definition(
                        sample["instruction"],
                        self.agent.evaluation_history[-len(dataset)]["actual"],
                        sample["relevant_apis"],
                        skill_file
                    )

        return self.apply_skill, self.get_skill

    def evaluate(self, actual_tool_calls: list[dict], expected_apis: list[dict]) -> float:
        if not expected_apis:
            return 1.0
        print(f">>> Evaluating. Expected APIs: {expected_apis}, Actual tool calls: {actual_tool_calls}")
        for expected in expected_apis:
            match_found = False
            for actual in actual_tool_calls:
                actual["api_name"] = actual["api_name"].removeprefix("server_")
                if actual["api_name"] != expected["api_name"]:
                    continue
                expected_args = expected.get("arguments")
                actual_args = actual.get("arguments", {}).get("file_path")

                if isinstance(expected_args, str):
                    try:
                        expected_args = json.loads(expected_args)
                    except (json.JSONDecodeError, TypeError):
                        pass

                if isinstance(actual_args, dict):
                    actual_args = (
                        actual_args.get("file_path")
                        or actual_args.get("source_file")
                        or actual_args.get("input_file")
                        or actual_args.get("path")
                        or next(iter(actual_args.values()), None)
                    )

                expected_args = expected_args or None
                actual_args = actual_args or None

                if expected_args == actual_args:
                    match_found = True
                    break
            if not match_found:
                return 0.0
        return 1.0

    def refine_agent_definition(self, task: str, actual_calls: list[dict],
                                expected_apis: list[dict], skill_file: str) -> str:
        client = OpenAI()
        prompt_content = Path(skill_file).read_text()

        response = client.responses.create(
            model="gpt-4.1-mini",
            input=f"""
This is the current skill definition:

{prompt_content}

## Refinement (iteration {self.iteration})

For tasks like:
"{task}"

Expected API calls:
{expected_apis}

Actual API calls made:
{actual_calls}

Return a refined SKILL.md including the frontmatter, no explanations.
""",
            temperature=0.3
        )

        refined_content = response.output_text
        self.iteration += 1
        Path(skill_file).write_text(refined_content)
        return refined_content