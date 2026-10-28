from typing import List, Dict
from dataclasses import dataclass, field


@dataclass
class Seed:
    instruction: str
    level: int
    pattern: str
    relevant_apis: List[Dict[str, str]] = field(default_factory=list)


class SingleToolSeeds:
    """9 diverse single-tool seeds using only apply and get operations"""

    @staticmethod
    def get_seeds() -> List[Seed]:
        return [
            # Level 1 - Full transformation name
            Seed(
                instruction="Apply Mantis2XML to ./atl_zoo/SoftwareQualityControl2MantisBTFile/modelsExamples/MantisExample.xmi",
                level=1,
                pattern="apply",
                relevant_apis=[
                    {
                        "api_name": "apply_Mantis2XML_transformation_tool",
                        "arguments": "./atl_zoo/SoftwareQualityControl2MantisBTFile/modelsExamples/MantisExample.xmi"
                    }
                ]
            ),
            Seed(
                instruction="Show me the configuration settings for the PNML2XML transformation",
                level=1,
                pattern="get",
                relevant_apis=[
                    {
                        "api_name": "list_transformation_PNML2XML_tool",
                        "arguments": ""
                    }
                ]
            ),

            # Level 2 - Source and target models mentioned
            Seed(
                instruction="Transform the KM3 model ./atl_zoo/KM32EMF/Sample-KM3.xmi into a DSL model",
                level=2,
                pattern="apply",
                relevant_apis=[
                    {
                        "api_name": "apply_KM32DSL_transformation_tool",
                        "arguments": "./atl_zoo/KM32EMF/Sample-KM3.xmi"
                    }
                ]
            ),
            Seed(
                instruction="What transformation can I use to convert MySQL schemas to KM3 format?",
                level=2,
                pattern="get",
                relevant_apis=[
                    {
                        "api_name": "list_transformation_MySQL2KM3_tool",
                        "arguments": ""
                    }
                ]
            ),

            # Level 3 - Only target model mentioned
            Seed(
                instruction="Transform this model /Users/zakariahachm/Downloads/llm-agents-mde/src/examples/class.xmi to Relational model",
                level=3,
                pattern="apply",
                relevant_apis=[
                    {
                        "api_name": "apply_Class2Relational_transformation_tool",
                        "arguments": "/Users/zakariahachm/Downloads/llm-agents-mde/src/examples/class.xmi"
                    }
                ]
            ),
            Seed(
                instruction="List me the details of the transformation that transforms this file /Users/zakariahachm/Downloads/llm-agents-mde/src/examples/class.xmi to Relational model",
                level=3,
                pattern="get",
                relevant_apis=[
                    {
                        "api_name": "list_transformation_Class2Relational_tool",
                        "arguments": ""
                    }
                ]
            ),

        ]