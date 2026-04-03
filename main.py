import asyncio
import json
from dotenv import load_dotenv
load_dotenv()

from megamodel.megamodel import MegamodelRegistry
from megamodel.megamodel_instance import populate_registry
from modeling_agents.meta_agent import MetaAgent


async def main():
    print("MESA Megamodel Instance Initialization")

    registry = MegamodelRegistry()
    await populate_registry(registry)
    print("MESA Megamodel Instance is ready with the following servers:")
    for server_name in registry.mcp_servers.keys():
        print(f" - {server_name}")

    with open("/Users/zakariahachm/Documents/Phd_Zakaria/MESA/datasets/testing_datatset.json", "r") as f:
        dataset = json.load(f)
    print(f"\nLoaded {len(dataset)} samples from dataset.")

    meta = MetaAgent()

    print("\n>>> Starting specialization loop...")
    apply_skill, get_skill = meta.specialize_agent(dataset, threshold=0.5)

    print("\n>>> Specialization complete. Final skill files:")
    print(f"  Apply skill : {apply_skill}")
    print(f"  Get skill   : {get_skill}")
    print("\n>>> Apply skill content:")
    print(open(apply_skill).read())
    print("\n>>> Get skill content:")
    print(open(get_skill).read())


if __name__ == "__main__":
    asyncio.run(main())