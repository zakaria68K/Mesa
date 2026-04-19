import json
import os
import subprocess
import tempfile
from pathlib import Path
import re

class GenericModelingAgent:
    def __init__(self, mcp_server_script: str, prompt: str = None):
        self.mcp_server_script = mcp_server_script
        self.evaluation_history = []

    def _build_opencode_config(self, mcp_server_script: str) -> dict:
        return {
            "$schema": "https://opencode.ai/config.json",
            "model": "ollama/gemma4:26b",
            "provider": {
                "ollama": {
                    "npm": "@ai-sdk/openai-compatible",
                    "name": "Ollama",
                    "options": {
                        "baseURL": "https://ollama.kher.nl/v1"
                    },
                    "models": {
                        "gemma4:26b": {
                            "name": "Gemma 4 26B"
                        }
                    }
                }
            },
            "mcp": {
                "modeling_server": {
                    "type": "local",
                    "command": [
                        "python3",
                        str(Path(mcp_server_script).resolve())
                    ],
                    "enabled": True
                }
            }
        }

    def _extract_skills_used(self, stderr: str) -> list[str]:
        ansi = re.compile(r'\x1b?\[[\d;]*m')
        skills = []
        for line in (ansi.sub('', l).strip() for l in stderr.splitlines()):
            m = re.search(r'[→⚙✦*]\s+[Ss]kill\s+"([^"]+)"', line)
            if m:
                skills.append(m.group(1))
        return skills

    def _parse_tool_calls_from_stderr(self, stderr: str) -> list[dict]:
        ansi = re.compile(r'\x1b?\[[\d;]*m')
        tool_calls, seen = [], set()
        for line in (ansi.sub('', l).strip() for l in stderr.splitlines()):
            m = (
                re.search(r'service=permission\s+permission=(modeling_server_\S+)\s+pattern=', line)
                or re.search(r'[⚙✦*]\s+(modeling_server_\S+)\s+(\{.*\})', line)
            )
            if not m:
                continue

            name = re.sub(r'^[^_]+_', '', m.group(1), count=1)
            args = json.loads(m.group(2)) if m.lastindex == 2 else {}

            existing = next((t for t in tool_calls if t["api_name"] == name and not t["arguments"]), None)
            if existing and args:
                seen.discard((name, "{}"))
                existing["arguments"] = args
                seen.add((name, json.dumps(args, sort_keys=True)))
            elif (name, json.dumps(args, sort_keys=True)) not in seen:
                seen.add((name, json.dumps(args, sort_keys=True)))
                tool_calls.append({"api_name": name, "arguments": args})
        return tool_calls

    def _run_opencode_with_mcp(self, task: str) -> tuple[str, list[dict]]:
        config = self._build_opencode_config(self.mcp_server_script)

        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "opencode.json"
            config_path.write_text(json.dumps(config, indent=2))
            env = os.environ.copy()
            env["OPENCODE_CONFIG"] = str(config_path)

            log_path = Path("opencode_logs") / f"opencode_6.txt"
            log_path.parent.mkdir(exist_ok=True)

            try:
                result = subprocess.run(
                    ["opencode", "run", "--print-logs", "--dir", str(Path.cwd()), task],
                    capture_output=True,
                    text=True,
                    timeout=300,
                    env=env,
                )
                stdout = result.stdout
                stderr = result.stderr
            except subprocess.TimeoutExpired as e:
                stdout = e.stdout or ""
                stderr = e.stderr or ""
                if isinstance(stdout, bytes):
                    stdout = stdout.decode("utf-8", errors="replace")
                if isinstance(stderr, bytes):
                    stderr = stderr.decode("utf-8", errors="replace")
                log_path.write_text(
                    f"=== TIMEOUT ===\nCommand timed out after 300 seconds\n\n"
                    f"=== PARTIAL STDOUT ===\n{stdout}\n\n=== PARTIAL STDERR ===\n{stderr}"
                )
                print(f">>> Logs written to: {log_path}")
                return "", []

            log_path.write_text(f"=== STDOUT ===\n{stdout}\n\n=== STDERR ===\n{stderr}")
            print(f">>> Logs written to: {log_path}")

        skills_used = self._extract_skills_used(stderr)
        print(f">>> Skills used: {skills_used}")
        if result.returncode != 0:
            raise RuntimeError(f"opencode error:\n{stderr[:500]}")
        tool_calls = self._parse_tool_calls_from_stderr(stderr)
        print(f">>> Tool calls parsed: {tool_calls}")

        return stdout.strip(), tool_calls

    def run(self, task: str, file: str) -> tuple[str, list[dict]]:
        skill_name = Path(file).parent.name if file else None
        if skill_name:
            full_task = (
                f'Before doing anything, you MUST load the skill "{skill_name}" with the skill tool. '
                f'Do not load any other skill unless explicitly asked. '
                "After loading it, strictly follow that skill and use only the MCP tools required by the task.\n\n"
                f"Task: {task}"
            )
        else:
            full_task = (
                "Before doing anything, load the appropriate skill using the skill tool. "
                "Then use the MCP tools as instructed by the skill.\n\n"
                f"Task: {task}"
            )
        return self._run_opencode_with_mcp(full_task)