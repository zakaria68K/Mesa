import asyncio

from megamodel.megamodel import MegamodelRegistry
from megamodel.megamodel_instance import populate_registry


async def main():
    print("MESA Megamodel Instance Initialization")
    # Create registry and populate it
    registry = MegamodelRegistry()
    await populate_registry(registry)
    print("MESA Megamodel Instance is ready with the following servers:")
    for server_name in registry.mcp_servers.keys():
        print(f" - {server_name}")
    # print all the megamodel entities and their values
    print("\nRegistered Entities:")
    for uri, entity in registry.entities.items():
        print(f"URI: {uri}, Name: {getattr(entity, 'name', 'N/A')}, Type: {type(entity).__name__}")

if __name__ == "__main__":
    asyncio.run(main())