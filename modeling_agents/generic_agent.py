import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
import requests


ANSI_RE = re.compile(r'\x1b?\[[\d;]*m')
SKILL_RE = re.compile(r'[→⚙✦*]\s+[Ss]kill\s+"([^"]+)"')
TOOL_PERMISSION_RE = re.compile(r'service=permission\s+permission=(modeling_server_\S+)\s+pattern=')
TOOL_CALL_RE = re.compile(r'[⚙✦*]\s+(modeling_server_\S+)(?:\s+(\{.*\}|Unknown))?')


class GenericModelingAgent:
    def __init__(self, mcp_server_script: str, project_root: str = None, _prompt: str = None, metamodel_file: str = None):
        self.mcp_server_script = mcp_server_script
        self.metamodel_file = metamodel_file
        # project_root must be the directory that contains .opencode/skills/ and the data files.
        # Pass it explicitly from MetaAgent, or it defaults to two levels above this file.
        if project_root:
            self.project_root = str(Path(project_root).resolve())
        else:
            self.project_root = str(Path(__file__).resolve().parent.parent)
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
        skills = []
        for line in (ANSI_RE.sub('', l).strip() for l in stderr.splitlines()):
            m = SKILL_RE.search(line)
            if m:
                skills.append(m.group(1))
        return skills

    def _parse_tool_calls_from_stderr(self, stderr: str) -> list[dict]:
        tool_calls, seen = [], set()
        for line in (ANSI_RE.sub('', l).strip() for l in stderr.splitlines()):
            m = TOOL_PERMISSION_RE.search(line) or TOOL_CALL_RE.search(line)
            if not m:
                continue

            name = re.sub(r'^modeling_server_', '', m.group(1))
            raw_args = m.group(2) if m.lastindex and m.lastindex >= 2 else None
            if raw_args and raw_args != "Unknown":
                try:
                    args = json.loads(raw_args)
                except json.JSONDecodeError:
                    args = {}
            else:
                args = {}
            args_key = json.dumps(args, sort_keys=True)

            existing = next((t for t in tool_calls if t["api_name"] == name and not t["arguments"]), None)
            if existing and args:
                seen.discard((name, "{}"))
                existing["arguments"] = args
                seen.add((name, args_key))
            elif (name, args_key) not in seen:
                seen.add((name, args_key))
                tool_calls.append({"api_name": name, "arguments": args})
        return tool_calls

    def _run_opencode_with_mcp(self, task: str) -> tuple[str, list[dict]]:
        config = self._build_opencode_config(self.mcp_server_script)

        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "opencode.json"
            config_path.write_text(json.dumps(config, indent=2))
            env = os.environ.copy()
            env["OPENCODE_CONFIG"] = str(config_path)

            server_name = Path(self.mcp_server_script).stem  # e.g. "emf_server" or "atl_server"
            log_path = Path("opencode_logs") / f"opencode_{server_name}.txt"
            log_path.parent.mkdir(exist_ok=True)

            try:
                result = subprocess.run(
                    ["opencode", "run", "--print-logs", "--dir", self.project_root, task],
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

    def _start_emf_session(self) -> str:
        emf_base = os.environ.get("EMF_SERVER_BASE", "http://localhost:8096")
        with open(self.metamodel_file, "rb") as f:
            resp = requests.post(f"{emf_base}/metamodel/start", files={"file": f}, timeout=30)
        resp.raise_for_status()
        return resp.json()["sessionId"]

    def run(self, task: str, file: str | None) -> tuple[str, list[dict]]:
        if self.metamodel_file and "$session_id" in task:
            real_session_id = self._start_emf_session()
            task = task.replace("$session_id", real_session_id)
        skill_name = Path(file).parent.name if file else None
        if skill_name:
            full_task = (
                f'Before doing anything, you MUST load the skill "{skill_name}" with the skill tool. '
                f'Do not load any other skill unless explicitly asked. '
                "After loading it, strictly follow that skill. "
                "IMPORTANT: some tasks require multiple sequential tool calls — do NOT stop after the first tool call, complete ALL steps the task requires. "
                "Do NOT use bash, glob, or file-search tools to locate files — pass file paths exactly as given to the MCP tools.\n\n"
                f"Task: {task}"
            )
        else:
            full_task = (
                "Use only the MCP tools available to complete the following task. "
                "Do NOT load any skill. "
                "IMPORTANT: some tasks require multiple sequential tool calls — do NOT stop after the first tool call, complete ALL steps the task requires. "
                "Do NOT use bash, glob, or file-search tools to locate files — pass file paths exactly as given to the MCP tools.\n\n"
                f"Task: {task}"
            )
        return self._run_opencode_with_mcp(full_task)