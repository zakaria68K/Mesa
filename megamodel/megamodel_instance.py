
import os, json, subprocess
from .server_config.server_integrator import MCPServerIntegrator
from .server_config.server_infra import MCPServer, MCPCapability
from .am3 import ReferenceModel
from .mcp_client import MCPClient


from megamodel.am3 import TransformationModel

async def populate_registry(registry):
    integrator = MCPServerIntegrator(registry)
    

    # Get server script paths
    atl_server_script = os.path.join(os.path.dirname(__file__), '..', 'mcp_servers', 'atl_server', 'atl_mcp_server.py')
    emf_server_script = os.path.join(os.path.dirname(__file__), '..', 'mcp_servers', 'emf_server', 'stateless_emf_server.py')
    openrewrite_server_script = os.path.join(os.path.dirname(__file__), '..', 'mcp_servers', 'openRewrite_servers', 'openrewrite_server.py')

    # Setup servers with script paths in metadata
    atl_server = integrator.setup_atl_server()
    emf_server = integrator.setup_emf_server()

    openrewrite_server = MCPServer(
        host="localhost",
        port=8089,
        name="openrewrite_server",
        tools_port=8083
    )
    openrewrite_server.add_capability(MCPCapability(
        input_types=["java", "xml", "yml", "properties"],
        output_types=["java", "xml", "yml", "properties"],
        can_execute=True,
        description="OpenRewrite code transformations"
    ))
    integrator.registry.register_mcp_server("openrewrite_server", openrewrite_server)
    openrewrite_server.metadata["script_path"] = openrewrite_server_script
    atl_server.metadata["script_path"] = atl_server_script
    emf_server.metadata["script_path"] = emf_server_script

    # Get ATL tools
    atl_client = MCPClient()
    tools = []
    try:
        await atl_client.connect_to_server(atl_server_script)
        session = await atl_client.get_session()
        response = await session.list_tools()
        tools = response.tools
    finally:
        await atl_client.cleanup()
    atl_tools = tools

    # Discover EMF tools using MCP protocol
    emf_client = MCPClient()
    tools = []
    try:
        await emf_client.connect_to_server(emf_server_script)
        session = await emf_client.get_session()
        response = await session.list_tools()
        tools = response.tools
    finally:
        await emf_client.cleanup()
    emf_tools = tools

    # Discover OpenRewrite tools using MCP protocol
    openrewrite_client = MCPClient()
    tools = []
    try:
        await openrewrite_client.connect_to_server(openrewrite_server_script)
        session = await openrewrite_client.get_session()
        response = await session.list_tools()
        tools = response.tools
    finally:
        await openrewrite_client.cleanup()
    openrewrite_tools = tools

    # Register tools with the megamodel registry
    registry.tools_by_server["atl_server"] = atl_tools
    registry.tools_by_server["emf_server"] = emf_tools
    registry.tools_by_server["openrewrite_server"] = openrewrite_tools

    # Call ATL server to get enabled transformations
    enabled_transformations = fetch_transformations()

    # Register transformation tools for ATL server
    def get_or_register_metamodel(uri, name):
        mm = registry.get_entity(uri)
        if not mm:
            mm = ReferenceModel(uri=uri, name=name)
            registry.register_entity(mm)
        return mm

    # Fetch samples once from ATL server
    try:
        samples_raw = subprocess.run([
            'curl', '-s', '-X', 'GET', 'http://localhost:8080/transformations/samples'
        ], capture_output=True, text=True, check=True)
        samples_data = json.loads(samples_raw.stdout)
        # Map name -> sampleSources
        samples_by_name = {entry.get('name'): entry.get('sampleSources', []) for entry in (samples_data or [])}
    except Exception:
        samples_by_name = {}
    for transfo_data in enabled_transformations:
        transfo_name = transfo_data.get('name')
        # Input metamodels
        input_mms = transfo_data.get('input_metamodels', [])
        source_ref = None
        if input_mms:
            mm = input_mms[0]
            source_ref = get_or_register_metamodel(mm.get('path'), mm.get('name', mm.get('path')))
        # Output metamodels
        output_mms = transfo_data.get('output_metamodels', [])
        target_ref = None
        if output_mms:
            mm = output_mms[0]
            target_ref = get_or_register_metamodel(mm.get('path'), mm.get('name', mm.get('path')))
        # Register transformation with references
        transfo_entity = TransformationModel(
            uri=transfo_data.get('atlFile', transfo_data.get('name', 'unknown')),
            name=transfo_data.get('name', 'unknown'),
            source_metamodel=source_ref,
            target_metamodel=target_ref,
            sample_sources=samples_by_name.get(transfo_name, [])
        )
        registry.register_entity(transfo_entity)