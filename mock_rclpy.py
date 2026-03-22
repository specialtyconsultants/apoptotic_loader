"""
Mock rclpy module for unit testing without a ROS 2 installation.

Provides just enough of the rclpy API surface to instantiate and test
the apoptotic_loader nodes' logic (state machine, KL divergence, etc.)
without requiring a ROS 2 runtime.
"""

import json
from unittest.mock import MagicMock

# ── Global state ──────────────────────────────────────────────────────

_initialized = False
_shutdown = False


def init(args=None):
    global _initialized, _shutdown
    _initialized = True
    _shutdown = False


def shutdown():
    global _initialized, _shutdown
    _initialized = False
    _shutdown = True


def spin(node):
    """No-op spin for testing."""
    pass


def spin_once(node, timeout_sec=None):
    """No-op spin_once for testing."""
    pass


# ── Parameter classes ─────────────────────────────────────────────────

class ParameterValue:
    def __init__(self, value):
        self._value = value

    @property
    def string_value(self):
        return str(self._value) if not isinstance(self._value, str) else self._value

    @property
    def integer_value(self):
        return int(self._value)

    @property
    def double_value(self):
        return float(self._value)

    @property
    def bool_value(self):
        return bool(self._value)

    @property
    def double_array_value(self):
        if isinstance(self._value, (list, tuple)):
            return [float(v) for v in self._value]
        return [0.0]


class Parameter:
    def __init__(self, name, value):
        self._name = name
        self._value = ParameterValue(value)

    def get_parameter_value(self):
        return self._value


# ── Logger ────────────────────────────────────────────────────────────

class MockLogger:
    def __init__(self, name='mock'):
        self._name = name
        self.messages = []  # Capture for assertions

    def _log(self, level, msg):
        self.messages.append((level, msg))

    def info(self, msg):    self._log('INFO', msg)
    def warn(self, msg):    self._log('WARN', msg)
    def error(self, msg):   self._log('ERROR', msg)
    def debug(self, msg):   self._log('DEBUG', msg)
    def fatal(self, msg):   self._log('FATAL', msg)


# ── Publisher / Subscription ──────────────────────────────────────────

class MockPublisher:
    def __init__(self, msg_type, topic, qos):
        self.msg_type = msg_type
        self.topic = topic
        self.published = []  # Capture published messages

    def publish(self, msg):
        self.published.append(msg)


class MockSubscription:
    def __init__(self, msg_type, topic, callback, qos):
        self.msg_type = msg_type
        self.topic = topic
        self.callback = callback


class MockTimer:
    def __init__(self, period, callback):
        self.period = period
        self.callback = callback
        self.cancelled = False

    def cancel(self):
        self.cancelled = True


# ── Node base class ───────────────────────────────────────────────────

class _NodeBase:
    """
    Mock Node that mirrors rclpy.node.Node's interface closely enough
    for the apoptotic_loader nodes to instantiate.
    """

    def __init__(self, node_name, **kwargs):
        self._node_name = node_name
        self._parameters = {}
        self._publishers = {}
        self._subscriptions = {}
        self._timers = []
        self._logger = MockLogger(node_name)

    def get_logger(self):
        return self._logger

    def declare_parameter(self, name, default_value=None):
        if name not in self._parameters:
            self._parameters[name] = Parameter(name, default_value)

    def get_parameter(self, name):
        return self._parameters.get(name, Parameter(name, ''))

    def set_parameter(self, name, value):
        """Test helper — set a parameter value."""
        self._parameters[name] = Parameter(name, value)

    def create_publisher(self, msg_type, topic, qos):
        pub = MockPublisher(msg_type, topic, qos)
        self._publishers[topic] = pub
        return pub

    def create_subscription(self, msg_type, topic, callback, qos):
        sub = MockSubscription(msg_type, topic, callback, qos)
        self._subscriptions[topic] = sub
        return sub

    def create_timer(self, period, callback):
        timer = MockTimer(period, callback)
        self._timers.append(timer)
        return timer

    def destroy_node(self):
        pass

    # ── Test helpers ──────────────────────────────────────────────
    def get_publisher(self, topic_suffix: str) -> MockPublisher | None:
        """Find a publisher by partial topic match."""
        for topic, pub in self._publishers.items():
            if topic_suffix in topic:
                return pub
        return None

    def get_subscription(self, topic_suffix: str) -> MockSubscription | None:
        """Find a subscription by partial topic match."""
        for topic, sub in self._subscriptions.items():
            if topic_suffix in topic:
                return sub
        return None

    def inject_message(self, topic_suffix: str, data: str):
        """Simulate receiving a message on a subscription."""
        from std_msgs.msg import String
        sub = self.get_subscription(topic_suffix)
        if sub:
            msg = String()
            msg.data = data
            sub.callback(msg)


# ── Module-level Node class ───────────────────────────────────────────

class _NodeModule:
    """Provides rclpy.node.Node."""
    Node = _NodeBase


node = _NodeModule()
