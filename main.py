import asyncio

from megamodel.megamodel import MegamodelRegistry
from megamodel.megamodel_instance import populate_registry
from dotenv import load_dotenv

async def main():
    load_dotenv()  # Load environment variables from .env
    print("MESA Megamodel Instance Initialization")
    # Create registry and populate it
    registry = MegamodelRegistry()
    await populate_registry(registry)
    print("MESA Megamodel Instance is ready with the following servers:")
    for server_name in registry.mcp_servers.keys():
        print(f" - {server_name}")
if __name__ == "__main__":
    asyncio.run(main())