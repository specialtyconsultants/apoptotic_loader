"""
manager_node — Core apoptotic lifecycle controller.

Implements the state machine:
    UNLOADED → VERIFYING → LOADING → ACTIVE → EXPIRING → RELOADING
                                       ↑                     |
                                       └─────────────────────┘

The model runs under a 24-hour TTL. At expiration the state is *destroyed*
(not paused, not archived) and a fresh instance loads from the verified
checkpoint.  Drift alerts from the observer can trigger early expiration.

Topics Published:
    ~/model_status    (std_msgs/String)  — current state + metadata JSON
    ~/ttl_countdown   (std_msgs/String)  — seconds remaining JSON
    ~/lifecycle_event (std_msgs/String)  — audit events JSON

Topics Subscribed:
    ~/force_expire    (std_msgs/String)  — manual expiration trigger
    ~/drift_alert     (std_msgs/String)  — from drift_observer_node

Subscribes (cross-node):
    /checkpoint_registry/verification_result (std_msgs/String)
"""

import json
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from apoptotic_loader.types import (
    LifecycleState,
    ExpireReason,
    LifecycleEvent,
    now,
    wall_now,
)


class ApoptoticManagerNode(Node):
    """
    Core lifecycle controller for apoptotic model loading.

    Subclass and override ``_execute_model_load()`` and
    ``_execute_model_destroy()`` to integrate your model framework
    (PyTorch, TensorRT, GR00T, etc.).
    """

    def __init__(self, node_name: str = 'apoptotic_manager'):
        super().__init__(node_name)

        # --- Parameters ---
        self.declare_parameter('model_name', 'default_model')
        self.declare_parameter('ttl_seconds', 86400)
        self.declare_parameter('on_expire', 'reload')
        self.declare_parameter('on_fail', 'safe_stop')
        self.declare_parameter('early_expire_on_drift', True)
        self.declare_parameter('max_reload_failures', 3)
        self.declare_parameter('countdown_publish_rate', 10.0)
        self.declare_parameter('reload_grace_seconds', 30.0)

        self._model_name = self.get_parameter('model_name').get_parameter_value().string_value
        self._ttl_seconds = self.get_parameter('ttl_seconds').get_parameter_value().integer_value
        self._on_expire = self.get_parameter('on_expire').get_parameter_value().string_value
        self._on_fail = self.get_parameter('on_fail').get_parameter_value().string_value
        self._early_expire = self.get_parameter('early_expire_on_drift').get_parameter_value().bool_value
        self._max_failures = self.get_parameter('max_reload_failures').get_parameter_value().integer_value
        self._countdown_rate = self.get_parameter('countdown_publish_rate').get_parameter_value().double_value
        self._reload_grace = self.get_parameter('reload_grace_seconds').get_parameter_value().double_value

        # --- State ---
        self._state = LifecycleState.UNLOADED
        self._load_time: float = 0.0          # monotonic time of last load
        self._cycle_number: int = 0
        self._consecutive_failures: int = 0
        self._checkpoint_verified: bool = False
        self._checkpoint_hash: str = ""

        # --- Publishers ---
        self._status_pub = self.create_publisher(String, '~/model_status', 10)
        self._countdown_pub = self.create_publisher(String, '~/ttl_countdown', 10)
        self._event_pub = self.create_publisher(String, '~/lifecycle_event', 10)
        self._safe_stop_pub = self.create_publisher(String, '/safe_stop_controller/trigger', 10)

        # --- Subscribers ---
        self._force_sub = self.create_subscription(
            String, '~/force_expire', self._on_force_expire, 10
        )
        self._drift_sub = self.create_subscription(
            String, '/drift_observer/drift_alert', self._on_drift_alert, 10
        )
        self._verify_sub = self.create_subscription(
            String, '/checkpoint_registry/verification_result',
            self._on_verification_result, 10
        )

        # --- Publisher to request checkpoint verification ---
        self._verify_req_pub = self.create_publisher(
            String, '/checkpoint_registry/verify_request', 10
        )

        # --- Timers ---
        self._countdown_timer = self.create_timer(
            self._countdown_rate, self._tick
        )

        self.get_logger().info(
            f'Apoptotic Manager initialized: model={self._model_name}, '
            f'ttl={self._ttl_seconds}s ({self._ttl_seconds / 3600:.1f}h)'
        )

        # Kick off the first cycle
        self._begin_cycle()

    # ==================================================================
    # INTEGRATION HOOKS — Override these in your subclass
    # ==================================================================

    def _execute_model_load(self) -> bool:
        """
        Load your model here.

        Returns True on success, False on failure.
        Override in subclass for PyTorch / TensorRT / GR00T / etc.
        """
        self.get_logger().warn(
            '_execute_model_load() not overridden — using stub (always succeeds)'
        )
        return True

    def _execute_model_destroy(self):
        """
        Destroy your model state here. NO STATE CARRIES OVER.

        Override in subclass. Example::

            del self.model
            torch.cuda.empty_cache()
            gc.collect()
        """
        self.get_logger().warn(
            '_execute_model_destroy() not overridden — using stub'
        )

    # ==================================================================
    # STATE MACHINE
    # ==================================================================

    def _transition(self, new_state: LifecycleState, reason: str = ""):
        """Execute a state transition with audit logging."""
        old_state = self._state
        self._state = new_state

        event = LifecycleEvent(
            timestamp=wall_now(),
            from_state=old_state.name,
            to_state=new_state.name,
            reason=reason,
            model_name=self._model_name,
            checkpoint_hash=self._checkpoint_hash,
            cycle_number=self._cycle_number,
        )

        # Publish audit event
        msg = String()
        msg.data = json.dumps(event.to_dict())
        self._event_pub.publish(msg)

        self.get_logger().info(
            f'[Cycle {self._cycle_number}] {old_state.name} → {new_state.name} ({reason})'
        )

    def _begin_cycle(self):
        """Start a new apoptotic cycle: verify → load → activate."""
        self._transition(LifecycleState.VERIFYING, "cycle_start")

        # Request checkpoint verification
        msg = String()
        msg.data = json.dumps({
            "requester": "apoptotic_manager",
            "cycle": self._cycle_number,
        })
        self._verify_req_pub.publish(msg)

        # If verification doesn't come back, the _on_verification_result
        # callback handles it. Set a timeout via a one-shot timer.
        self._verify_timeout = self.create_timer(
            self._reload_grace, self._on_verify_timeout
        )

    def _do_load(self):
        """Attempt to load the model from checkpoint."""
        self._transition(LifecycleState.LOADING, "checkpoint_verified")

        success = False
        try:
            success = self._execute_model_load()
        except Exception as e:
            self.get_logger().error(f'Model load exception: {e}')
            success = False

        if success:
            self._load_time = now()
            self._cycle_number += 1
            self._consecutive_failures = 0
            self._transition(LifecycleState.ACTIVE, "model_loaded")
        else:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._max_failures:
                self._transition(
                    LifecycleState.SAFE_STOPPED,
                    f"max_reload_failures ({self._max_failures})"
                )
                self._trigger_safe_stop("max_reload_failures")
            else:
                self.get_logger().warn(
                    f'Load failed ({self._consecutive_failures}/{self._max_failures}), retrying...'
                )
                self._transition(LifecycleState.RELOADING, "load_failed_retry")
                self._begin_cycle()

    def _do_expire(self, reason: ExpireReason):
        """Expire the current model — destroy state, then reload or stop."""
        if self._state not in (LifecycleState.ACTIVE, LifecycleState.EXPIRING):
            self.get_logger().warn(
                f'Cannot expire in state {self._state.name}'
            )
            return

        self._transition(LifecycleState.EXPIRING, reason.value)

        # Destroy model state — NO STATE CARRIES OVER
        try:
            self._execute_model_destroy()
        except Exception as e:
            self.get_logger().error(f'Model destroy exception: {e}')

        if self._on_expire == "reload":
            self._transition(LifecycleState.RELOADING, "state_destroyed")
            self._begin_cycle()
        else:
            self._transition(LifecycleState.SAFE_STOPPED, "expire_policy_stop")
            self._trigger_safe_stop(reason.value)

    def _trigger_safe_stop(self, reason: str):
        """Request the safe-stop controller to take over."""
        msg = String()
        msg.data = json.dumps({
            "reason": reason,
            "model_name": self._model_name,
            "cycle": self._cycle_number,
            "timestamp": wall_now(),
        })
        self._safe_stop_pub.publish(msg)
        self.get_logger().error(f'SAFE STOP triggered: {reason}')

    # ==================================================================
    # TIMER / TICK
    # ==================================================================

    def _tick(self):
        """Called at countdown_publish_rate — check TTL, publish status."""
        if self._state == LifecycleState.ACTIVE:
            elapsed = now() - self._load_time
            remaining = max(0.0, self._ttl_seconds - elapsed)

            # Publish countdown
            msg = String()
            msg.data = json.dumps({
                "model_name": self._model_name,
                "ttl_remaining_seconds": round(remaining, 1),
                "ttl_total_seconds": self._ttl_seconds,
                "cycle_number": self._cycle_number,
                "elapsed_seconds": round(elapsed, 1),
            })
            self._countdown_pub.publish(msg)

            # TTL expired?
            if remaining <= 0:
                self.get_logger().info(
                    f'TTL expired after {elapsed:.0f}s — triggering apoptosis'
                )
                self._do_expire(ExpireReason.TTL_EXPIRED)

        # Always publish status
        self._publish_status()

    def _publish_status(self):
        msg = String()
        msg.data = json.dumps({
            "state": self._state.name,
            "model_name": self._model_name,
            "cycle_number": self._cycle_number,
            "consecutive_failures": self._consecutive_failures,
        })
        self._status_pub.publish(msg)

    # ==================================================================
    # CALLBACKS
    # ==================================================================

    def _on_verification_result(self, msg: String):
        """Checkpoint registry reports verification result."""
        try:
            data = json.loads(msg.data)
        except json.JSONDecodeError:
            self.get_logger().error('Bad JSON in verification_result')
            return

        # Cancel timeout timer if it exists
        if hasattr(self, '_verify_timeout') and self._verify_timeout is not None:
            self._verify_timeout.cancel()
            self._verify_timeout = None

        if self._state != LifecycleState.VERIFYING:
            return  # Not waiting for verification right now

        if data.get("verified"):
            self._checkpoint_verified = True
            self._checkpoint_hash = data.get("hash", "")
            self._do_load()
        else:
            self.get_logger().error(
                f'Checkpoint verification failed: {data.get("detail")}'
            )
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._max_failures:
                self._transition(
                    LifecycleState.SAFE_STOPPED,
                    "checkpoint_verification_failed"
                )
                self._trigger_safe_stop("checkpoint_verification_failed")
            else:
                # Retry
                self._begin_cycle()

    def _on_verify_timeout(self):
        """No verification response within grace period."""
        if hasattr(self, '_verify_timeout') and self._verify_timeout is not None:
            self._verify_timeout.cancel()
            self._verify_timeout = None

        if self._state == LifecycleState.VERIFYING:
            self.get_logger().error('Checkpoint verification timed out')
            self._transition(
                LifecycleState.SAFE_STOPPED,
                "verification_timeout"
            )
            self._trigger_safe_stop("verification_timeout")

    def _on_force_expire(self, msg: String):
        """Manual expiration trigger (testing / operator intervention)."""
        self.get_logger().warn(f'Manual force expire: {msg.data}')
        self._do_expire(ExpireReason.MANUAL_EXPIRE)

    def _on_drift_alert(self, msg: String):
        """Drift observer detected anomaly — trigger early expiration."""
        if not self._early_expire:
            self.get_logger().info('Drift alert received but early_expire disabled')
            return

        if self._state != LifecycleState.ACTIVE:
            return

        self.get_logger().warn(f'Drift alert — triggering early expiration: {msg.data}')
        self._do_expire(ExpireReason.DRIFT_DETECTED)

    # ==================================================================
    # Properties
    # ==================================================================

    @property
    def state(self) -> LifecycleState:
        return self._state

    @property
    def ttl_remaining(self) -> float:
        if self._state != LifecycleState.ACTIVE:
            return 0.0
        return max(0.0, self._ttl_seconds - (now() - self._load_time))

    @property
    def cycle_number(self) -> int:
        return self._cycle_number


def main(args=None):
    rclpy.init(args=args)
    node = ApoptoticManagerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
