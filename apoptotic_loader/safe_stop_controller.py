"""
Safe Stop Controller Node
=========================
Graceful degradation handler with velocity ramp-down, operator notification,
and clearance gate.
Craig McClurkin / Specialty Consultants — Apache-2.0
"""

import rclpy
from rclpy.node import Node
from std_msgs.msg import String, Float64
import time


class SafeStopControllerNode(Node):
    """
    Handles graceful degradation when:
      - Apoptotic reload fails
      - Drift threshold exceeded and early_expire disabled
      - Hardware fault detected
    
    Stop types:
      velocity_ramp    — gradually reduce velocity to zero
      immediate_hold   — stop all motion immediately
      return_home      — navigate to home position then stop
    """

    def __init__(self):
        super().__init__('safe_stop_controller')

        # ── Parameters ────────────────────────────────────────────────────────
        self.declare_parameter('stop_type', 'velocity_ramp')
        self.declare_parameter('ramp_duration_seconds', 5.0)
        self.stop_type = self.get_parameter('stop_type').value

        # ── Publishers ─────────────────────────────────────────────────────────
        self.status_pub   = self.create_publisher(String,  '~/safe_stop_status', 10)
        self.alert_pub    = self.create_publisher(String,  '~/operator_alert',   10)
        self.velocity_pub = self.create_publisher(Float64, '~/velocity_command', 10)

        # ── Subscribers ────────────────────────────────────────────────────────
        self.lifecycle_sub = self.create_subscription(
            String, '/apoptotic_manager/lifecycle_event', self.lifecycle_callback, 10)
        self.clearance_sub = self.create_subscription(
            String, '~/operator_clearance', self.clearance_callback, 10)

        # ── State ──────────────────────────────────────────────────────────────
        self.is_stopped = False
        self.awaiting_clearance = False
        self.current_velocity = 1.0  # Normalized 0.0 - 1.0

        self.get_logger().info(f'Safe Stop Controller initialized. Stop type: {self.stop_type}')

    def lifecycle_callback(self, msg):
        event = msg.data
        if "SAFE_STOP_REQUESTED" in event or "APOPTOSIS_TRIGGERED" in event:
            if not self.is_stopped:
                self.get_logger().warn(f'🛑 Safe stop triggered by lifecycle event: {event}')
                self._execute_safe_stop(reason=event)

    def clearance_callback(self, msg):
        if msg.data.upper() in ("CLEAR", "RESUME", "OK"):
            self.get_logger().info(f'✅ Operator clearance received: {msg.data}')
            self._resume_operations()
        else:
            self.get_logger().warn(f'Unrecognized clearance command: {msg.data}')

    def _execute_safe_stop(self, reason: str = "UNKNOWN"):
        self.is_stopped = True
        self.awaiting_clearance = True

        stop_type = self.get_parameter('stop_type').value
        self.get_logger().warn(f'Executing safe stop — type: {stop_type} — reason: {reason}')

        if stop_type == 'velocity_ramp':
            self._velocity_ramp_down()
        elif stop_type == 'immediate_hold':
            self._immediate_hold()
        elif stop_type == 'return_home':
            self._return_home()

        # Notify operator
        alert = String()
        alert.data = f"SAFE_STOP_ACTIVE|reason:{reason}|type:{stop_type}|awaiting_clearance:true"
        self.alert_pub.publish(alert)
        self.get_logger().warn('📢 Operator alert published. Awaiting clearance to resume.')

    def _velocity_ramp_down(self):
        """Simulate gradual velocity reduction."""
        ramp_steps = 5
        for i in range(ramp_steps, 0, -1):
            v = i / ramp_steps
            msg = Float64()
            msg.data = v
            self.velocity_pub.publish(msg)
            self.get_logger().info(f'Velocity ramp: {v:.1f}')
        # Final stop
        self.velocity_pub.publish(Float64(data=0.0))
        self.status_pub.publish(String(data="SAFE_STOP:VELOCITY_RAMP_COMPLETE"))
        self.get_logger().info('✅ Velocity ramp-down complete. Robot at rest.')

    def _immediate_hold(self):
        self.velocity_pub.publish(Float64(data=0.0))
        self.status_pub.publish(String(data="SAFE_STOP:IMMEDIATE_HOLD"))
        self.get_logger().warn('⛔ Immediate hold — all motion stopped.')

    def _return_home(self):
        self.get_logger().info('🏠 Navigating to home position...')
        self.status_pub.publish(String(data="SAFE_STOP:RETURNING_HOME"))
        # In production: publish navigation goal to home coordinates
        self.velocity_pub.publish(Float64(data=0.0))
        self.status_pub.publish(String(data="SAFE_STOP:AT_HOME"))

    def _resume_operations(self):
        self.is_stopped = False
        self.awaiting_clearance = False
        self.current_velocity = 1.0
        self.status_pub.publish(String(data="OPERATIONS_RESUMED"))
        self.get_logger().info('▶  Operations resumed after operator clearance.')


def main(args=None):
    rclpy.init(args=args)
    node = SafeStopControllerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info('Safe Stop Controller shutting down gracefully.')
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
