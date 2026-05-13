import json
import re
from collections import defaultdict
from pathlib import Path
from datetime import datetime
from openai import OpenAI
from modeling_agents.generic_agent import GenericModelingAgent

# The directory that contains .opencode/skills/ and the atl_zoo/ data.
# Adjust this if your layout differs.
PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)


class MetaAgent:

    def __init__(self, agent_class=GenericModelingAgent,
        mcp_server_script="mcp_servers/emf/emf_server.py",
        apply_skill=".opencode/skills/emf-write/SKILL.md",
        get_skill=".opencode/skills/emf-read/SKILL.md",
        iteration=0):
        self.apply_skill = apply_skill
        self.get_skill = get_skill
        self.iteration = iteration
        self.agent = agent_class(
            mcp_server_script=mcp_server_script,
            project_root=PROJECT_ROOT,
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

    def _normalize_actual_args(self, actual: dict) -> str | None:
        actual_args = actual.get("arguments", {})
        if isinstance(actual_args, dict):
            for key in ("file_path", "source_file", "input_file", "path"):
                if key in actual_args:
                    val = actual_args[key]
                    return val if isinstance(val, str) else None
            for v in actual_args.values():
                if isinstance(v, str):
                    return v
        return None

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

    def specialize_agent(
        self,
        dataset: list[dict],
        threshold: float = 0.5,
        max_iterations: int = 10,
        log_file: str = "debug_logs/specialization_iterations1.txt",
    ):
        results = [(sample, None, None) for sample in dataset]
        prev_avg_score = None

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
                        f"Iteration {self.iteration} | refining skill={skill_file} | "
                        f"failures={payload['total_failures']} | patterns={payload['distinct_patterns']} | "
                        f"examples_used={len(payload['examples'])}"
                    ),
                )
                backup = Path(skill_file).read_text()

                # If score already regressed vs previous iteration, skip refinement
                if prev_avg_score is not None and avg_score < prev_avg_score - 0.05:
                    self._append_log(
                        log_file,
                        (
                            f"Iteration {self.iteration} | skipping refinement for {skill_file}: "
                            f"score regressed ({prev_avg_score:.2f} -> {avg_score:.2f}), restoring backup"
                        ),
                    )
                    Path(skill_file).write_text(backup)
                    continue

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
                    raise

            self._append_log(
                log_file,
                f"Iteration {self.iteration} refinement_count={refined_in_iteration}",
            )

            prev_avg_score = avg_score
            self.iteration += 1

        self._append_log(
            log_file,
            f"Specialization finished at {datetime.now().isoformat(timespec='seconds')}"
        )
        self._append_log(log_file, "=" * 80)

        return self.apply_skill, self.get_skill

    def _parse_args_string(self, args_str: str) -> dict:
        """Parse 'session_id, class_name=foo, feature_name=bar' into {'class_name': 'foo', ...}.
        Bare tokens (like 'session_id') that have no '=' are ignored."""
        result = {}
        for token in args_str.split(","):
            token = token.strip()
            if not token or token == "session_id":
                continue
            if "=" in token:
                k, _, v = token.partition("=")
                result[k.strip().lower()] = v.strip().lower()
        return result

    def _args_match(self, exp_args, actual: dict) -> bool:
        """Compare expected args against an actual call's arguments dict, ignoring session_id."""
        # Build expected dict (strip session_id)
        if isinstance(exp_args, str):
            exp_dict = self._parse_args_string(exp_args)
        elif isinstance(exp_args, dict):
            exp_dict = {k.lower(): str(v).lower() for k, v in exp_args.items() if k != "session_id"}
        else:
            return True  # no constraint

        if not exp_dict:
            return True  # only session_id was specified — no real constraint

        # Build actual dict (strip session_id)
        act_raw = actual.get("arguments", {})
        if isinstance(act_raw, str):
            try:
                act_raw = json.loads(act_raw)
            except (json.JSONDecodeError, TypeError):
                act_raw = {}
        act_dict = {k.lower(): str(v).lower() for k, v in act_raw.items() if k != "session_id"}

        # Every expected key must be present with a matching value
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
        client = OpenAI(
            base_url="https://ollama.kher.nl/v1",
            api_key="ollama",
            timeout=120.0,
            max_retries=2,
        )
        prompt_content = Path(skill_file).read_text()
        top_patterns = failures_payload.get("pattern_summary", [])[:10]
        examples = failures_payload.get("examples", [])[:8]

        # Collect tool names that were expected but are completely absent from the skill text.
        # These are the primary cause of failures: the agent cannot call a tool it doesn't know exists.
        missing_tools = sorted({
            name
            for p in top_patterns
            for name in p["expected_tools"]
            if name and name not in prompt_content
        })

        # Compact example list: instruction + expected tool name + actual tool called
        compact_examples = [
            {
                "instruction": e["instruction"],
                "expected": [self._normalize_api_name(a["api_name"]) for a in e["expected_apis"]],
                "actual_called": [self._normalize_api_name(a["api_name"]) for a in e["actual_calls"]],
            }
            for e in examples
        ]

        response = client.chat.completions.create(
            model="gemma4:26b",
            messages=[
                {
                    "role": "user",
                    "content": f"""You must update this SKILL.md by adding missing tool entries.

Current SKILL.md:
{prompt_content}

The agent failed because it tried to perform tasks that required tools not listed in the skill.

Tools that are MISSING from the skill and caused failures ({len(missing_tools)} tools):
{json.dumps(missing_tools, ensure_ascii=False, indent=2)}

Failing examples showing what tool was needed vs what was called:
{json.dumps(compact_examples, ensure_ascii=False, indent=2)}

Instructions:
- Keep the frontmatter (---) and all existing content EXACTLY unchanged
- For each tool in the missing tools list, append one bullet under ## Available MCP Tools:
  `- \`<tool_name>_tool\` — [infer a one-line description from the tool name]`
- Do NOT remove, reorder, or rewrite any existing tool entries
- Do NOT add commentary, headers, or explanation outside the tool list
- Add only minimal clarifications to prevent repeating these mistakes
- Return ONLY the complete raw SKILL.md content with no markdown fences
"""
                }
            ],
            temperature=0.1,
        )

        refined_content = response.choices[0].message.content
        # Strip markdown code fences Gemma tends to add
        refined_content = re.sub(r'^```[^\n]*\n', '', refined_content.strip(), flags=re.MULTILINE)
        refined_content = re.sub(r'\n```$', '', refined_content.strip(), flags=re.MULTILINE)
        refined_content = refined_content.strip()

        # Sanity check: if Gemma returned something suspiciously short, restore backup
        if backup and len(refined_content) < len(backup) * 0.5:
            Path(skill_file).write_text(backup)
            return backup

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