"""
Run the generic agent (plugged with the ATL MCP server, no skill) on the all_tools seeds,
single and multi tool, and report the tool-call accuracy with MetaAgent.evaluate.
Results are written to outputs/main2/<run_id>_results.json after each sample.

Usage: python main2.py [single|multi|all]   (default: all)
"""
import datetime
import json
import shutil
import sys
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
from modeling_agents.generic_agent import GenericModelingAgent
from modeling_agents.meta_agent import MetaAgent, PROJECT_ROOT

sys.path.insert(0, "datasets/ATL/model_transformation_seeds/all_tools")
from single_tool_seeds import SingleToolSeeds
from multi_tool_seeds import MultiToolSeeds

RUN_ID      = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
RESULTS_FILE = Path(f"outputs/main2/{RUN_ID}_results.json")
LOGS_DIR     = Path(f"outputs/main2/{RUN_ID}_logs")  # opencode log of each sample


def summary(scores: list[float]) -> dict:
    return {
        "accuracy": sum(scores) / len(scores) if scores else 0.0,
        "fully_correct": sum(1 for s in scores if s == 1.0),
        "total": len(scores),
    }


def save(results: dict) -> None:
    for data in results["sets"].values():
        data["summary"] = summary([s["score"] for s in data["samples"]])
    RESULTS_FILE.write_text(json.dumps(results, indent=2, ensure_ascii=False))


def run(agent: GenericModelingAgent, evaluator: MetaAgent, name: str, seeds: list, results: dict) -> None:
    samples = results["sets"].setdefault(name, {"samples": []})["samples"]
    for i, seed in enumerate(seeds):
        error, answer = None, ""
        try:
            answer, actual_calls = agent.run(seed.instruction, file=None)
        except Exception as e:
            error = str(e)
            print(f"    agent error: {e}")
            actual_calls = []
        shutil.copy("opencode_logs/opencode_logs.txt", LOGS_DIR / f"{name}_{i+1}.txt")
        score = evaluator.evaluate(actual_calls, seed.relevant_apis)
        samples.append({
            "instruction": seed.instruction,
            "level": seed.level,
            "pattern": seed.pattern,
            "expected": seed.relevant_apis,
            "actual": actual_calls,
            "answer": answer,
            "score": score,
            "error": error,
        })
        save(results)
        pct = round((i + 1) / len(seeds) * 100)
        print(f"  [{name} {i+1}/{len(seeds)} — {pct}%] score={score:.2f}")
        print(f"    Expected : {[e['api_name'] for e in seed.relevant_apis]}")
        print(f"    Actual   : {[a['api_name'] for a in actual_calls]}")


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    agent = GenericModelingAgent(mcp_server_script="mcp_servers/atl/atl_server.py", project_root=PROJECT_ROOT)
    evaluator = MetaAgent()  # only used for its evaluate()

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    results = {"run_id": RUN_ID, "sets": {}}
    if which in ("single", "all"):
        run(agent, evaluator, "single", SingleToolSeeds.get_seeds(), results)
    if which in ("multi", "all"):
        run(agent, evaluator, "multi", MultiToolSeeds.get_seeds(), results)

    all_scores = [s["score"] for d in results["sets"].values() for s in d["samples"]]
    results["overall"] = summary(all_scores)
    save(results)

    print("\n" + "=" * 60)
    for name, data in [*results["sets"].items(), ("overall", {"summary": results["overall"]})]:
        s = data["summary"]
        print(f"{name:<8} accuracy={s['accuracy']:.2%} | fully correct={s['fully_correct']}/{s['total']}")
    print(f"Results saved to {RESULTS_FILE}")


if __name__ == "__main__":
    main()
