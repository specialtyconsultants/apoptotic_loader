"""Tests for manager_node — state machine, lifecycle, expiration."""

import json
import time

from apoptotic_loader.manager_node import ApoptoticManagerNode
from apoptotic_loader.types import LifecycleState, ExpireReason
from mock_std_msgs import String


class TestManagerNodeInit:
    def test_initializes_in_verifying_state(self):
        """On init, the manager immediately begins a cycle (VERIFYING)."""
        node = ApoptoticManagerNode()
        assert node.state == LifecycleState.VERIFYING

    def test_default_parameters(self):
        node = ApoptoticManagerNode()
        assert node._ttl_seconds == 86400
        assert node._model_name == "default_model"
        assert node._on_expire == "reload"
        assert node._early_expire is True
        assert node._max_failures == 3


class TestStateMachine:
    def _make_node(self, **overrides):
        node = ApoptoticManagerNode()
        for k, v in overrides.items():
            setattr(node, f'_{k}', v)
        return node

    def test_transition_publishes_event(self):
        node = self._make_node()
        event_pub = node.get_publisher('lifecycle_event')
        initial_count = len(event_pub.published)

        node._transition(LifecycleState.LOADING, "test_reason")

        assert len(event_pub.published) > initial_count
        event_data = json.loads(event_pub.published[-1].data)
        assert event_data["to_state"] == "LOADING"
        assert event_data["reason"] == "test_reason"

    def test_transition_updates_state(self):
        node = self._make_node()
        node._transition(LifecycleState.ACTIVE, "test")
        assert node.state == LifecycleState.ACTIVE

    def test_verification_success_triggers_load(self):
        """When checkpoint verified, node should transition to LOADING."""
        node = self._make_node()
        assert node.state == LifecycleState.VERIFYING

        # Simulate verification success
        msg = String()
        msg.data = json.dumps({"verified": True, "hash": "abc123..."})
        node._on_verification_result(msg)

        # Should have gone through LOADING → ACTIVE (stub always succeeds)
        assert node.state == LifecycleState.ACTIVE
        assert node.cycle_number == 1

    def test_verification_failure_retries(self):
        node = self._make_node(max_failures=3, consecutive_failures=0)
        assert node.state == LifecycleState.VERIFYING

        # Simulate verification failure
        msg = String()
        msg.data = json.dumps({"verified": False, "detail": "hash_mismatch"})
        node._on_verification_result(msg)

        # Should retry — back in VERIFYING
        assert node._consecutive_failures == 1
        assert node.state == LifecycleState.VERIFYING

    def test_max_failures_triggers_safe_stop(self):
        node = self._make_node(max_failures=2, consecutive_failures=1)
        # Already at 1 failure, next will be 2 = max
        msg = String()
        msg.data = json.dumps({"verified": False, "detail": "corruption"})
        node._on_verification_result(msg)

        assert node.state == LifecycleState.SAFE_STOPPED

        # Verify safe-stop was published
        safe_pub = node.get_publisher('safe_stop_controller/trigger')
        assert len(safe_pub.published) > 0


class TestModelLoadDestroy:
    def test_stub_load_succeeds(self):
        """Default stub always returns True."""
        node = ApoptoticManagerNode()
        assert node._execute_model_load() is True

    def test_subclass_load_hook(self):
        """Verify the subclass hook pattern works."""
        load_called = False
        destroy_called = False

        class MyManager(ApoptoticManagerNode):
            def _execute_model_load(self) -> bool:
                nonlocal load_called
                load_called = True
                return True

            def _execute_model_destroy(self):
                nonlocal destroy_called
                destroy_called = True

        node = MyManager()
        # Simulate successful verification to trigger load
        msg = String()
        msg.data = json.dumps({"verified": True, "hash": "test"})
        node._on_verification_result(msg)

        assert load_called
        assert node.state == LifecycleState.ACTIVE

        # Force expire to trigger destroy
        expire_msg = String()
        expire_msg.data = "manual_test"
        node._on_force_expire(expire_msg)

        assert destroy_called

    def test_load_failure_increments_counter(self):
        class FailingManager(ApoptoticManagerNode):
            def _execute_model_load(self) -> bool:
                return False

        node = FailingManager()
        node._max_failures = 5  # high so we don't safe-stop yet

        msg = String()
        msg.data = json.dumps({"verified": True, "hash": "test"})
        node._on_verification_result(msg)

        assert node._consecutive_failures >= 1


class TestTTLExpiration:
    def test_ttl_remaining_when_active(self):
        node = ApoptoticManagerNode()
        node._ttl_seconds = 100

        # Get to ACTIVE state
        msg = String()
        msg.data = json.dumps({"verified": True, "hash": "test"})
        node._on_verification_result(msg)

        assert node.state == LifecycleState.ACTIVE
        remaining = node.ttl_remaining
        assert 99 <= remaining <= 100

    def test_ttl_remaining_when_not_active(self):
        node = ApoptoticManagerNode()
        assert node.ttl_remaining == 0.0

    def test_tick_publishes_countdown(self):
        node = ApoptoticManagerNode()
        node._ttl_seconds = 3600

        # Get to ACTIVE
        msg = String()
        msg.data = json.dumps({"verified": True, "hash": "test"})
        node._on_verification_result(msg)

        countdown_pub = node.get_publisher('ttl_countdown')
        before = len(countdown_pub.published)
        node._tick()
        assert len(countdown_pub.published) > before

        data = json.loads(countdown_pub.published[-1].data)
        assert "ttl_remaining_seconds" in data
        assert data["ttl_remaining_seconds"] > 0

    def test_expired_ttl_triggers_apoptosis(self):
        node = ApoptoticManagerNode()
        node._ttl_seconds = 0  # Immediate expiry

        # Get to ACTIVE
        msg = String()
        msg.data = json.dumps({"verified": True, "hash": "test"})
        node._on_verification_result(msg)

        # Tick should detect expired TTL
        node._tick()
        # Should be in VERIFYING (reloading → begin_cycle → verifying)
        assert node.state in (
            LifecycleState.VERIFYING,
            LifecycleState.RELOADING,
            LifecycleState.EXPIRING,
        )


class TestDriftTriggeredExpire:
    def test_drift_alert_causes_early_expire(self):
        node = ApoptoticManagerNode()
        node._early_expire = True

        # Get to ACTIVE
        msg = String()
        msg.data = json.dumps({"verified": True, "hash": "test"})
        node._on_verification_result(msg)
        assert node.state == LifecycleState.ACTIVE

        # Simulate drift alert
        alert = String()
        alert.data = json.dumps({"alert": True, "kl_divergence": 0.12})
        node._on_drift_alert(alert)

        # Should have expired
        assert node.state != LifecycleState.ACTIVE

    def test_drift_alert_ignored_when_disabled(self):
        node = ApoptoticManagerNode()
        node._early_expire = False

        # Get to ACTIVE
        msg = String()
        msg.data = json.dumps({"verified": True, "hash": "test"})
        node._on_verification_result(msg)

        alert = String()
        alert.data = json.dumps({"alert": True})
        node._on_drift_alert(alert)

        # Should still be ACTIVE
        assert node.state == LifecycleState.ACTIVE


class TestForceExpire:
    def test_manual_expire(self):
        node = ApoptoticManagerNode()

        # Get to ACTIVE
        msg = String()
        msg.data = json.dumps({"verified": True, "hash": "test"})
        node._on_verification_result(msg)

        # Force expire
        force_msg = String()
        force_msg.data = "manual_test"
        node._on_force_expire(force_msg)

        assert node.state != LifecycleState.ACTIVE
