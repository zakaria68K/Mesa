import os
import json
import subprocess
from .server_config.server_integrator import MCPServerIntegrator
from .am3 import ReferenceModel, TransformationModel, Server, Status, Capability
from .server_config.client import MCPClient
from mcp_servers.atl.atl_server import fetch_transformations


async def populate_registry(registry, servers: list[str] | None = None):
    """
    Populate the registry with MCP servers and their tools.

    Args:
        registry: the MegamodelRegistry instance
        servers:  list of server names to register, e.g. ["emf"] or ["atl", "emf"].
                  Defaults to None which registers all servers.
    """
    integrator = MCPServerIntegrator(registry)
    _all = servers is None

    # ── ATL server ────────────────────────────────────────────
    if _all or "atl" in servers:
        atl_server_script = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "mcp_servers", "atl", "atl_server.py")
        )

        atl_server_raw = integrator.setup_atl_server()
        atl_server_raw.metadata["script_path"] = atl_server_script

        atl_server_obj = Server(
            name="atl_server",
            port=8080,
            status=Status.CONNECTED,
            script_path=atl_server_script,
        )
        registry.register_server(atl_server_obj)

        atl_client = MCPClient()
        tools = []
        try:
            await atl_client.connect_to_server(atl_server_script)
            session = await atl_client.get_session()
            response = await session.list_tools()
            tools = response.tools
        finally:
            await atl_client.cleanup()

        registry.register_tools_for_server("atl_server", tools)

        capabilities = registry.derive_server_capabilities("atl_server")
        for cap in capabilities:
            if cap.name == "list":
                cap.name = "get"
        atl_server_obj.capabilities = capabilities

        # Fetch enabled transformations (ATL-only)
        enabled_transformations = fetch_transformations()

        def get_or_register_metamodel(uri, name):
            mm = registry.get_entity(uri)
            if not mm:
                mm = ReferenceModel(uri=uri, name=name)
                registry.register_entity(mm)
            return mm

        try:
            samples_raw = subprocess.run(
                ['curl', '-s', '-X', 'GET', 'http://localhost:8080/transformations/samples'],
                capture_output=True, text=True, check=True
            )
            samples_data = json.loads(samples_raw.stdout)
            samples_by_name = {
                entry.get('name'): entry.get('sampleSources', [])
                for entry in (samples_data or [])
            }
        except Exception:
            samples_by_name = {}

        for transfo_data in enabled_transformations:
            transfo_name = transfo_data.get('name')

            source_ref = None
            input_mms = transfo_data.get('input_metamodels', [])
            if input_mms:
                mm = input_mms[0]
                source_ref = get_or_register_metamodel(mm.get('path'), mm.get('name', mm.get('path')))

            target_ref = None
            output_mms = transfo_data.get('output_metamodels', [])
            if output_mms:
                mm = output_mms[0]
                target_ref = get_or_register_metamodel(mm.get('path'), mm.get('name', mm.get('path')))

            transfo_entity = TransformationModel(
                uri=transfo_data.get('atlFile', transfo_data.get('name', 'unknown')),
                name=transfo_data.get('name', 'unknown'),
                source_metamodel=source_ref,
                target_metamodel=target_ref,
                sample_sources=samples_by_name.get(transfo_name, [])
            )
            registry.register_entity(transfo_entity)

    # ── EMF server ────────────────────────────────────────────
    if _all or "emf" in servers:
        emf_server_script = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "mcp_servers", "emf", "emf_server.py")
        )
        emf_server_raw = integrator.setup_emf_server()
        emf_server_raw.metadata["script_path"] = emf_server_script

        emf_server_obj = Server(
            name="emf_server",
            port=8096,
            status=Status.CONNECTED,
            script_path=emf_server_script,
        )
        registry.register_server(emf_server_obj)

        emf_client = MCPClient()
        emf_tools = []
        try:
            await emf_client.connect_to_server(emf_server_script)
            emf_session = await emf_client.get_session()
            emf_response = await emf_session.list_tools()
            emf_tools = emf_response.tools
        finally:
            await emf_client.cleanup()

        registry.register_tools_for_server("emf_server", emf_tools)

        _emf_rules = [
            "You MUST use ONLY the MCP tools provided by the `emf_server`.",
            "You MUST NOT attempt to run Python scripts directly.",
            "Do NOT use bash, glob, or file-search tools.",
        ]
        emf_server_obj.capabilities = [
            Capability(
                name="write",
                description="Write operations via emf_server",
                tool_keywords=["start", "create", "update", "clear", "delete"],
                rules=_emf_rules,
            ),
            Capability(
                name="read",
                description="Read operations via emf_server",
                tool_keywords=["inspect", "list", "get"],
                rules=_emf_rules,
            ),
        ]