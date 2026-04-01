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
            "model": {
                "name": "gemini-2.5-flash-lite"  #  disable routing
            }
        }

    def _parse_tool_calls_from_activity_log(self, log_path: Path) -> list[dict]:
        tool_calls = []
        if not log_path.exists():
            return tool_calls

        for line in log_path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
                if event.get("type") == "tool_call" or "functionCall" in event:
                    func = event.get("functionCall") or event
                    tool_calls.append({
                        "api_name": func.get("name") or event.get("tool_name"),
                        "arguments": func.get("args") or event.get("arguments", {}),
                    })
            except json.JSONDecodeError:
                continue

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
                ["gemini", "-p", task, "--output-format", "stream-json", "--yolo",
                "--model", "gemini-2.5-flash-lite"],
                capture_output=True,
                text=True,
                timeout=300,
                env=env,
            )

            print(f" Subprocess return code: {result.returncode}")
            print(f" stderr: {result.stderr[:300] if result.stderr else 'empty'}")

            # Print every stream-json event
            print("\n STREAM EVENTS:")
            events = []
            for line in result.stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    events.append(event)
                    print(f"  [{event.get('type', 'unknown')}] {json.dumps(event, indent=2)}")
                except json.JSONDecodeError:
                    print(f"  [raw] {line}")

            # Print raw activity log
            print("\n>>> ACTIVITY LOG:")
            if activity_log_path.exists():
                raw = activity_log_path.read_text()
                print(f"  ({len(raw)} bytes)")
                for line in raw.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        print(f"  {json.dumps(json.loads(line), indent=2)}")
                    except json.JSONDecodeError:
                        print(f"  [raw] {line}")
            else:
                print("  Activity log does NOT exist")

            actual_calls = self._parse_tool_calls_from_activity_log(activity_log_path)
            print(f"\n>>> Tool calls parsed: {actual_calls}")

        # Extract final response from stream events
        final_output = ""
        for event in reversed(events):
            if event.get("type") == "content" and event.get("role") == "model":
                final_output = event.get("text", "")
                break
            if "response" in event:
                final_output = event["response"]
                break

        return final_output, actual_calls

    def run(self, task: str, file: str) -> tuple[str, list[dict]]:
        agents_md = Path(file).read_text()
        full_task = f"{agents_md}\n\nTask: {task}"
        return self._run_gemini_with_mcp(full_task)