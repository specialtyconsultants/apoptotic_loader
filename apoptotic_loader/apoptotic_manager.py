"""
Apoptotic Manager Node
======================
Core lifecycle controller for Apoptotic Model Loading.
Craig McClurkin / Specialty Consultants
Apache-2.0 — craig.mcclurkin@louisville.edu
"""

import rclpy
from rclpy.node import Node
from std_msgs.msg import String, Int32
import gc
# import torch  # Commented out for lightweight simulation/testing without GPU

class ApoptoticManagerNode(Node):
    """
    Core lifecycle controller for Apoptotic Model Loading.

    State machine: UNLOADED -> VERIFYING -> LOADING -> ACTIVE -> EXPIRING -> RELOADING

    Enforces the Time-To-Live (TTL) and handles state destruction.
    Every 24 hours (configurable), the model state is destroyed and reloaded
    from a cryptographically verified checkpoint.
    """

    STATES = ["UNLOADED", "VERIFYING", "LOADING", "ACTIVE", "EXPIRING", "RELOADING"]

    def __init__(self):
        super().__init__('apoptotic_manager')

        # ── Parameters ────────────────────────────────────────────────────────
        self.declare_parameter('ttl_seconds', 86400)          # Default: 24h
        self.declare_parameter('kl_threshold', 0.05)          # Drift trigger
        self.declare_parameter('early_expire_on_drift', True)
        self.declare_parameter('stop_type', 'velocity_ramp')

        self.ttl_seconds = self.get_parameter('ttl_seconds').value
        self.kl_threshold = self.get_parameter('kl_threshold').value
        self.current_ttl = self.ttl_seconds
        self.state = "UNLOADED"

        # ── Publishers ─────────────────────────────────────────────────────────
        self.ttl_pub    = self.create_publisher(Int32,  '~/ttl_countdown',  10)
        self.status_pub = self.create_publisher(String, '~/model_status',   10)
        self.event_pub  = self.create_publisher(String, '~/lifecycle_event', 10)

        # ── Subscribers ────────────────────────────────────────────────────────
        self.force_expire_sub = self.create_subscription(
            String, '~/force_expire', self.force_expire_callback, 10)

        self.drift_alert_sub = self.create_subscription(
            String, '/drift_observer/drift_alert', self.drift_alert_callback, 10)

        # ── Timers ─────────────────────────────────────────────────────────────
        self.timer = self.create_timer(1.0, self.countdown_step)

        # ── Initial Load ───────────────────────────────────────────────────────
        self.model = None
        self.get_logger().info('╔══════════════════════════════════════════╗')
        self.get_logger().info('║   APOPTOTIC MODEL LOADER — v1.0.0        ║')
        self.get_logger().info('║   Specialty Consultants / Craig McClurkin║')
        self.get_logger().info('╚══════════════════════════════════════════╝')
        self.get_logger().info(f'TTL configured: {self.ttl_seconds}s | KL threshold: {self.kl_threshold}')
        self._set_state("VERIFYING")
        self._execute_model_load()

    # ── State Machine ──────────────────────────────────────────────────────────

    def _set_state(self, new_state: str):
        self.state = new_state
        msg = String()
        msg.data = new_state
        self.status_pub.publish(msg)
        self.event_pub.publish(String(data=f"STATE_TRANSITION:{new_state}"))
        self.get_logger().info(f'[STATE] → {new_state}')

    # ── TTL Countdown ──────────────────────────────────────────────────────────

    def countdown_step(self):
        if self.state == "ACTIVE":
            if self.current_ttl > 0:
                self.current_ttl -= 1
                msg = Int32()
                msg.data = self.current_ttl
                self.ttl_pub.publish(msg)
                # Log every hour (3600s) and last 60 seconds
                if self.current_ttl % 3600 == 0 or self.current_ttl <= 60:
                    hours = self.current_ttl // 3600
                    mins  = (self.current_ttl % 3600) // 60
                    secs  = self.current_ttl % 60
                    self.get_logger().info(f'TTL remaining: {hours:02d}:{mins:02d}:{secs:02d}')
            else:
                self.get_logger().warn('⚠  TTL EXPIRED — executing programmed apoptosis...')
                self._trigger_apoptosis(reason="TTL_EXPIRED")

    # ── Callbacks ──────────────────────────────────────────────────────────────

    def force_expire_callback(self, msg):
        self.get_logger().warn(f'⚡ Manual override received: "{msg.data}" — triggering immediate apoptosis.')
        self._trigger_apoptosis(reason=f"MANUAL_OVERRIDE:{msg.data}")

    def drift_alert_callback(self, msg):
        early_expire = self.get_parameter('early_expire_on_drift').value
        if early_expire:
            self.get_logger().warn(f'📡 Drift alert received: {msg.data} — triggering early apoptosis.')
            self._trigger_apoptosis(reason=f"DRIFT_TRIGGERED:{msg.data}")

    # ── Core Apoptosis Sequence ────────────────────────────────────────────────

    def _trigger_apoptosis(self, reason: str = "TTL_EXPIRED"):
        """Coordinates the cell death and rebirth sequence."""
        self._set_state("EXPIRING")
        self.event_pub.publish(String(data=f"APOPTOSIS_TRIGGERED:{reason}"))
        self.get_logger().warn(f'☠  Apoptosis triggered — reason: {reason}')

        self._execute_model_destroy()

        self.get_logger().info('🔄 Model state cleared. Requesting verified checkpoint reload...')
        self._set_state("RELOADING")
        success = self._execute_model_load()

        if success:
            self.current_ttl = self.ttl_seconds  # Reset the clock
            self.get_logger().info(f'✅ Reload complete. TTL reset to {self.ttl_seconds}s.')
        else:
            self.get_logger().error('❌ Reload FAILED — entering safe-stop mode.')
            self._set_state("UNLOADED")
            self.event_pub.publish(String(data="SAFE_STOP_REQUESTED"))

    # ── Integration Hooks (override these in subclasses) ──────────────────────

    def _execute_model_load(self) -> bool:
        """
        Load your model here from the Checkpoint Registry Node.
        Override in subclass for real model loading (PyTorch, TensorRT, GR00T, etc.)
        """
        self._set_state("LOADING")
        self.get_logger().info('📦 Simulating load from cryptographically verified checkpoint...')
        # Real implementation:
        # self.model = torch.load('/opt/apoptotic/checkpoints/my_model.pt')
        self.model = "ACTIVE_MOCK_MODEL_v1.0"
        self._set_state("ACTIVE")
        self.status_pub.publish(String(data="LOADED_AND_VERIFIED"))
        self.get_logger().info('✅ Model loaded and verified. Lifecycle clock started.')
        return True

    def _execute_model_destroy(self):
        """
        Destroy your model state here. NO STATE CARRIES OVER.
        Override in subclass for real cleanup (VRAM flush, etc.)
        """
        self.get_logger().info('🔥 Executing programmed cell death...')
        if self.model is not None:
            del self.model
            self.model = None
        # Real implementation:
        # torch.cuda.empty_cache()
        gc.collect()
        self.status_pub.publish(String(data="DESTROYED_CLEANLY"))
        self.get_logger().info('✅ Model state destroyed cleanly.')


def main(args=None):
    rclpy.init(args=args)
    node = ApoptoticManagerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info('Apoptotic Manager shutting down gracefully.')
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
