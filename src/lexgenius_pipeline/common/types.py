from enum import Enum


class RecordType(str, Enum):
    ADVERSE_EVENT = "adverse_event"
    RECALL = "recall"
    FILING = "filing"
    REGULATION = "regulation"
    RESEARCH = "research"
    NEWS = "news"
    LEGISLATION = "legislation"
    ENFORCEMENT = "enforcement"


class SourceTier(str, Enum):
    FEDERAL = "federal"
    STATE = "state"
    JUDICIAL = "judicial"
    COMMERCIAL = "commercial"


class SignalStrength(str, Enum):
    WEAK = "weak"
    MODERATE = "moderate"
    STRONG = "strong"
    CRITICAL = "critical"


class ExecutionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"
