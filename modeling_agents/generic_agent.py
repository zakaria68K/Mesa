import datetime
import json
import os
import subprocess
import sys
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
        strip_prefix = lambda n: re.sub(r'^[^_]+_', '', n, count=1)
        tool_calls, seen = [], set()
        for line in (ansi.sub('', l).strip() for l in stderr.splitlines()):
            m = re.search(r'service=permission\s+permission=(modeling_server_\S+)\s+pattern=', line) \
            or re.search(r'[⚙✦*]\s+(modeling_server_\S+)\s+(\{.*\})', line)
            if not m: continue
            name = strip_prefix(m.group(1))
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
            env["OLLAMA_HOST"] = os.getenv("OLLAMA_HOST", "http://localhost:11434")

            log_path = Path("opencode_logs") / f"opencode_6.txt"
            log_path.parent.mkdir(exist_ok=True)

            result = subprocess.run(
                ["opencode", "run", "--print-logs", "--dir", str(Path.cwd()), task],
                capture_output=True,
                text=True,
                timeout=300,
                env=env,
            )

            log_path.write_text(f"=== STDOUT ===\n{result.stdout}\n\n=== STDERR ===\n{result.stderr}")
            print(f">>> Logs written to: {log_path}")

        skills_used = self._extract_skills_used(result.stderr)
        print(f">>> Skills used: {skills_used}")
        if result.returncode != 0:
            raise RuntimeError(f"opencode error:\n{result.stderr[:500]}")
        tool_calls = self._parse_tool_calls_from_stderr(result.stderr)
        print(f">>> Tool calls parsed: {tool_calls}")

        return result.stdout.strip(), tool_calls
    
    def run(self, task: str, file: str) -> tuple[str, list[dict]]:
        full_task = (
            "Before doing anything, load the appropriate skill using the skill tool. "
            "Then use the MCP tools as instructed by the skill.\n\n"
            f"Task: {task}"
        )
        return self._run_opencode_with_mcp(full_task)