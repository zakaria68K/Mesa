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
        # Initialize results: None means "not yet run"
        results = [(sample, None, None) for sample in dataset]

        while True:
            for i, (sample, score, actual_calls) in enumerate(results):
                if score == 1.0:  # skip already passing samples
                    continue
                output, actual_calls = self.agent.run(sample["instruction"], None)
                expected_apis = sample["relevant_apis"]
                score = self.evaluate(actual_calls, expected_apis)
                print(f"  Score: {score:.2f} | Expected: {expected_apis} | Got: {actual_calls}")
                results[i] = (sample, score, actual_calls)
                self.agent.evaluation_history.append({
                    "instruction": sample["instruction"],
                    "score": score,
                    "expected": expected_apis,
                    "actual": actual_calls
                })

            scores = [r[1] for r in results]
            avg_score = sum(scores) / len(scores)
            print(f"Iteration {self.iteration} — avg score: {avg_score:.2f}")

            if avg_score >= threshold:
                print("Threshold met. Specialization complete.")
                break

            for sample, score, actual_calls in results:
                if score < 1.0:
                    skill_file = self._skill_for(sample["relevant_apis"])
                    self.refine_agent_definition(
                        sample["instruction"],
                        actual_calls,
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

        mismatch_analysis = []
        for expected, actual in zip(expected_apis, actual_calls):
            if expected["api_name"] != actual["api_name"]:
                mismatch_analysis.append(
                    f"- Task segment led to: `{actual['api_name']}` "
                    f"but expected: `{expected['api_name']}`"
                )
        mismatch_str = "\n".join(mismatch_analysis) if mismatch_analysis else "- No matching calls were made."

        response = client.responses.create(
            model="gpt-4.1-mini",
            input=f"""
    You are refining an agent skill definition file.

    Current skill:
    {prompt_content}

    A task failed. Here are the details:
    - Task: "{task}"
    - Expected API calls: {expected_apis}
    - Actual API calls made: {actual_calls}

    ## Key insight about the failure
    The following tool name mismatches were observed:
    {mismatch_str}

    Analyze why the agent picked the wrong tools given the task and expected vs actual calls above,
    then update the skill to prevent this mistake.

    Rewrite the skill as a single clean SKILL.md.
    Rules:
    - Keep the frontmatter (---) unchanged.
    - DO NOT append iteration history or refinement blocks.
    - DO NOT include any explanation or commentary outside the skill content.
    - Consolidate all guidance into the existing sections.
    - Return ONLY the final skill content, nothing else.
    """,
            temperature=0.3
        )

        refined_content = response.output_text
        self.iteration += 1
        Path(skill_file).write_text(refined_content)
        return refined_content