import json

from openai import OpenAI

from openai import OpenAI
from modeling_agents.generic_agent import GenericModelingAgent


class MetaAgent:
    
    def __init__(self, agent_class=GenericModelingAgent, file="./Agents.md", iteration=0):
        self.agent_class = agent_class
        self.file = file                        # keep this as a path always
        self.prompt_content = open(file).read() # load content separately
        self.iteration = iteration
        self.agent = agent_class()



    def specialize_agent(self, dataset: list[dict], threshold: float = 0.8):
       
         while True:
            scores = []
            for sample in dataset:
                output, actual_calls = self.agent.run(sample["instruction"], self.file)
                expected_apis = sample["relevant_apis"]
                score = self.evaluate(actual_calls, expected_apis)
                print(f"  Score: {score:.2f} | Expected: {expected_apis} | Got: {actual_calls}")
                scores.append(score)
                self.agent.evaluation_history.append({
                    "instruction": sample["instruction"],
                    "score": score,
                    "expected": expected_apis,
                    "actual": actual_calls
                })
                if score < threshold: 
                    self.refine_agent_definition(sample["instruction"], actual_calls, expected_apis)
            avg_score = sum(scores) / len(scores)
            print(f"Iteration {self.iteration} — avg score: {avg_score:.2f}")
            if avg_score >= threshold:
                print("Threshold met. Specialization complete.")
                break

            return self.file()



    def evaluate(actual_tool_calls, expected_apis):

        if not expected_apis:
            return 1.0     
        for expected in expected_apis:
            match_found = False
            for actual in actual_tool_calls:
                if actual["api_name"] != expected["api_name"]:
                    continue
                expected_args = expected.get("arguments")
                actual_args = actual.get("arguments").get("file_path") if isinstance(actual.get("arguments"), dict) else actual.get("arguments")
                # normalize string JSON -> dict if needed
                if isinstance(expected_args, str):
                    try:
                        expected_args = json.loads(expected_args)
                    except:
                        pass
                if expected_args == actual_args:
                    match_found = True
                    break
            if not match_found:
                return 0.0
        return 1.0



    def refine_agent_definition(self, task: str, actual_calls: list[dict], expected_apis: list[dict]):

        client = OpenAI()

        refinement_prompt = f"""
    This is the old content of the agent definition file (Agents.md):

    {self.prompt_content}

    Based on the performance of the agent on the task and the API calls it made, refine the content of the agent definition file to improve its performance in future iterations.

    ## Refinement (iteration {self.iteration})

    For tasks like:
    "{task}"

    Expected API calls:
    {expected_apis}

    Actual API calls made:
    {actual_calls}

    Return a refined file, no explanations, just the content of the file in markdown format.
    """

        response = client.responses.create(
            model="gpt-4.1-mini",
            input=refinement_prompt,
            temperature=0.3
        )

        refined_content = response.output_text

        # update agent definition
        self.prompt_content = refined_content
        self.iteration += 1

        return refined_content