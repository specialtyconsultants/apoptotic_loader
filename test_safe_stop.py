"""Tests for safe_stop_node — stop strategies, clearance, alerts."""

import json

from apoptotic_loader.safe_stop_node import SafeStopNode, SafeStopState
from apoptotic_loader.types import StopType
from mock_std_msgs import String


class TestSafeStopInit:
    def test_default_state_is_idle(self):
        node = SafeStopNode()
        assert node._state == SafeStopState.IDLE
        assert node.is_cleared is True

    def test_default_stop_type(self):
        node = SafeStopNode()
        assert node._stop_type == StopType.VELOCITY_RAMP


class TestTriggerStop:
    def test_trigger_sets_stopping_state(self):
        node = SafeStopNode()
        msg = String()
        msg.data = json.dumps({"reason": "ttl_expired", "model_name": "test"})
        node._on_trigger(msg)
        assert node._state in (SafeStopState.STOPPING, SafeStopState.STOPPED,
                                SafeStopState.AWAITING_CLEARANCE)

    def test_trigger_publishes_operator_alert(self):
        node = SafeStopNode()
        alert_pub = node.get_publisher('operator_alert')
        before = len(alert_pub.published)

        msg = String()
        msg.data = json.dumps({"reason": "drift_detected"})
        node._on_trigger(msg)

        assert len(alert_pub.published) > before
        data = json.loads(alert_pub.published[-1].data)
        assert "drift_detected" in data["stop_reason"]

    def test_duplicate_trigger_ignored(self):
        node = SafeStopNode()
        msg = String()
        msg.data = json.dumps({"reason": "test"})
        node._on_trigger(msg)

        alert_pub = node.get_publisher('operator_alert')
        count_after_first = len(alert_pub.published)

        # Second trigger should be ignored
        node._on_trigger(msg)
        assert len(alert_pub.published) == count_after_first

    def test_reason_extracted_from_json(self):
        node = SafeStopNode()
        msg = String()
        msg.data = json.dumps({"reason": "max_reload_failures"})
        node._on_trigger(msg)
        assert node._stop_reason == "max_reload_failures"

    def test_plain_string_reason(self):
        node = SafeStopNode()
        msg = String()
        msg.data = "simple_reason"
        node._on_trigger(msg)
        assert node._stop_reason == "simple_reason"


class TestImmediateHold:
    def test_immediate_hold_publishes_zero_velocity(self):
        node = SafeStopNode()
        node._stop_type = StopType.IMMEDIATE_HOLD
        node._require_clearance = False

        vel_pub = node.get_publisher('velocity_command')
        msg = String()
        msg.data = json.dumps({"reason": "test"})
        node._on_trigger(msg)

        # Should have published velocity = 0
        assert len(vel_pub.published) > 0
        data = json.loads(vel_pub.published[-1].data)
        assert data["velocity_scale"] == 0.0

    def test_immediate_hold_goes_to_cleared_without_gate(self):
        node = SafeStopNode()
        node._stop_type = StopType.IMMEDIATE_HOLD
        node._require_clearance = False

        msg = String()
        msg.data = json.dumps({"reason": "test"})
        node._on_trigger(msg)

        assert node._state == SafeStopState.CLEARED
        assert node.is_cleared is True


class TestReturnHome:
    def test_return_home_publishes_position(self):
        node = SafeStopNode()
        node._stop_type = StopType.RETURN_HOME
        node._home_position = [1.0, 2.0, 3.0, 0.0, 0.0, 0.0]
        node._require_clearance = False

        vel_pub = node.get_publisher('velocity_command')
        msg = String()
        msg.data = json.dumps({"reason": "test"})
        node._on_trigger(msg)

        assert len(vel_pub.published) > 0
        data = json.loads(vel_pub.published[-1].data)
        assert data["command"] == "return_home"
        assert data["target_position"] == [1.0, 2.0, 3.0, 0.0, 0.0, 0.0]


class TestVelocityRamp:
    def test_ramp_creates_timer(self):
        node = SafeStopNode()
        node._stop_type = StopType.VELOCITY_RAMP
        initial_timer_count = len(node._timers)

        msg = String()
        msg.data = json.dumps({"reason": "test"})
        node._on_trigger(msg)

        # Should have created a ramp timer
        assert len(node._timers) > initial_timer_count

    def test_ramp_tick_decreases_velocity(self):
        node = SafeStopNode()
        node._stop_type = StopType.VELOCITY_RAMP
        node._ramp_seconds = 5.0

        msg = String()
        msg.data = json.dumps({"reason": "test"})
        node._on_trigger(msg)

        vel_pub = node.get_publisher('velocity_command')
        # First tick (almost immediately after start) should be near 1.0
        node._ramp_tick()
        if vel_pub.published:
            data = json.loads(vel_pub.published[-1].data)
            assert data["velocity_scale"] <= 1.0


class TestClearanceGate:
    def test_requires_clearance_by_default(self):
        node = SafeStopNode()
        node._stop_type = StopType.IMMEDIATE_HOLD
        node._require_clearance = True

        msg = String()
        msg.data = json.dumps({"reason": "test"})
        node._on_trigger(msg)

        assert node._state == SafeStopState.AWAITING_CLEARANCE
        assert node.is_cleared is False

    def test_operator_clearance_clears_gate(self):
        node = SafeStopNode()
        node._stop_type = StopType.IMMEDIATE_HOLD
        node._require_clearance = True

        # Trigger stop
        msg = String()
        msg.data = json.dumps({"reason": "test"})
        node._on_trigger(msg)
        assert node._state == SafeStopState.AWAITING_CLEARANCE

        # Operator clears
        clear_msg = String()
        clear_msg.data = "operator_confirmed"
        node._on_operator_clear(clear_msg)

        assert node._state == SafeStopState.CLEARED
        assert node.is_cleared is True

    def test_clearance_ignored_when_not_awaiting(self):
        node = SafeStopNode()
        # In IDLE state, clearance is a no-op
        clear_msg = String()
        clear_msg.data = "premature_clear"
        node._on_operator_clear(clear_msg)
        assert node._state == SafeStopState.IDLE

    def test_reset_returns_to_idle(self):
        node = SafeStopNode()
        node._stop_type = StopType.IMMEDIATE_HOLD
        node._require_clearance = False

        msg = String()
        msg.data = json.dumps({"reason": "test"})
        node._on_trigger(msg)

        node.reset()
        assert node._state == SafeStopState.IDLE
        assert node._stop_reason == ""
