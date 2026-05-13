from dataclasses import dataclass, field
from typing import Optional, List, Dict
from enum import Enum


@dataclass
class Capability:
    name: str
    description: str = ""
    tool_keywords: List[str] = field(default_factory=list)
    rules: List[str] = field(default_factory=list)

class Status(Enum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"


class ModelType(Enum):
    REFERENCE = "reference"
    TRANSFORMATION = "transformation"
    TERMINAL = "terminal"


@dataclass
class Entity:
    uri: str
    name: str = ""
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.name:
            self.name = self.uri.split('/')[-1] if '/' in self.uri else self.uri


@dataclass
class Relationship:
    source: Entity
    target: Entity
    relationship_type: str = "conformsTo"


# ── Artifacts ──────────────────────────────────────────────

@dataclass
class Model(Entity):
    conformsTo: Optional['Metamodel'] = None
    model_type: ModelType = ModelType.TERMINAL
    content_path: Optional[str] = None

    def __post_init__(self):
        super().__post_init__()


@dataclass
class Metamodel(Model):
    source_metamodels: List['Metamodel'] = field(default_factory=list)  # sourceMM
    target_metamodels: List['Metamodel'] = field(default_factory=list)  # targetMM

    def __post_init__(self):
        super().__post_init__()
        self.model_type = ModelType.REFERENCE


ReferenceModel = Metamodel


@dataclass
class TransformationModel(Model):
    transformation_language: str = "ATL"
    source_metamodel: Optional[Metamodel] = None
    target_metamodel: Optional[Metamodel] = None
    sample_sources: List[str] = field(default_factory=list)

    def __post_init__(self):
        super().__post_init__()
        self.model_type = ModelType.TRANSFORMATION


@dataclass
class TerminalModel(Model):
    instance_data: Optional[dict] = None

    def __post_init__(self):
        super().__post_init__()
        self.model_type = ModelType.TERMINAL


# ── Tools ──────────────────────────────────────────────────

@dataclass
class Resource:
    uri: str


@dataclass
class Tool(Resource):
    name: str = ""
    description: str = ""
    parameters: Dict[str, str] = field(default_factory=dict)
    server_name: str = ""


@dataclass
class ModelingTool(Tool):
    entities: List[Entity] = field(default_factory=list)


@dataclass
class MetamodelingTool(ModelingTool):
    pass


@dataclass
class TransformationTool(ModelingTool):
    pass


@dataclass
class Server:
    name: str
    port: int = 0
    status: Status = Status.DISCONNECTED
    resources: List[Resource] = field(default_factory=list)
    capabilities: List[Capability] = field(default_factory=list)
    script_path: str = ""
    metadata: dict = field(default_factory=dict)


# ── Agents ─────────────────────────────────────────────────

@dataclass
class Agent:
    model: str
    prompt: str
    tools: List[Tool] = field(default_factory=list)


@dataclass
class ModelingAgent(Agent):
    pass


@dataclass
class MetamodelingAgent(ModelingAgent):
    pass


@dataclass
class TransformationAgent(ModelingAgent):
    pass