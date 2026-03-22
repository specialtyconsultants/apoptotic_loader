"""
Shared types, enums, and constants for the Apoptotic Model Loading framework.
"""

from enum import Enum, auto
from dataclasses import dataclass, field
import time


class LifecycleState(Enum):
    """
    State machine for the apoptotic model lifecycle.

    UNLOADED → VERIFYING → LOADING → ACTIVE → EXPIRING → RELOADING
                                        ↑                    |
                                        └────────────────────┘
    """
    UNLOADED = auto()
    VERIFYING = auto()
    LOADING = auto()
    ACTIVE = auto()
    EXPIRING = auto()
    RELOADING = auto()
    SAFE_STOPPED = auto()
    ERROR = auto()


class StopType(Enum):
    """Safe-stop strategies."""
    VELOCITY_RAMP = "velocity_ramp"
    IMMEDIATE_HOLD = "immediate_hold"
    RETURN_HOME = "return_home"


class ExpireReason(Enum):
    """Why a model cycle ended."""
    TTL_EXPIRED = "ttl_expired"
    DRIFT_DETECTED = "drift_detected"
    MANUAL_EXPIRE = "manual_expire"
    CHECKPOINT_MISMATCH = "checkpoint_mismatch"
    RELOAD_FAILURE = "reload_failure"


@dataclass
class DriftReport:
    """Drift metrics published by the observer."""
    timestamp: float = 0.0
    kl_divergence: float = 0.0
    entropy_ratio: float = 1.0
    mean_latency_ms: float = 0.0
    latency_anomaly: bool = False
    samples_since_load: int = 0
    alert: bool = False
    alert_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "kl_divergence": round(self.kl_divergence, 6),
            "entropy_ratio": round(self.entropy_ratio, 4),
            "mean_latency_ms": round(self.mean_latency_ms, 2),
            "latency_anomaly": self.latency_anomaly,
            "samples_since_load": self.samples_since_load,
            "alert": self.alert,
            "alert_reason": self.alert_reason,
        }


@dataclass
class LifecycleEvent:
    """Audit record for a lifecycle transition."""
    timestamp: float = 0.0
    from_state: str = ""
    to_state: str = ""
    reason: str = ""
    model_name: str = ""
    checkpoint_hash: str = ""
    cycle_number: int = 0

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "from_state": self.from_state,
            "to_state": self.to_state,
            "reason": self.reason,
            "model_name": self.model_name,
            "checkpoint_hash": self.checkpoint_hash,
            "cycle_number": self.cycle_number,
        }


@dataclass
class CheckpointInfo:
    """Metadata about a verified checkpoint."""
    uri: str = ""
    expected_hash: str = ""
    verified: bool = False
    verified_at: float = 0.0
    size_bytes: int = 0
    last_error: str = ""


# --- Utility ---------------------------------------------------------------

def now() -> float:
    """Monotonic clock for TTL calculations (not wall-clock)."""
    return time.monotonic()


def wall_now() -> float:
    """Wall-clock time for audit timestamps."""
    return time.time()
