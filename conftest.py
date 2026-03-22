"""
Pytest conftest — patches rclpy and std_msgs with mocks before node imports.

This allows all apoptotic_loader nodes to be tested without ROS 2 installed.
"""

import sys
import os

# Ensure the test directory is on the path
TEST_DIR = os.path.dirname(__file__)
sys.path.insert(0, TEST_DIR)

# Patch rclpy and std_msgs BEFORE any node code imports them
import mock_rclpy
import mock_std_msgs

# Create mock module hierarchy
class _StdMsgsPackage:
    msg = mock_std_msgs

sys.modules['rclpy'] = mock_rclpy
sys.modules['rclpy.node'] = mock_rclpy.node
sys.modules['std_msgs'] = _StdMsgsPackage
sys.modules['std_msgs.msg'] = mock_std_msgs
sys.modules['std_srvs'] = type(sys)('std_srvs')  # empty stub

# Also ensure the package root is importable
PACKAGE_DIR = os.path.dirname(TEST_DIR)
sys.path.insert(0, PACKAGE_DIR)
