# MESA: Model-based Engineering Specialization Architecture

MESA is a closed-loop framework that specializes LLM-based agents for Model-Based Engineering (MBE) tools exposed through MCP servers, without manual prompt authoring.

Instead of hand-writing tool-usage instructions, MESA discovers the tools registered on an MCP server, generates an initial skill file directly from the tool registry, runs an agent against a generated evaluation dataset, and uses the resulting execution traces to rewrite the skill file. This loop repeats until a target accuracy is reached or a fixed iteration budget is exhausted.

This repository contains the artifact accompanying the paper "Towards the LLM-based Continuous Engineering of Modeling Agents: An Approach and Research Roadmap", submitted to the MODELS 2026 NIER track.

## How It Works

1. Initialize the MBE Repository: discover and register the available MCP servers and their tools.
2. Generate an evaluation dataset of natural language instructions paired with ground-truth tool-call sequences.
3. Generate an initial SKILL.md from the tool registry (server names, tool names, tool descriptions).
4. Bind a generic agent to the registered MCP servers and run it on the dataset under the current skill file.
5. Score the resulting tool calls against the ground truth and collect execution traces.
6. If the accuracy threshold is not met, group failing samples by mismatch pattern and pass representative failures to a separate refiner LLM, which rewrites the SKILL.md.
7. Repeat from step 4 until the threshold is reached or the iteration budget is exhausted.

## Repository Contents

- `megamodel/`: MCP server discovery and tool registration logic.
- `datasets/`:Datasets generation process resulting instruction-to-tool-call evaluation datasets for the ATL and EMF MCP servers.
- `megamodel_toskill/`: initial SKILL.md generation from the tool registry (GET and APPLY patterns).
- `modeling_agents/generic_agent.py/`: agent execution harness binding the OpenCode Agent to the registered MCP servers.
- `modeling_agents/meta_agent.py/`: failure pattern grouping and skill rewriting (MetaAgent) logic.
- `datasets/testing_datatset.json/`: the n=50 evaluation datasets used for the ATL and EMF experiments.
- `debug_logs/opencode_logs/`: specialization logs and per-iteration evaluation results for both runs reported in the paper.
- `.opencode/skills/`: generated SKILL.md for both tools.

## Reproducing the Experiments

The experiments bind the agent to a locally hosted model and require no external API calls, so no modeling artifacts or execution traces leave the local environment. See the configuration files in each subdirectory for the model and MCP server setup used to produce the results.
