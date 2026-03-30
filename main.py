import asyncio
from dotenv import load_dotenv
load_dotenv() 
from megamodel.megamodel import MegamodelRegistry
from megamodel.megamodel_instance import populate_registry


from modeling_agents.generic_agent import GenericModelingAgent

async def main():
    load_dotenv()  # Load environment variables from .env
    print("MESA Megamodel Instance Initialization")
    # Create registry and populate it
    registry = MegamodelRegistry()
    await populate_registry(registry)
    print("MESA Megamodel Instance is ready with the following servers:")
    for server_name in registry.mcp_servers.keys():
        print(f" - {server_name}")
    
    # Instantiate the agent: 
    agent = GenericModelingAgent(mcp_server_script="mcp_servers/atl/atl_server.py")
    agent_result = await agent.run(task = "Transform this Class model /Users/zakariahachm/Documents/Phd_Zakaria/Scripts/atl-server/sample sources/Class.xmi to A relational model using the ATL transformation available in the ATL server.")

    print("\nAgent Result:\n", agent_result)

if __name__ == "__main__":
    asyncio.run(main())