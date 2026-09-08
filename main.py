import asyncio
import json
from random import random
from dotenv import load_dotenv
load_dotenv()
from megamodel.megamodel import MegamodelRegistry
from megamodel.megamodel_instance import populate_registry
from modeling_agents.meta_agent import MetaAgent
import sys
import random 
sys.path.insert(0, '.opencode/skills')
from megamodel_toskill import MegamodelToSkill


def load_specialization_dataset(dataset_path: str) -> list[dict]:
    with open(dataset_path, "r") as f:
        raw_dataset = json.load(f)

    if isinstance(raw_dataset, dict):
        dataset_sections = raw_dataset.values()
    elif isinstance(raw_dataset, list):
        dataset_sections = [raw_dataset]
    else:
        raise TypeError(f"Unsupported dataset format: {type(raw_dataset).__name__}")

    samples: list[dict] = []
    for section in dataset_sections:
        if not isinstance(section, list):
            continue
        for sample in section:
            if not isinstance(sample, dict):
                continue
            if "instruction" not in sample or "relevant_apis" not in sample:
                continue
            samples.append(sample)

    return samples

async def main():

    print("MESA Megamodel Instance Initialization")

    registry = MegamodelRegistry()
    await populate_registry(registry)
    print("MESA Megamodel Instance is ready with the following servers:")
    for server_name in registry.mcp_servers.keys():
        print(f" - {server_name}")

    dataset = load_specialization_dataset(
        "/Users/anonymoushachm/Documents/Phd_anonymous/MESA/datasets/testing_datatset.json"
    )
    print(f"\nLoaded {len(dataset)} valid samples from dataset.")

    random.seed(42)
    random.shuffle(dataset)

    train_dataset = dataset[:50]   # seen by the specialization loop
    test_dataset  = dataset[50:75] # never shown to the meta-agent

    # generate skill files from megamodel registry
    print("\n> Generating skill files from megamodel...")
    skill_generator = MegamodelToSkill(registry)
    skill_generator.generate_patterns()

    meta = MetaAgent()
    specialization_log_file = "debug_logs/specialization_iterations_run2.txt"

    print("\n>>> Starting specialization loop...")
    apply_skill, get_skill = meta.specialize_agent(
        train_dataset,
        threshold=1.0,
        log_file=specialization_log_file,
    )
    test_score = meta.evaluate_on_test_set(test_dataset, specialization_log_file)
    
    print("\n>>> Specialization complete. Final skill files:")
    print(f"  Apply skill : {apply_skill}")
    print(f"  Get skill   : {get_skill}")
    print(f"  Iteration log: {specialization_log_file}")
    print("\n>>> Apply skill content:")
    print(open(apply_skill).read())
    print("\n>>> Get skill content:")
    print(open(get_skill).read())
    
if __name__ == "__main__":
    asyncio.run(main())