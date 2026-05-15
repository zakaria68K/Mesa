import asyncio
import json
import sys
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
sys.path.insert(0, '.opencode/skills')
from megamodel_toskill import MegamodelToSkill
from megamodel.megamodel import MegamodelRegistry
from megamodel.megamodel_instance import populate_registry
from modeling_agents.meta_agent import MetaAgent


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

    dataset = load_specialization_dataset(
        "/Users/zakariahachm/Documents/Phd_Zakaria/MESA/datasets/emf_testing_dataset_50.json"
    )
    print(f"Loaded {len(dataset)} samples from EMF dataset.")

    # Skills generation
    print("\n> Populating registry and generating skill files...")
    registry = MegamodelRegistry()
    await populate_registry(registry)
    base_dir = str(Path(".opencode/skills").resolve())
    generated = MegamodelToSkill(registry).generate_all_skills(base_dir=base_dir)
    print(f"> {len(generated)} skill(s) written: {[p.parent.name for p in generated]}")

    meta = MetaAgent(
        metamodel_file="/Users/zakariahachm/Documents/Phd_Zakaria/Paper_Artifacts_SAM_2025/atl_zoo-master/EMF2KM3/Ecore.ecore"
    )
    specialization_log_file = "debug_logs/specialization_iterations_emf.txt"

    print("\n>>> Starting EMF specialization loop...")
    apply_skill, get_skill = meta.specialize_agent(
        dataset,
        threshold=0.85,
        log_file=specialization_log_file,
    )

    print("\n>>> Specialization complete.")
    print(f"  Write skill : {apply_skill}")
    print(f"  Read skill  : {get_skill}")
    print(f"  Log         : {specialization_log_file}")
    
if __name__ == "__main__":
    asyncio.run(main())