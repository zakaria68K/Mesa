import json
from collections import defaultdict
from pathlib import Path
from datetime import datetime
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

    def _append_log(self, log_file: str, line: str) -> None:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def _skill_for(self, expected_apis: list[dict]) -> str:
        if any("list" in e["api_name"] for e in expected_apis):
            return self.get_skill
        return self.apply_skill

    def _normalize_api_name(self, name: str) -> str:
        return (name or "").removeprefix("server_")
    
    def _normalize_actual_args(self, actual: dict) -> str | None:
        actual_args = actual.get("arguments", {}).get("file_path")
        if isinstance(actual_args, dict):
            return next((actual_args[k] for k in ("file_path", "source_file", "input_file", "path") if k in actual_args), next(iter(actual_args.values()), None))
        return actual_args or None

    def _failure_signature(self, expected_apis: list[dict], actual_calls: list[dict]) -> tuple:
        expected_names = tuple(self._normalize_api_name(e.get("api_name", "")) for e in expected_apis)
        actual_names = tuple(self._normalize_api_name(a.get("api_name", "")) for a in actual_calls)
        return expected_names, actual_names

    def _build_failure_payload(
        self,
        failures: list[dict],
        max_examples: int = 12,
        max_total_instruction_chars: int = 1600,
    ) -> dict:
        """Build a compact failure payload for refinement."""
        grouped = defaultdict(list)
        for f in failures:
            sig = self._failure_signature(f["expected_apis"], f["actual_calls"])
            grouped[sig].append(f)

        sorted_groups = sorted(grouped.items(), key=lambda item: len(item[1]), reverse=True)

        selected = []
        # First pass: 1 per group
        for _, items in sorted_groups:
            if len(selected) >= max_examples:
                break
            selected.append(items[0])

        if len(selected) < max_examples:
            # Second pass: fill remaining
            for _, items in sorted_groups:
                for item in items[1:]:
                    if len(selected) >= max_examples:
                        break
                    selected.append(item)
                if len(selected) >= max_examples:
                    break

        total_chars = 0
        trimmed_selected = []
        for item in selected:
            instruction = item.get("instruction", "")
            remaining = max_total_instruction_chars - total_chars
            if remaining <= 0:
                break
            if len(instruction) > remaining:
                instruction = instruction[: max(0, remaining - 3)] + "..."
            total_chars += len(instruction)
            trimmed_item = dict(item)
            trimmed_item["instruction"] = instruction
            trimmed_selected.append(trimmed_item)

        pattern_summary = []
        for (expected_names, actual_names), items in sorted_groups:
            pattern_summary.append(
                {
                    "count": len(items),
                    "expected_tools": list(expected_names),
                    "actual_tools": list(actual_names),
                }
            )

        return {
            "total_failures": len(failures),
            "distinct_patterns": len(sorted_groups),
            "pattern_summary": pattern_summary,
            "examples": trimmed_selected,
        }

    def specialize_agent(
        self,
        dataset: list[dict],
        threshold: float = 0.5,
        max_iterations: int = 10,
        log_file: str = "debug_logs/specialization_iterations.txt",
    ):
        results = [(sample, None, None) for sample in dataset]

        self._append_log(log_file, "=" * 80)
        self._append_log(
            log_file,
            (
                f"Specialization run started at {datetime.now().isoformat(timespec='seconds')} | "
                f"samples={len(dataset)} | threshold={threshold} | max_iterations={max_iterations}"
            ),
        )

        while True:
            refined_in_iteration = 0
            self._append_log(log_file, "-" * 80)
            self._append_log(log_file, f"Iteration {self.iteration} started")

            for i, (sample, _, actual_calls) in enumerate(results):
                expected_apis = sample["relevant_apis"]
                skill_file = self._skill_for(expected_apis)
                _, actual_calls = self.agent.run(sample["instruction"], skill_file)
                score = self.evaluate(actual_calls, expected_apis)
                self._append_log(
                    log_file,
                    (
                        f"Iteration {self.iteration} | sample={i + 1}/{len(results)} | "
                        f"score={score:.2f}"
                    ),
                )
                results[i] = (sample, score, actual_calls)
                self.agent.evaluation_history.append({
                    "instruction": sample["instruction"],
                    "score": score,
                    "expected": expected_apis,
                    "actual": actual_calls
                })

            scores = [r[1] for r in results]
            avg_score = sum(scores) / len(scores)
            failing_samples = sum(1 for s in scores if s < 1.0)
            self._append_log(
                log_file,
                (
                    f"Iteration {self.iteration} summary | avg_score={avg_score:.2f} | "
                    f"failing_samples={failing_samples}/{len(results)}"
                ),
            )

            if avg_score >= threshold:
                self._append_log(
                    log_file,
                    (
                        f"Iteration {self.iteration} exit: threshold met "
                        f"(avg_score={avg_score:.2f} >= {threshold})"
                    ),
                )
                break

            if self.iteration >= max_iterations:
                self._append_log(
                    log_file,
                    (
                        f"Iteration {self.iteration} exit: max_iterations reached "
                        f"(max_iterations={max_iterations}, avg_score={avg_score:.2f})"
                    ),
                )
                break

            self._append_log(log_file, f"Iteration {self.iteration} refinement phase started")
            failures_by_skill = defaultdict(list)
            for sample, score, actual_calls in results:
                if score < 1.0:
                    skill_file = self._skill_for(sample["relevant_apis"])
                    failures_by_skill[skill_file].append(
                        {
                            "instruction": sample["instruction"],
                            "expected_apis": sample["relevant_apis"],
                            "actual_calls": actual_calls,
                        }
                    )

            for skill_file, failures in failures_by_skill.items():
                payload = self._build_failure_payload(failures)
                self._append_log(
                    log_file,
                    (
                        f"Iteration {self.iteration} | refining skill={Path(skill_file).name} | "
                        f"failures={payload['total_failures']} | patterns={payload['distinct_patterns']} | "
                        f"examples_used={len(payload['examples'])}"
                    ),
                )
                try:
                    self.refine_agent_definition_batch(
                        failures_payload=payload,
                        skill_file=skill_file,
                    )
                    refined_in_iteration += 1
                except Exception as e:
                    self._append_log(
                        log_file,
                        (
                            f"Iteration {self.iteration} refinement error | "
                            f"skill={Path(skill_file).name} | error={e}"
                        ),
                    )
                    raise

            self._append_log(
                log_file,
                f"Iteration {self.iteration} refinement_count={refined_in_iteration}",
            )

            self.iteration += 1

        self._append_log(
            log_file,
            f"Specialization finished at {datetime.now().isoformat(timespec='seconds')}"
        )
        self._append_log(log_file, "=" * 80)

        return self.apply_skill, self.get_skill

    def evaluate(self, actual_tool_calls: list[dict], expected_apis: list[dict]) -> float:
        if not expected_apis:
            return 1.0
        for expected in expected_apis:
            match_found = False
            for actual in actual_tool_calls:
                actual_name = (actual.get("api_name") or "").removeprefix("server_")
                if actual_name != expected["api_name"]:
                    continue

                expected_args = expected.get("arguments")
                actual_args = self._normalize_actual_args(actual)

                if isinstance(expected_args, str):
                    try:
                        expected_args = json.loads(expected_args)
                    except (json.JSONDecodeError, TypeError):
                        pass

                expected_args = expected_args or None

                if expected_args == actual_args:
                    match_found = True
                    break
            if not match_found:
                return 0.0
        return 1.0

    def refine_agent_definition_batch(self, failures_payload: dict, skill_file: str) -> str:
        client = OpenAI(
            base_url="https://ollama.kher.nl/v1",
            api_key="ollama",
        )
        prompt_content = Path(skill_file).read_text()
        top_patterns = failures_payload.get("pattern_summary", [])[:10]
        examples = failures_payload.get("examples", [])[:8]

        response = client.chat.completions.create(
            model="gemma4:26b",
            messages=[
                {
                    "role": "user",
                    "content": f"""
Refine this SKILL.md with small incremental edits only.

Current SKILL.md:
{prompt_content}

Score/Error context:
- failing_items: {failures_payload['total_failures']}
- distinct_error_patterns: {failures_payload['distinct_patterns']}

Top tool-mismatch patterns:
{json.dumps(top_patterns, ensure_ascii=False, indent=2)}

Representative failing examples:
{json.dumps(examples, ensure_ascii=False, indent=2)}

Instructions:
- Keep the same SKILL.md structure and section order
- Keep the frontmatter (---) unchanged
- Add only minimal clarifications to prevent repeating these mistakes
- Do not rewrite unrelated parts
- Do not overfit to one example
- Return only the updated SKILL.md content
"""
                }
            ],
            temperature=0.3,
        )

        refined_content = response.choices[0].message.content
        Path(skill_file).write_text(refined_content)
        return refined_content

    def refine_agent_definition(self, task: str, actual_calls: list[dict],
                                expected_apis: list[dict], skill_file: str) -> str:
        """Backward-compatible single-sample wrapper over batched refinement."""
        payload = self._build_failure_payload(
            [
                {
                    "instruction": task,
                    "expected_apis": expected_apis,
                    "actual_calls": actual_calls,
                }
            ],
            max_examples=1,
            max_total_instruction_chars=600,
        )
        return self.refine_agent_definition_batch(payload, skill_file)