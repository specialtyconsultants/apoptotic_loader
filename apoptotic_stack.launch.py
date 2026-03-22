"""
apoptotic_stack.launch.py — Launch all four apoptotic loader nodes.

Usage:
    ros2 launch apoptotic_loader apoptotic_stack.launch.py
    ros2 launch apoptotic_loader apoptotic_stack.launch.py model_name:=welding_arm ttl_hours:=24

Arguments:
    model_name   — identifier for the model (default: default_model)
    ttl_hours    — time-to-live in hours (default: 24, converted to seconds)
    config_file  — path to YAML config (default: package share/config/default.yaml)
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    pkg_share = get_package_share_directory('apoptotic_loader')
    default_config = os.path.join(pkg_share, 'config', 'default.yaml')

    # --- Launch Arguments ---
    model_name_arg = DeclareLaunchArgument(
        'model_name', default_value='default_model',
        description='Model identifier'
    )
    ttl_hours_arg = DeclareLaunchArgument(
        'ttl_hours', default_value='24',
        description='Time-to-live in hours (converted to seconds internally)'
    )
    config_file_arg = DeclareLaunchArgument(
        'config_file', default_value=default_config,
        description='Path to YAML configuration file'
    )

    config = LaunchConfiguration('config_file')

    # --- Nodes ---
    checkpoint_registry = Node(
        package='apoptotic_loader',
        executable='checkpoint_registry_node',
        name='checkpoint_registry',
        parameters=[config],
        output='screen',
    )

    apoptotic_manager = Node(
        package='apoptotic_loader',
        executable='apoptotic_manager_node',
        name='apoptotic_manager',
        parameters=[config, {
            'model_name': LaunchConfiguration('model_name'),
        }],
        output='screen',
    )

    drift_observer = Node(
        package='apoptotic_loader',
        executable='drift_observer_node',
        name='drift_observer',
        parameters=[config],
        output='screen',
    )

    safe_stop = Node(
        package='apoptotic_loader',
        executable='safe_stop_node',
        name='safe_stop_controller',
        parameters=[config],
        output='screen',
    )

    return LaunchDescription([
        model_name_arg,
        ttl_hours_arg,
        config_file_arg,
        checkpoint_registry,
        apoptotic_manager,
        drift_observer,
        safe_stop,
    ])
