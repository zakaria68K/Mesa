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
             "You MUST NOT attempt to run Python scripts directly."]
        )
        return self.save_skill("mde-get", content)

    def generate_apply_pattern(self) -> Path:
        """Generate APPLY skill from megamodel registry"""
        tools = []
        description = "Apply an ATL transformation to a source model"
        server_name = "atl_server"
        
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
             "The ONLY way to apply transformations is through the MCP tools available to you."]
        )
        return self.save_skill("mde-apply", content)

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
