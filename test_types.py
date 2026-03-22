"""Tests for apoptotic_loader.types — enums, dataclasses, utilities."""

import time
from apoptotic_loader.types import (
    LifecycleState,
    StopType,
    ExpireReason,
    DriftReport,
    LifecycleEvent,
    CheckpointInfo,
    now,
    wall_now,
)


class TestLifecycleState:
    def test_all_states_exist(self):
        expected = {
            'UNLOADED', 'VERIFYING', 'LOADING', 'ACTIVE',
            'EXPIRING', 'RELOADING', 'SAFE_STOPPED', 'ERROR'
        }
        actual = {s.name for s in LifecycleState}
        assert actual == expected

    def test_state_machine_ordering(self):
        """Verify the documented state order is representable."""
        path = [
            LifecycleState.UNLOADED,
            LifecycleState.VERIFYING,
            LifecycleState.LOADING,
            LifecycleState.ACTIVE,
            LifecycleState.EXPIRING,
            LifecycleState.RELOADING,
        ]
        assert len(path) == 6


class TestStopType:
    def test_values(self):
        assert StopType.VELOCITY_RAMP.value == "velocity_ramp"
        assert StopType.IMMEDIATE_HOLD.value == "immediate_hold"
        assert StopType.RETURN_HOME.value == "return_home"

    def test_from_string(self):
        assert StopType("velocity_ramp") == StopType.VELOCITY_RAMP


class TestExpireReason:
    def test_all_reasons(self):
        reasons = {r.value for r in ExpireReason}
        assert "ttl_expired" in reasons
        assert "drift_detected" in reasons
        assert "manual_expire" in reasons


class TestDriftReport:
    def test_defaults(self):
        report = DriftReport()
        assert report.kl_divergence == 0.0
        assert report.alert is False

    def test_to_dict(self):
        report = DriftReport(
            timestamp=1000.0,
            kl_divergence=0.0312,
            entropy_ratio=1.05,
            alert=True,
            alert_reason="kl exceeded",
        )
        d = report.to_dict()
        assert d["kl_divergence"] == 0.0312
        assert d["alert"] is True
        assert d["alert_reason"] == "kl exceeded"
        assert isinstance(d["timestamp"], float)


class TestLifecycleEvent:
    def test_to_dict(self):
        event = LifecycleEvent(
            timestamp=1000.0,
            from_state="ACTIVE",
            to_state="EXPIRING",
            reason="ttl_expired",
            model_name="welding_arm",
            checkpoint_hash="abc123",
            cycle_number=5,
        )
        d = event.to_dict()
        assert d["from_state"] == "ACTIVE"
        assert d["to_state"] == "EXPIRING"
        assert d["cycle_number"] == 5


class TestCheckpointInfo:
    def test_defaults(self):
        info = CheckpointInfo()
        assert info.verified is False
        assert info.uri == ""


class TestTimeFunctions:
    def test_now_is_monotonic(self):
        t1 = now()
        t2 = now()
        assert t2 >= t1

    def test_wall_now_is_epoch(self):
        t = wall_now()
        assert t > 1_700_000_000  # After 2023
