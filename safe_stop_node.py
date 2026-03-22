"""
safe_stop_node — Graceful degradation handler.

If reload fails — network down, corrupted checkpoint, hardware fault — the
robot enters a pre-defined safe-stop mode with operator notification.
The operator must clear the gate before the system can resume.

Stop Types:
    velocity_ramp   — gradually reduce velocity to zero over ramp_down_seconds
    immediate_hold  — freeze in place immediately
    return_home     — navigate to pre-configured home position, then hold

Topics Published:
    ~/safe_stop_status (std_msgs/String)  — current stop state JSON
    ~/operator_alert   (std_msgs/String)  — alert for operator intervention
    ~/velocity_command (std_msgs/String)   — velocity scaling factor [0.0-1.0]

Topics Subscribed:
    ~/trigger         (std_msgs/String)   — trigger safe-stop (from manager)
    ~/operator_clear  (std_msgs/String)   — operator clearance to resume
"""

import json

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from apoptotic_loader.types import StopType, wall_now, now


class SafeStopState:
    IDLE = "IDLE"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    AWAITING_CLEARANCE = "AWAITING_CLEARANCE"
    CLEARED = "CLEARED"


class SafeStopNode(Node):
    """Graceful degradation controller for the apoptotic lifecycle."""

    def __init__(self):
        super().__init__('safe_stop_controller')

        # --- Parameters ---
        self.declare_parameter('stop_type', 'velocity_ramp')
        self.declare_parameter('ramp_down_seconds', 5.0)
        self.declare_parameter('require_operator_clearance', True)
        self.declare_parameter('home_position', [0.0, 0.0, 0.0, 0.0, 0.0, 0.0])

        self._stop_type_str = self.get_parameter('stop_type').get_parameter_value().string_value
        self._ramp_seconds = self.get_parameter('ramp_down_seconds').get_parameter_value().double_value
        self._require_clearance = self.get_parameter('require_operator_clearance').get_parameter_value().bool_value
        self._home_position = self.get_parameter('home_position').get_parameter_value().double_array_value

        try:
            self._stop_type = StopType(self._stop_type_str)
        except ValueError:
            self.get_logger().warn(
                f'Unknown stop_type "{self._stop_type_str}", defaulting to velocity_ramp'
            )
            self._stop_type = StopType.VELOCITY_RAMP

        # --- State ---
        self._state = SafeStopState.IDLE
        self._stop_reason: str = ""
        self._stop_start_time: float = 0.0
        self._ramp_timer = None

        # --- Publishers ---
        self._status_pub = self.create_publisher(String, '~/safe_stop_status', 10)
        self._alert_pub = self.create_publisher(String, '~/operator_alert', 10)
        self._velocity_pub = self.create_publisher(String, '~/velocity_command', 10)

        # --- Subscribers ---
        self._trigger_sub = self.create_subscription(
            String, '~/trigger', self._on_trigger, 10
        )
        self._clear_sub = self.create_subscription(
            String, '~/operator_clear', self._on_operator_clear, 10
        )

        # --- Status timer ---
        self._status_timer = self.create_timer(5.0, self._publish_status)

        self.get_logger().info(
            f'Safe-stop controller initialized: type={self._stop_type.value}, '
            f'ramp={self._ramp_seconds}s, clearance={self._require_clearance}'
        )

    # ==================================================================
    # STOP EXECUTION
    # ==================================================================

    def _on_trigger(self, msg: String):
        """Receive safe-stop trigger from the manager."""
        if self._state in (SafeStopState.STOPPING, SafeStopState.STOPPED,
                           SafeStopState.AWAITING_CLEARANCE):
            self.get_logger().warn('Already in safe-stop — ignoring duplicate trigger')
            return

        try:
            data = json.loads(msg.data)
            self._stop_reason = data.get("reason", "unknown")
        except json.JSONDecodeError:
            self._stop_reason = msg.data or "unknown"

        self.get_logger().error(
            f'SAFE STOP TRIGGERED: {self._stop_reason} (type={self._stop_type.value})'
        )

        self._state = SafeStopState.STOPPING
        self._stop_start_time = now()

        # Send operator alert immediately
        self._send_alert(f"Safe-stop triggered: {self._stop_reason}")

        # Execute stop strategy
        if self._stop_type == StopType.VELOCITY_RAMP:
            self._begin_velocity_ramp()
        elif self._stop_type == StopType.IMMEDIATE_HOLD:
            self._immediate_hold()
        elif self._stop_type == StopType.RETURN_HOME:
            self._return_home()

    def _begin_velocity_ramp(self):
        """Gradually reduce velocity to zero."""
        self._ramp_timer = self.create_timer(0.1, self._ramp_tick)

    def _ramp_tick(self):
        """Called at 10Hz during velocity ramp-down."""
        elapsed = now() - self._stop_start_time
        if elapsed >= self._ramp_seconds:
            # Ramp complete
            self._publish_velocity(0.0)
            if self._ramp_timer:
                self._ramp_timer.cancel()
                self._ramp_timer = None
            self._finalize_stop()
        else:
            # Linear ramp: 1.0 → 0.0 over ramp_down_seconds
            scale = max(0.0, 1.0 - (elapsed / self._ramp_seconds))
            self._publish_velocity(scale)

    def _immediate_hold(self):
        """Freeze in place immediately."""
        self._publish_velocity(0.0)
        self._finalize_stop()

    def _return_home(self):
        """
        Navigate to home position then hold.
        In production, this would interface with the motion planner.
        For now, publish the home position command and finalize.
        """
        self.get_logger().info(f'Return-home commanded: {self._home_position}')
        # Publish home position as velocity command with metadata
        msg = String()
        msg.data = json.dumps({
            "command": "return_home",
            "target_position": list(self._home_position),
            "timestamp": wall_now(),
        })
        self._velocity_pub.publish(msg)
        # Finalize immediately (in production, wait for arrival confirmation)
        self._finalize_stop()

    def _finalize_stop(self):
        """Mark the stop as complete, enter clearance gate."""
        self._state = SafeStopState.STOPPED
        self.get_logger().warn('Robot stopped.')

        if self._require_clearance:
            self._state = SafeStopState.AWAITING_CLEARANCE
            self._send_alert(
                "Robot stopped — operator clearance required to resume"
            )
            self.get_logger().warn('Awaiting operator clearance...')
        else:
            self._state = SafeStopState.CLEARED
            self.get_logger().info('No clearance required — cleared automatically')

    # ==================================================================
    # OPERATOR CLEARANCE
    # ==================================================================

    def _on_operator_clear(self, msg: String):
        """Operator provides clearance to resume."""
        if self._state != SafeStopState.AWAITING_CLEARANCE:
            self.get_logger().warn(
                f'Clearance received but state is {self._state} — ignoring'
            )
            return

        self.get_logger().info(f'Operator clearance received: {msg.data}')
        self._state = SafeStopState.CLEARED
        self._send_alert("Operator clearance granted — system may resume")

    @property
    def is_cleared(self) -> bool:
        """Check if the system is cleared to resume operations."""
        return self._state in (SafeStopState.IDLE, SafeStopState.CLEARED)

    def reset(self):
        """Reset to idle state (called by manager after successful reload)."""
        self._state = SafeStopState.IDLE
        self._stop_reason = ""
        self._publish_velocity(1.0)

    # ==================================================================
    # PUBLISHING
    # ==================================================================

    def _publish_velocity(self, scale: float):
        """Publish velocity scaling factor (0.0 = stopped, 1.0 = full)."""
        msg = String()
        msg.data = json.dumps({
            "velocity_scale": round(scale, 3),
            "timestamp": wall_now(),
        })
        self._velocity_pub.publish(msg)

    def _send_alert(self, message: str):
        """Publish operator alert."""
        msg = String()
        msg.data = json.dumps({
            "alert": message,
            "stop_reason": self._stop_reason,
            "stop_type": self._stop_type.value,
            "state": self._state,
            "timestamp": wall_now(),
        })
        self._alert_pub.publish(msg)
        self.get_logger().warn(f'OPERATOR ALERT: {message}')

    def _publish_status(self):
        msg = String()
        msg.data = json.dumps({
            "state": self._state,
            "stop_type": self._stop_type.value,
            "stop_reason": self._stop_reason,
            "require_clearance": self._require_clearance,
            "is_cleared": self.is_cleared,
        })
        self._status_pub.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = SafeStopNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
