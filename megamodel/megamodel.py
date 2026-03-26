from typing import Dict, List, Optional, Any
from .execution import AgentSession 
from .am3 import Entity, Relationship, Model, Server, Tool, Agent
from .planning import Workflow


class MegamodelRegistry:
    """Central registry for the extended AM3 megamodel"""

    def __init__(self):
        # ── Artifacts ──
        self.entities: Dict[str, Entity] = {}
        self.relationships: List[Relationship] = []
        self._models_by_type: Dict[str, List[Model]] = {
            "reference": [],
            "transformation": [],
            "terminal": []
        }

        # ── Tools ──
        self.servers: Dict[str, Server] = {}
        self.tools_by_server: Dict[str, List[Tool]] = {}

        # ── Agents ──
        self.agents: Dict[str, Agent] = {}

        # ── Workflows ──
        self.workflows: Dict[str, Workflow] = {}

        # ── Sessions / Traces ──
        self.sessions: Dict[str, AgentSession] = {}

        # backwards compat
        self.mcp_servers = self.servers
        self.workflow_plans = self.workflows

    # ── Entities ───────────────────────────────────────────

    def register_entity(self, entity: Entity) -> str:
        self.entities[entity.uri] = entity
        if isinstance(entity, Model):
            model_type = entity.model_type.value
            if model_type in self._models_by_type:
                self._models_by_type[model_type].append(entity)
        return entity.uri

    def get_entity(self, uri: str) -> Optional[Entity]:
        return self.entities.get(uri)

    def find_entities_by_type(self, entity_type: type) -> List[Entity]:
        return [e for e in self.entities.values() if isinstance(e, entity_type)]

    def register_relationship(self, relationship: Relationship) -> None:
        self.relationships.append(relationship)

    def find_relationships(self, source_uri: str = None, target_uri: str = None,
                           relationship_type: str = None) -> List[Relationship]:
        return [
            rel for rel in self.relationships
            if (source_uri is None or rel.source.uri == source_uri)
            and (target_uri is None or rel.target.uri == target_uri)
            and (relationship_type is None or rel.relationship_type == relationship_type)
        ]

    # ── Servers & Tools ────────────────────────────────────

    def register_server(self, server: Server) -> None:
        self.servers[server.name] = server

    def register_mcp_server(self, name: str, server: Any) -> None:
        """Backwards compat"""
        if not hasattr(server, 'metadata'):
            server.metadata = {}
        self.servers[name] = server
        self.tools_by_server[name] = getattr(server, 'tools', [])

    def register_mcp_server_with_script(self, name: str, server: Any, script_path: str) -> None:
        if not hasattr(server, 'metadata'):
            server.metadata = {}
        server.metadata['script_path'] = script_path
        self.register_mcp_server(name, server)

    def register_tools_for_server(self, server_name: str, tools: List[Tool]) -> None:
        self.tools_by_server[server_name] = tools

    def get_mcp_server(self, name: str) -> Optional[Any]:
        return self.servers.get(name)

    def discover_tools(self, server_name: str = None) -> List[Tool]:
        if server_name:
            return self.tools_by_server.get(server_name, [])
        return [tool for tools in self.tools_by_server.values() for tool in tools]

    def find_tools_by_capability(self, input_type: str = None,
                                  output_type: str = None) -> List[Tool]:
        matching = []
        for server_name, server in self.servers.items():
            for cap in getattr(server, 'capabilities', []):
                if (input_type is None or input_type in getattr(cap, 'input_types', [])) and \
                   (output_type is None or output_type in getattr(cap, 'output_types', [])):
                    matching.extend(self.tools_by_server.get(server_name, []))
        return matching

    # ── Agents ─────────────────────────────────────────────

    def register_agent(self, agent_id: str, agent: Agent) -> None:
        self.agents[agent_id] = agent

    def get_agent(self, agent_id: str) -> Optional[Agent]:
        return self.agents.get(agent_id)

    # ── Workflows ──────────────────────────────────────────

    def create_workflow(self, goal: Any, instruction: str = "") -> Workflow:
        workflow = Workflow(goal=goal, instruction=instruction)
        self.workflows[workflow.plan_id] = workflow
        return workflow

    def create_workflow_plan(self, goal: Any) -> Workflow:
        """Backwards compat"""
        return self.create_workflow(goal)

    def get_workflow(self, plan_id: str) -> Optional[Workflow]:
        return self.workflows.get(plan_id)

    def get_workflow_plan(self, plan_id: str) -> Optional[Workflow]:
        return self.get_workflow(plan_id)

    # ── Sessions ───────────────────────────────────────────

    def create_session(self, context: Dict[str, Any] = None) -> AgentSession:
        session = AgentSession(context=context or {})
        self.sessions[session.session_id] = session
        return session

    def get_session(self, session_id: str) -> Optional[AgentSession]:
        return self.sessions.get(session_id)

    # ── Queries ────────────────────────────────────────────

    def query_models(self, metamodel_uri: str = None,
                     model_type: str = None) -> List[Model]:
        candidates = (
            self._models_by_type[model_type]
            if model_type and model_type in self._models_by_type
            else self.find_entities_by_type(Model)
        )
        return [
            m for m in candidates
            if metamodel_uri is None or (
                hasattr(m, 'conformsTo') and m.conformsTo and
                m.conformsTo.uri == metamodel_uri
            )
        ]

    def get_execution_statistics(self) -> Dict[str, Any]:
        total_invocations = 0
        successful_invocations = 0
        for session in self.sessions.values():
            for trace in session.execution_traces:
                for step in trace.trace_steps:
                    total_invocations += len(step.invocations)
                    successful_invocations += sum(1 for inv in step.invocations if not inv.is_error)
        return {
            "total_sessions": len(self.sessions),
            "total_workflows": len(self.workflows),
            "total_invocations": total_invocations,
            "successful_invocations": successful_invocations,
            "success_rate": (successful_invocations / total_invocations * 100) if total_invocations > 0 else 0,
            "registered_entities": len(self.entities),
            "registered_relationships": len(self.relationships),
            "active_servers": len(self.servers)
        }