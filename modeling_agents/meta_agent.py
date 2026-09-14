import json
import os
import re
from collections import defaultdict
from pathlib import Path
from datetime import datetime
from openai import OpenAI
from modeling_agents.generic_agent import GenericModelingAgent

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)


class MetaAgent:

    def __init__(self, agent_class=GenericModelingAgent,
        mcp_server_script="mcp_servers/emf/emf_server.py",
        apply_skill=".opencode/skills/emf-write/SKILL.md",
        get_skill=".opencode/skills/emf-read/SKILL.md",
        metamodel_file: str = None,
        iteration=0):
        self.apply_skill = apply_skill
        self.get_skill = get_skill
        self.iteration = iteration
        self.agent = agent_class(
            mcp_server_script=mcp_server_script,
            project_root=PROJECT_ROOT,
            metamodel_file=metamodel_file,
        )

    def _append_log(self, log_file: str, line: str) -> None:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def _skill_for(self, expected_apis: list[dict]) -> str:
        read_verbs = ("list", "inspect", "get")
        if any(e["api_name"].split("_")[0] in read_verbs for e in expected_apis):
            return self.get_skill
        return self.apply_skill

    def _normalize_api_name(self, name: str) -> str:
        name = name or ""
        for prefix in ("modeling_server_", "server_"):
            if name.startswith(prefix):
                return name[len(prefix):]
        return name

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
        grouped = defaultdict(list)
        for f in failures:
            sig = self._failure_signature(f["expected_apis"], f["actual_calls"])
            grouped[sig].append(f)

        sorted_groups = sorted(grouped.items(), key=lambda item: len(item[1]), reverse=True)

        selected = []
        for _, items in sorted_groups:
            if len(selected) >= max_examples:
                break
            selected.append(items[0])

        if len(selected) < max_examples:
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

    def evaluate_no_skill_baseline(self, dataset: list[dict], log_file: str) -> float:
        scores = []
        for sample in dataset:
            _, actual_calls = self.agent.run(sample["instruction"], file=None)
            score = self.evaluate(actual_calls, sample["relevant_apis"])
            scores.append(score)
            self._append_log(log_file, f"BASELINE | score={score:.2f}")
        avg = sum(scores) / len(scores)
        self._append_log(log_file, f"BASELINE avg_score={avg:.2f}")
        print(f">>> No-skill baseline score: {avg:.2f}")
        return avg

    def evaluate_on_test_set(self, test_dataset: list[dict], log_file: str) -> float:
        scores = []
        for sample in test_dataset:
            skill_file = self._skill_for(sample["relevant_apis"])
            _, actual_calls = self.agent.run(sample["instruction"], skill_file)
            score = self.evaluate(actual_calls, sample["relevant_apis"])
            scores.append(score)
            self._append_log(log_file, f"TEST | score={score:.2f}")
        avg = sum(scores) / len(scores)
        self._append_log(log_file, f"TEST avg_score={avg:.2f}")
        print(f">>> Held-out test score: {avg:.2f}")
        return avg

    def specialize_agent(
        self,
        dataset: list[dict],
        threshold: float = 0.5,
        max_iterations: int = 5,
        log_file: str = "debug_logs/specialization_iterations1.txt",
        checkpoint_file: str = None,
    ):
        results = [(sample, None, None) for sample in dataset]

        # Restore from iteration checkpoint if available
        if checkpoint_file and Path(checkpoint_file).exists():
            iter_cp = json.loads(Path(checkpoint_file).read_text())
            self.iteration = iter_cp["iteration"] + 1
            Path(self.apply_skill).write_text(iter_cp["skill_apply"])
            Path(self.get_skill).write_text(iter_cp["skill_get"])
            self._append_log(log_file, f"Resuming from iteration {self.iteration} (checkpoint restored)")
            print(f">>> Resuming specialization from iteration {self.iteration}")

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

            for i, (sample, _, _prev_calls) in enumerate(results):
                expected_apis = sample["relevant_apis"]
                skill_file = self._skill_for(expected_apis)
                _, actual_calls = self.agent.run(sample["instruction"], skill_file)
                score = self.evaluate(actual_calls, expected_apis)
                print(f"\n--- Sample {i + 1} | score={score:.2f} ---")
                print(f"  Expected: {[e['api_name'] for e in expected_apis]}")
                print(f"  Actual calls ({len(actual_calls)}):")
                for c in actual_calls:
                    print(f"    {c['api_name']}  args={c.get('arguments', {})}")
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

            # Save iteration checkpoint
            if checkpoint_file:
                iter_cp = {
                    "iteration": self.iteration,
                    "avg_score": avg_score,
                    "skill_apply": Path(self.apply_skill).read_text(),
                    "skill_get": Path(self.get_skill).read_text(),
                }
                Path(checkpoint_file).write_text(json.dumps(iter_cp, indent=2))

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
                        f"Iteration {self.iteration} | refining skill={skill_file} | "
                        f"failures={payload['total_failures']} | patterns={payload['distinct_patterns']} | "
                        f"examples_used={len(payload['examples'])}"
                    ),
                )
                backup = Path(skill_file).read_text()
                try:
                    self.refine_agent_definition_batch(
                        failures_payload=payload,
                        skill_file=skill_file,
                        backup=backup,
                    )
                    refined_in_iteration += 1
                except Exception as e:
                    Path(skill_file).write_text(backup)
                    self._append_log(
                        log_file,
                        (
                            f"Iteration {self.iteration} refinement error | "
                            f"skill={skill_file} | error={e} | backup restored"
                        ),
                    )

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

    def _parse_args_string(self, args_str: str) -> dict:
        result = {}
        for token in args_str.split(","):
            token = token.strip()
            if not token or token in ("session_id", "object_id"):
                continue
            if "=" in token:
                k, _, v = token.partition("=")
                if k.strip().lower() == "object_id":
                    continue
                result[k.strip().lower()] = v.strip().lower()
        return result

    def _args_match(self, exp_args, actual: dict) -> bool:
        if isinstance(exp_args, str):
            exp_dict = self._parse_args_string(exp_args)
        elif isinstance(exp_args, dict):
            exp_dict = {k.lower(): str(v).lower() for k, v in exp_args.items() if k not in ("session_id", "object_id")}
        else:
            return True

        if not exp_dict:
            return True

        act_raw = actual.get("arguments", {})
        if isinstance(act_raw, str):
            try:
                act_raw = json.loads(act_raw)
            except (json.JSONDecodeError, TypeError):
                act_raw = {}
        act_dict = {k.lower(): str(v).lower() for k, v in act_raw.items() if k != "session_id"}

        return all(act_dict.get(k) == v for k, v in exp_dict.items())

    def evaluate(self, actual_tool_calls: list[dict], expected_apis: list[dict]) -> float:
        if not expected_apis:
            return 1.0
        matched = 0
        for expected in expected_apis:
            exp_name = self._normalize_api_name(expected.get("api_name", ""))
            exp_args = expected.get("arguments")
            for actual in actual_tool_calls:
                act_name = self._normalize_api_name(actual.get("api_name", ""))
                if act_name != exp_name:
                    continue
                if self._args_match(exp_args, actual):
                    matched += 1
                    break
        return matched / len(expected_apis)

    def refine_agent_definition_batch(self, failures_payload: dict, skill_file: str, backup: str = None) -> str:
        openai_model = os.getenv("EVAL_SYSTEM_MODEL") or os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
        client = OpenAI(timeout=60.0, max_retries=2)

        prompt_content = Path(skill_file).read_text()
        top_patterns = failures_payload.get("pattern_summary", [])[:10]
        examples = failures_payload.get("examples", [])[:8]

        missing_tools = sorted({
            name
            for p in top_patterns
            for name in p["expected_tools"]
            if name and name not in prompt_content
        })

        compact_examples = [
            {
                "instruction": e["instruction"],
                "expected_sequence": [self._normalize_api_name(a["api_name"]) for a in e["expected_apis"]],
                "actual_called": [self._normalize_api_name(a["api_name"]) for a in e["actual_calls"]],
            }
            for e in examples
        ]

        response = client.chat.completions.create(
            model=openai_model,
            temperature=0.1,
            messages=[
                {
                    "role": "user",
                    "content": f"""You are improving an AI agent skill file based on observed failures.

Current SKILL.md:
{prompt_content}

Observed failure patterns (expected tool sequence vs what agent actually called):
{json.dumps(top_patterns, indent=2)}

Concrete failing examples:
{json.dumps(compact_examples, indent=2)}

Tools completely missing from the skill:
{json.dumps(missing_tools, indent=2)}

Analyze the failures and rewrite the skill to fix:
1. The agent stops after one tool call — add explicit sequencing rules showing which tools must be called together and in what order
2. The agent calls the wrong tool — add clarifications distinguishing similar tools
3. Add any missing tools under ## Available MCP Tools with a one-line description

Rules:
- Return ONLY raw markdown, no code fences, no ```markdown, no ``` wrapping
- Do NOT change the frontmatter (--- block at the top)
- Do NOT remove any existing tool entries
- Return the FULL updated SKILL.md
"""
                }
            ],
        )

        refined_content = response.choices[0].message.content.strip()
        refined_content = re.sub(r'^```[^\n]*\n', '', refined_content, flags=re.MULTILINE)
        refined_content = re.sub(r'```$', '', refined_content, flags=re.MULTILINE).strip()

        if backup:
            if len(refined_content) < len(backup) * 0.85:
                Path(skill_file).write_text(backup)
                return backup
            original_tools = re.findall(r'`(\w+_tool)`', backup)
            refined_tools = re.findall(r'`(\w+_tool)`', refined_content)
            if not all(t in refined_tools for t in original_tools):
                Path(skill_file).write_text(backup)
                return backup

        Path(skill_file).write_text(refined_content)
        return refined_content