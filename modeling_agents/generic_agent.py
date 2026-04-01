import json
import subprocess
import tempfile
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


class GenericModelingAgent:
    def __init__(self, mcp_server_script: str, prompt: str = None):
        self.mcp_server_script = mcp_server_script
        self.evaluation_history = []

    def _build_gemini_settings(self, mcp_server_script: str) -> dict:
        return {
            "mcpServers": {
                "modeling_server": {
                    "command": "python3",
                    "args": [str(Path(mcp_server_script).resolve())]
                }
            },       
            "model": { "name": "gemini-2.5-flash"
            },
        "autoUpdate": False,
        "selectedAuthType": "apiKey"
            }

    def _parse_tool_calls_from_activity_log(self, log_path: Path) -> list[dict]:
        if not log_path.exists():
            return []

        tool_calls = []
        for line in log_path.read_text().splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            payload = event.get("payload", {})
            bodies = [
                payload.get("response", {}).get("body", ""),
                payload.get("chunk", {}).get("data", ""),
            ]

            for body in filter(None, bodies):
                for sse_line in body.splitlines():
                    if not sse_line.startswith("data:"):
                        continue
                    try:
                        data = json.loads(sse_line[5:])
                    except json.JSONDecodeError:
                        continue

                    for candidate in data.get("candidates", []):
                        for part in candidate.get("content", {}).get("parts", []):
                            if fc := part.get("functionCall"):
                                tool_calls.append({
                                    "api_name": fc.get("name"),
                                    "arguments": fc.get("args", {}),
                                })
        return tool_calls
    
    def _run_gemini_with_mcp(self, task: str) -> tuple[str, list[dict]]:
        settings = self._build_gemini_settings(self.mcp_server_script)

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            settings_path = tmp_path / "settings.json"
            settings_path.write_text(json.dumps(settings, indent=2))
            activity_log_path = tmp_path / "activity.jsonl"

            env = os.environ.copy()
            env["GEMINI_CONFIG_DIR"] = tmp_dir
            env["GEMINI_API_KEY"] = os.getenv("GEMINI_API_KEY", "").strip()
            env["GEMINI_CLI_ACTIVITY_LOG_TARGET"] = str(activity_log_path)


            result = subprocess.run(
                ["gemini", "-p", task, "--output-format", "json", "--yolo",
                 "--model", "gemini-2.5-flash"],
                capture_output=True,
                text=True,
                timeout=300,
                env=env,
            )

            actual_calls = self._parse_tool_calls_from_activity_log(activity_log_path)          
            print(f">>> Tool calls from activity log: {actual_calls}")

        if result.returncode != 0:
            raise RuntimeError(f"Gemini CLI error:\n{result.stderr.strip()}")

        gemini_json = json.loads(result.stdout)
        final_output = gemini_json.get("response", "")

        return final_output, actual_calls

    def run(self, task: str, file: str) -> tuple[str, list[dict]]:
        agents_md = Path(file).read_text()
        full_task = f"{agents_md}\n\nTask: {task}"
        return self._run_gemini_with_mcp(full_task)