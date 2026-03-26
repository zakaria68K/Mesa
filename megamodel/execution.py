from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from datetime import datetime
from enum import Enum
import uuid

from .am3 import Status


@dataclass
class Invocation:
    """Maps to diagram: Invocation(content, is_error) -> arguments -> Status"""
    content: str
    is_error: bool = False
    arguments: Dict[str, Any] = field(default_factory=dict)
    status: Status = Status.CONNECTED
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class TraceStep:
    """Maps to diagram: TraceStep(tool_name, success) -> invocations 0..* -> Invocation"""
    tool_name: str
    success: bool = True
    invocations: List[Invocation] = field(default_factory=list)

    def add_invocation(self, invocation: Invocation):
        self.invocations.append(invocation)


@dataclass
class ExecutionTrace:
    """Maps to diagram: ExecutionTrace(instruction) -> trace_steps 1..* -> TraceStep"""
    instruction: str = ""
    trace_steps: List[TraceStep] = field(default_factory=list)
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def add_trace_step(self, step: TraceStep):
        self.trace_steps.append(step)

    def analyze(self) -> Dict[str, Any]:
        total = sum(len(s.invocations) for s in self.trace_steps)
        successful = sum(len([i for i in s.invocations if not i.is_error]) for s in self.trace_steps)
        return {
            "total_invocations": total,
            "successful_invocations": successful,
            "success_rate": (successful / total * 100) if total > 0 else 0
        }


@dataclass
class AgentSession:
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    context: Dict[str, Any] = field(default_factory=dict)
    execution_traces: List[ExecutionTrace] = field(default_factory=list)
    start_time: datetime = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    status: str = "created"

    def start(self):
        self.start_time = datetime.now()
        self.status = "running"

    def end(self, status: str = "completed"):
        self.end_time = datetime.now()
        self.status = status

    def create_new_trace(self, instruction: str = "") -> ExecutionTrace:
        trace = ExecutionTrace(instruction=instruction)
        self.execution_traces.append(trace)
        return trace