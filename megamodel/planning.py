from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from enum import Enum
from datetime import datetime
import uuid


class PlanStatus(Enum):
    CREATED = "created"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class StepStatus(Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class AgentGoal:
    description: str
    success_criteria: Dict[str, Any] = field(default_factory=dict)

    def validate(self) -> Dict[str, Any]:
        return {"valid": len(self.description) > 0}


@dataclass
class Step:
    """Maps to diagram: Step(tool_name, server_name, parameters)"""
    tool_name: str
    server_name: str = ""
    parameters: List[str] = field(default_factory=list)
    # Runtime fields
    step_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    description: str = ""
    status: StepStatus = StepStatus.PENDING
    dependencies: List['Step'] = field(default_factory=list)
    result: Dict[str, Any] = field(default_factory=dict)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None

    def can_execute(self) -> bool:
        return all(dep.status == StepStatus.COMPLETED for dep in self.dependencies)

    def mark_ready(self):
        if self.can_execute():
            self.status = StepStatus.READY

    def start_execution(self):
        self.status = StepStatus.RUNNING
        self.start_time = datetime.now()

    def mark_completed(self, result: Dict[str, Any] = None):
        self.status = StepStatus.COMPLETED
        self.end_time = datetime.now()
        if result:
            self.result = result

    def mark_failed(self, error: str):
        self.status = StepStatus.FAILED
        self.end_time = datetime.now()
        self.result = {"error": error}


# Keep PlanStep as alias for backwards compatibility
PlanStep = Step


@dataclass
class Workflow:
    """Maps to diagram: Workflow(instruction) -> plan_steps 1..* -> Step"""
    goal: AgentGoal
    instruction: str = ""
    plan_steps: List[Step] = field(default_factory=list)
    status: PlanStatus = PlanStatus.CREATED
    plan_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None

    def add_step(self, step: Step):
        self.plan_steps.append(step)
        self._update_step_readiness()

    def get_ready_steps(self) -> List[Step]:
        return [s for s in self.plan_steps if s.status == StepStatus.READY]

    def get_running_steps(self) -> List[Step]:
        return [s for s in self.plan_steps if s.status == StepStatus.RUNNING]

    def get_completed_steps(self) -> List[Step]:
        return [s for s in self.plan_steps if s.status == StepStatus.COMPLETED]

    def get_failed_steps(self) -> List[Step]:
        return [s for s in self.plan_steps if s.status == StepStatus.FAILED]

    def _update_step_readiness(self):
        for step in self.plan_steps:
            if step.status == StepStatus.PENDING and step.can_execute():
                step.mark_ready()

    def validate_plan(self) -> Dict[str, Any]:
        issues = []
        if not self.goal.validate()["valid"]:
            issues.append("Invalid goal")
        if not self.plan_steps:
            issues.append("No steps defined")
        return {"valid": len(issues) == 0, "issues": issues}

    def start_execution(self):
        self.status = PlanStatus.IN_PROGRESS
        self.start_time = datetime.now()
        self._update_step_readiness()

    def check_completion(self) -> bool:
        if self.status != PlanStatus.IN_PROGRESS:
            return False
        if all(s.status == StepStatus.COMPLETED for s in self.plan_steps):
            self.status = PlanStatus.COMPLETED
            self.end_time = datetime.now()
            return True
        if any(s.status == StepStatus.FAILED for s in self.plan_steps):
            self.status = PlanStatus.FAILED
            self.end_time = datetime.now()
            return True
        return False


WorkflowPlan = Workflow