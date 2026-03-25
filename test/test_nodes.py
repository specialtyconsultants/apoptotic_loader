import pytest
import rclpy
from rclpy.node import Node

# Import your nodes
from apoptotic_loader.apoptotic_manager import ApoptoticManagerNode
from apoptotic_loader.checkpoint_registry import CheckpointRegistryNode
from apoptotic_loader.drift_observer import DriftObserverNode
from apoptotic_loader.safe_stop_controller import SafeStopControllerNode

@pytest.fixture(scope="module")
def ros_init():
    """Initialize the ROS 2 context for the test module."""
    rclpy.init()
    yield
    rclpy.shutdown()

def test_apoptotic_manager_init(ros_init):
    """Test that the core manager initializes and loads parameters."""
    node = ApoptoticManagerNode()
    assert node.state == "ACTIVE" or node.state == "VERIFYING", "Node should enter an active or verifying state on boot."
    assert node.ttl_seconds > 0, "TTL parameter not loaded correctly."
    node.destroy_node()

def test_checkpoint_registry_init(ros_init):
    """Test that the registry loads the mock database."""
    node = CheckpointRegistryNode()
    assert "mock_model_v1.0" in node.registry, "Mock registry failed to load."
    node.destroy_node()

def test_drift_observer_init(ros_init):
    """Test that the observer initializes with the correct baseline."""
    node = DriftObserverNode()
    assert len(node.baseline_distribution) == 10, "Baseline distribution not initialized."
    assert node.kl_threshold > 0, "KL Threshold parameter not loaded."
    node.destroy_node()

def test_safe_stop_controller_init(ros_init):
    """Test that the safe stop controller boots without triggering a stop."""
    node = SafeStopControllerNode()
    assert node.is_stopped is False, "Controller should not boot in a stopped state."
    node.destroy_node()
