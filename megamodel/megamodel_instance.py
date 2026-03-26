import os, sys
import json
import subprocess
from .server_config.server_integrator import MCPServerIntegrator
from .am3 import ReferenceModel
from .server_config.client import MCPClient
from mcp_servers.atl.atl_server import fetch_transformations


from megamodel.am3 import TransformationModel

async def populate_registry(registry):
    integrator = MCPServerIntegrator(registry)
    # Get server script paths
    atl_server_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "mcp_servers", "atl", "atl_server.py"))
    #emf_server_script = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."), 'mcp_servers', 'emf_server', 'emf','stateless_emf_server.py')

    # Setup servers with script paths in metadata
    atl_server = integrator.setup_atl_server()
    atl_server.metadata["script_path"] = atl_server_script

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

    # Register tools with the megamodel registry
    registry.tools_by_server["atl_server"] = atl_tools
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