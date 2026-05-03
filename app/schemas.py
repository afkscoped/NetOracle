from pydantic import BaseModel, Field
from typing import Any


class MetricFrame(BaseModel):
    timestamp: str
    slice_id: str
    node_id: str
    node_type: str
    metrics: dict[str, float]
    fault_label: int = 0
    fault_type: str | None = None


class FaultInjectionRequest(BaseModel):
    slice_id: str = "slice_1"
    node_id: str = "upf_1"
    fault_type: str = Field(default="congestion", pattern="^(congestion|cpu_overload|packet_loss|vnf_degradation|latency_spike)$")
    severity: float = Field(default=0.85, ge=0.1, le=1.0)


class NaturalLanguageQuery(BaseModel):
    question: str


class DemoRunRequest(BaseModel):
    slice_id: str = "slice_1"
    node_id: str = "upf_1"
    fault_type: str = "congestion"
    severity: float = 0.85
    ticks: int = Field(default=24, ge=5, le=200)


class ApiResponse(BaseModel):
    ok: bool
    data: Any
