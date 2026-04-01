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

    meta = MetaAgent(file="Agents.md")
    actual_calls = []

    for i, sample in enumerate(dataset):
        print(f"\n[Sample {i+1}/{len(dataset)}] Pattern: {sample.get('pattern')} | Level: {sample.get('level', 'N/A')}")
        print(f"Instruction: {sample['instruction']}")
        print("-" * 40)

        print(">>> Starting Gemini CLI subprocess...")
        try:
            output, actual_calls = meta.agent.run(sample["instruction"], meta.file)
            print(f">>> Gemini finished. Tool calls captured: {actual_calls}")
        except RuntimeError as e:
            print(f" Gemini CLI raised an error:\n{e}")
        except Exception as e:
            print(f">>> Unexpected error: {type(e).__name__}: {e}")

        score = meta.evaluate(actual_calls, sample["relevant_apis"])

        print(f"\n  Score: {score:.2f}")
        print(f"   Expected : {[e['api_name'] for e in sample['relevant_apis']]}")
        print(f"   Got      : {[c['api_name'] for c in actual_calls]}")
if __name__ == "__main__":
    asyncio.run(main())