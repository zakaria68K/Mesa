import asyncio
import json
from dotenv import load_dotenv
load_dotenv()

from megamodel.megamodel import MegamodelRegistry
from megamodel.megamodel_instance import populate_registry
from modeling_agents.generic_agent import GenericModelingAgent


async def main():
    print("MESA Megamodel Instance Initialization")

    registry = MegamodelRegistry()
    await populate_registry(registry)
    print("MESA Megamodel Instance is ready with the following servers:")
    for server_name in registry.mcp_servers.keys():
        print(f" - {server_name}")

    # Load dataset from JSON file
    with open("/Users/zakariahachm/Documents/Phd_Zakaria/MESA/datasets/testing_datatset.json", "r") as f:
        dataset = json.load(f)
    print(f"\nLoaded {len(dataset)} samples from dataset.")

    agent = GenericModelingAgent(mcp_server_script="mcp_servers/atl/atl_server.py")

    print("\n" + "="*60)
    print("Running evaluation over dataset...")
    print("="*60)

    for i, sample in enumerate(dataset):
        print(f"\n[Sample {i+1}/{len(dataset)}] Pattern: {sample.get('pattern')} | Level: {sample.get('level', 'N/A')}")
        print(f"Instruction: {sample['instruction']}")
        print("-" * 40)

        output, actual_calls = await agent.run(sample["instruction"])
        score = agent.evaluate(actual_calls, sample["relevant_apis"])

        print(f"\n Score: {score:.2f}")
        print(f"   Expected : {[e['api_name'] for e in sample['relevant_apis']]}")
        print(f"   Got      : {[c['api_name'] for c in actual_calls]}")



if __name__ == "__main__":
    asyncio.run(main())