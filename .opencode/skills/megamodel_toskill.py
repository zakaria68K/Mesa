from pathlib import Path
from typing import List, Dict, Any
import sys
import asyncio
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from megamodel.megamodel import MegamodelRegistry
from megamodel.megamodel_instance import populate_registry

class MegamodelToSkill:
    """Generate SKILL.md files for every (server x capability) pair found in the registry.

    No tool names, descriptions, or rules are hardcoded here — everything is read from
    MegamodelRegistry at generation time.
    """

    def __init__(self, registry=None):
        self.registry = registry

    # ── Rendering ─────────────────────────────────────────────────────────────

    def _render_skill(
        self,
        name: str,
        description: str,
        tools: List[Any],
        rules: List[str],
        server_name: str,
    ) -> str:
        lines = [
            "---",
            f"name: {name}",
            f"description: {description}",
            "---",
            "",
            f"You are a Model-Driven Engineering agent with access to the {server_name} MCP server.",
            "",
        ]

        if rules:
            lines.append("## CRITICAL RULES")
            for rule in rules:
                lines.append(f"- {rule}")
            lines.append("")

        lines.append("## Available MCP Tools")
        for tool in tools[:2]:
            tool_name = tool.name if hasattr(tool, "name") else str(tool)
            tool_desc = getattr(tool, "description", "") or ""
            lines.append(f"- `{tool_name}` — {tool_desc}")
        if len(tools) > 2:
            lines.append(f"- *(and {len(tools) - 2} more tools with the same pattern)*")

        return "\n".join(lines)

    def _save_skill(self, name: str, content: str, base_dir: str = ".opencode/skills") -> Path:
        output_dir = Path(base_dir) / name
        output_dir.mkdir(parents=True, exist_ok=True)
        skill_path = output_dir / "SKILL.md"
        skill_path.write_text(content)
        return skill_path

    # ── Tool matching ──────────────────────────────────────────────────────────

    def _tools_for_capability(self, server_name: str, capability) -> List[Any]:
        """Return tools registered for *server_name* whose names match any keyword
        in *capability.tool_keywords*.  If the keyword list is empty, return all
        tools for that server."""
        all_tools = self.registry.tools_by_server.get(server_name, [])
        keywords = getattr(capability, "tool_keywords", [])
        if not keywords:
            return all_tools
        return [
            t for t in all_tools
            if any(kw.lower() in t.name.lower() for kw in keywords)
        ]

    # ── Public API ─────────────────────────────────────────────────────────────

    def generate_all_skills(self, base_dir: str = ".opencode/skills") -> List[Path]:
        """For every server in the registry, for every capability on that server,
        generate one SKILL.md and return the list of written paths."""
        if self.registry is None:
            raise RuntimeError("No registry attached — pass registry= when constructing MegamodelToSkill.")

        paths = []
        for server_name, server in self.registry.servers.items():
            capabilities = getattr(server, "capabilities", [])
            if not capabilities:
                print(f">>> {server_name}: no capabilities found, skipping skill generation")
                continue

            for cap in capabilities:
                tools = self._tools_for_capability(server_name, cap)
                skill_name = f"{server_name.replace('_server', '')}-{cap.name}"
                content = self._render_skill(
                    name=skill_name,
                    description=cap.description,
                    tools=tools,
                    rules=cap.rules,
                    server_name=server_name,
                )
                path = self._save_skill(skill_name, content, base_dir)
                print(f">>> Generated skill: {path} ({len(tools)} tools)")
                paths.append(path)

        return paths


if __name__ == "__main__":


    async def run():
        registry = MegamodelRegistry()
        await populate_registry(registry)
        base_dir = str(Path(__file__).resolve().parent)
        paths = MegamodelToSkill(registry).generate_all_skills(base_dir=base_dir)
        print(f"\nDone. {len(paths)} skill(s) written.")

    asyncio.run(run())

