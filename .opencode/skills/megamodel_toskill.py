from pathlib import Path
from typing import List, Dict
import re

class MegamodelToSkill:
    """Query megamodel and generate skill files"""

    def __init__(self, registry=None):
        self.registry = registry

    def to_camel_case(self, s: str) -> str:
        parts = re.split(r'[-_]', s)
        return parts[0].lower() + "".join(x.title() for x in parts[1:])

    def render_skill(self, name: str, description: str, tools: List[Dict[str, str]], rules: List[str] = None, metadata: Dict = None) -> str:
        """Render skill markdown with YAML frontmatter and dynamic metadata"""
        lines = [
            "---",
            f"name: {name}",
            f"description: {description}",
        ]
        if metadata and "tools" in metadata:
            lines.append(f"tools: {', '.join(metadata['tools'])}")
        lines.extend(["---", "", "You are a Model-Driven Engineering agent with access to an ATL MCP server.", ""])
        
        if rules:
            lines.append("## CRITICAL RULES")
            for rule in rules:
                lines.append(f"- {rule}")
            lines.append("")
        
        lines.append("## Available MCP Tools")
        for tool in tools:
            if isinstance(tool, dict):
                lines.append(f"- `{tool['name']}` — {tool['description']}")
            else:
                lines.append(f"- `{tool}`")
        
        return "\n".join(lines)

    def save_skill(self, name: str, content: str, base_dir: str = ".opencode/skills") -> Path:
        """Save skill file to disk"""
        output_dir = Path(base_dir) / name
        output_dir.mkdir(parents=True, exist_ok=True)
        skill_path = output_dir / "SKILL.md"
        skill_path.write_text(content)
        return skill_path

    def generate_get_pattern(self) -> Path:
        """Generate GET skill from megamodel registry"""
        tools = []
        description = "List and retrieve available ATL transformation samples and inputs"
        server_name = "atl_server"
        list_tools = []
        
        if self.registry:
            servers = list(self.registry.servers.keys())
            if servers:
                server_name = servers[0]
            
            all_tools = self.registry.discover_tools()
            list_tools = [t for t in all_tools if hasattr(t, 'name') and 'list' in t.name.lower()]
            print(f">>> Discovered tools for GET pattern: {[t.name for t in list_tools]}")

            for tool in list_tools[:2]:
                #print  descriptions if available, otherwise just names
                desc ={'name': tool.name, 'description': getattr(tool, 'description', 'No description')}
                tools.append(desc)

        content = self.render_skill(
            "mde-get",
            description,
            tools,
            [f"You MUST use ONLY the MCP tools provided by the `{server_name}`.", 
             "You MUST NOT attempt to run Python scripts directly."],
            {"tools": [t.name for t in list_tools]}
        )
        return self.save_skill("mde-get", content)

    def generate_apply_pattern(self) -> Path:
        """Generate APPLY skill from megamodel registry"""
        tools = []
        description = "Apply an ATL transformation to a source model"
        server_name = "atl_server"
        apply_tools = []
        
        if self.registry:
            servers = list(self.registry.servers.keys())
            if servers:
                server_name = servers[0]
            
            all_tools = self.registry.discover_tools()
            apply_tools = [t for t in all_tools if hasattr(t, 'name') and 'apply' in t.name.lower()]
            print(f">>> Discovered tools for APPLY pattern: {[t.name for t in apply_tools]}")
                 
            for tool in apply_tools[:2]:
                desc ={'name': tool.name, 'description': getattr(tool, 'description', 'No description')}
                tools.append(desc)
            

        content = self.render_skill(
            "mde-apply",
            description,
            tools,
            [f"You MUST use ONLY the MCP tools provided by the `{server_name}` to perform transformations.",
             "The ONLY way to apply transformations is through the MCP tools available to you."],
            {"tools": [t.name for t in apply_tools]}
        )
        return self.save_skill("mde-apply", content)

    def sync_tools(self, base_dir: str = ".opencode/skills") -> None:
        """Reflect tools added/removed in the registry into the (possibly refined) skills, keeping their rules"""
        if not self.registry:
            return
        current = {t.name: getattr(t, 'description', 'No description') for t in self.registry.discover_tools() if hasattr(t, 'name')}
        for name, keyword in (("mde-get", "list"), ("mde-apply", "apply")):
            path = Path(base_dir) / name / "SKILL.md"
            text = path.read_text()
            match = re.search(r'^tools:(.*)$', text, flags=re.MULTILINE)
            if not match:  # skill generated before sync existed, nothing to diff against
                continue
            known = {n.strip() for n in match.group(1).split(',') if n.strip()}
            tools = [n for n in current if keyword in n.lower()]
            added = [n for n in tools if n not in known]
            removed = known - set(tools)
            if not added and not removed:
                continue
            print(f">>> Syncing {name}: added={added} removed={sorted(removed)}")

            lines = [l for l in text.splitlines() if not any(f"`{r}`" in l for r in removed)]
            new_lines = [f"- `{n}` — {current[n]}" for n in added]
            header = next((i for i, l in enumerate(lines) if l.strip() == "## Available MCP Tools"), None)
            if header is None:
                lines += ["", "## Available MCP Tools", *new_lines]
            else:
                lines[header + 1:header + 1] = new_lines
            text = "\n".join(lines)
            text = re.sub(r'^tools:.*$', f"tools: {', '.join(tools)}", text, count=1, flags=re.MULTILINE)
            path.write_text(text)

    def generate_patterns(self, base_dir: str = ".opencode/skills") -> List[Path]:
        """Generate GET and APPLY pattern skill templates from megamodel"""
        paths = []
        
        metadata = {}
        if self.registry:
            from megamodel.am3 import TransformationModel
            transformations = self.registry.find_entities_by_type(TransformationModel)
            servers = list(self.registry.servers.keys())
            metadata = {
                "transformations": [t.name for t in transformations],
                "servers": servers
            }
        
        # Generate patterns with metadata
        paths.append(self.generate_get_pattern())
        paths.append(self.generate_apply_pattern())
        return paths
