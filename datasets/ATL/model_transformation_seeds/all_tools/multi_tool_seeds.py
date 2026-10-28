from typing import List, Dict
from dataclasses import dataclass, field


@dataclass
class Seed:
    instruction: str
    level: int
    pattern: str
    relevant_apis: List[Dict[str, str]] = field(default_factory=list)


class MultiToolSeeds:

    @staticmethod
    def get_seeds() -> List[Seed]:
        return [
            # LEVEL 1 - Full transformation names
            Seed(
                instruction="First show me the configuration of Class2Relational and then transform ./atl_zoo/PNML2XML/modelsExamples/PetriNet2.xmi using PNML2XML transformation",
                level=1,
                pattern="get, apply",
                relevant_apis=[
                    {
                        "api_name": "list_transformation_Class2Relational_tool",
                        "arguments": ""
                    },
                    {
                        "api_name": "apply_PNML2XML_transformation_tool",
                        "arguments": "./atl_zoo/PNML2XML/modelsExamples/PetriNet2.xmi"
                    }
                ]
            ),
            Seed(
                instruction="Compare the configurations of the Mantis2XML and MySQL2KM3 transformations",
                level=1,
                pattern="get, get",
                relevant_apis=[
                    {
                        "api_name": "list_transformation_Mantis2XML_tool",
                        "arguments": ""
                    },
                    {
                        "api_name": "list_transformation_MySQL2KM3_tool",
                        "arguments": ""
                    }
                ]
            ),
            Seed(
                instruction="Transform ./atl_zoo/KM32EMF/Sample-KM3.xmi with KM32DSL and then check the PNML2XML configuration",
                level=1,
                pattern="apply, get",
                relevant_apis=[
                    {
                        "api_name": "apply_KM32DSL_transformation_tool",
                        "arguments": "./atl_zoo/KM32EMF/Sample-KM3.xmi"
                    },
                    {
                        "api_name": "list_transformation_PNML2XML_tool",
                        "arguments": ""
                    }
                ]
            ),
            Seed(
                instruction="Transform ./atl_zoo/Ant2Maven/Examples/input/Ant/build.xmi using Ant2Maven and then transform ./atl_zoo/BibTeX2DocBook/samples/sample1.xmi using BibTeX2DocBook",
                level=1,
                pattern="apply, apply",
                relevant_apis=[
                    {
                        "api_name": "apply_Ant2Maven_transformation_tool",
                        "arguments": "./atl_zoo/Ant2Maven/Examples/input/Ant/build.xmi"
                    },
                    {
                        "api_name": "apply_BibTeX2DocBook_transformation_tool",
                        "arguments": "./atl_zoo/BibTeX2DocBook/samples/sample1.xmi"
                    }
                ]
            ),

            # LEVEL 2 - Source and target models mentioned
            Seed(
                instruction="Show me the configuration settings of the transformation that transforms a Class into a Relational model and then transform ./atl_zoo/PNML2XML/modelsExamples/PetriNet2.xmi from a PNML model to a XML model",
                level=2,
                pattern="get, apply",
                relevant_apis=[
                    {
                        "api_name": "list_transformation_Class2Relational_tool",
                        "arguments": ""
                    },
                    {
                        "api_name": "apply_PNML2XML_transformation_tool",
                        "arguments": "./atl_zoo/PNML2XML/modelsExamples/PetriNet2.xmi"
                    }
                ]
            ),
            Seed(
                instruction="Transform the KM3 model ./atl_zoo/KM32EMF/Sample-KM3.xmi to DSL and then compare the configurations of the transformation that transforms a MySQL into a KM3",
                level=2,
                pattern="apply, get",
                relevant_apis=[
                    {
                        "api_name": "apply_KM32DSL_transformation_tool",
                        "arguments": "./atl_zoo/KM32EMF/Sample-KM3.xmi"
                    },
                    {
                        "api_name": "list_transformation_MySQL2KM3_tool",
                        "arguments": ""
                    }
                ]
            ),
            Seed(
                instruction="Transform the Book model /Publication/outputModelPublication.xmi to a Publication model and then transform the Family model ./atl_zoo/BibTeX2DocBook/samples/sample1.xmi to a Persons model",
                level=2,
                pattern="apply, apply",
                relevant_apis=[
                    {
                        "api_name": "apply_Book2Publication_transformation_tool",
                        "arguments": "/Publication/outputModelPublication.xmi"
                    },
                    {
                        "api_name": "apply_Families2Persons_transformation_tool",
                        "arguments": "./atl_zoo/BibTeX2DocBook/samples/sample1.xmi"
                    }
                ]
            ),
            Seed(
                instruction="Show me the configuration settings of the transformation that transforms a Class into a Relational and then show me the configuration settings of the transformation that transforms a Ant into a Maven",
                level=2,
                pattern="get, get",
                relevant_apis=[
                    {
                        "api_name": "list_transformation_Class2Relational_tool",
                        "arguments": ""
                    },
                    {
                        "api_name": "list_transformation_Ant2Maven_tool",
                        "arguments": ""
                    }
                ]
            ),

            # LEVEL 3 - Only target model mentioned
            Seed(
                instruction="Transform this model /Users/zakariahachm/Downloads/llm-agents-mde/src/examples/class.xmi to Relational model and then transform this model /Users/zakariahachm/Downloads/llm-agents-mde/src/examples/petrinet.xmi to XML model",
                level=3,
                pattern="apply, apply",
                relevant_apis=[
                    {
                        "api_name": "apply_Class2Relational_transformation_tool",
                        "arguments": "/Users/zakariahachm/Downloads/llm-agents-mde/src/examples/class.xmi"
                    },
                    {
                        "api_name": "apply_PNML2XML_transformation_tool",
                        "arguments": "/Users/zakariahachm/Downloads/llm-agents-mde/src/examples/petrinet.xmi"
                    }
                ]
            ),
            Seed(
                instruction="Show me the transformation that transforms this file /Users/zakariahachm/Downloads/llm-agents-mde/src/examples/mantis.xmi to XML model then transform this model /Users/zakariahachm/Downloads/llm-agents-mde/src/examples/ant.xmi to Maven model",
                level=3,
                pattern="get, apply",
                relevant_apis=[
                    {
                        "api_name": "list_transformation_Mantis2XML_tool",
                        "arguments": ""
                    },
                    {
                        "api_name": "apply_Ant2Maven_transformation_tool",
                        "arguments": "/Users/zakariahachm/Downloads/llm-agents-mde/src/examples/ant.xmi"
                    }
                ]
            ),
            Seed(
                instruction="Show me the transformation that transforms this file /Users/zakariahachm/Downloads/llm-agents-mde/src/examples/class.xmi to Relational model then show me the transformation that transforms this file /Users/zakariahachm/Downloads/llm-agents-mde/src/examples/bibtex.xmi to a DocBook model",
                level=3,
                pattern="get, get",
                relevant_apis=[
                    {
                        "api_name": "list_transformation_Class2Relational_tool",
                        "arguments": ""
                    },
                    {
                        "api_name": "list_transformation_BibTeX2DocBook_tool",
                        "arguments": ""
                    }
                ]
            ),
            Seed(
                instruction="Transform this model /MetamodelBridge/Models/SimpleExample/DSL2EMF/SimpleExampleMM-XML.xmi to DSL model then show me the transformation that transforms this file /Users/zakariahachm/Downloads/llm-agents-mde/src/examples/mysql.xmi to KM3 model",
                level=3,
                pattern="apply, get",
                relevant_apis=[
                    {
                        "api_name": "apply_XML2DSL_transformation_tool",
                        "arguments": "/MetamodelBridge/Models/SimpleExample/DSL2EMF/SimpleExampleMM-XML.xmi"
                    },
                    {
                        "api_name": "list_transformation_MySQL2KM3_tool",
                        "arguments": ""
                    }
                ]
            )
        ]