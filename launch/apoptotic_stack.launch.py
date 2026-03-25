"""
Apoptotic Stack Launch File
============================
Launches all four nodes: checkpoint_registry, apoptotic_manager,
drift_observer, safe_stop_controller.
Craig McClurkin / Specialty Consultants — Apache-2.0
"""

import os
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    pkg_share = get_package_share_directory('apoptotic_loader')
    config_file = os.path.join(pkg_share, 'config', 'default.yaml')

    # ── Launch Arguments ───────────────────────────────────────────────────────
    ttl_arg = DeclareLaunchArgument(
        'ttl_hours',
        default_value='24',
        description='Time-to-live in hours for each model instance'
    )
    model_arg = DeclareLaunchArgument(
        'model_name',
        default_value='mock_model_v1.0',
        description='Model ID to load from the checkpoint registry'
    )
    kl_arg = DeclareLaunchArgument(
        'kl_threshold',
        default_value='0.05',
        description='KL Divergence threshold for drift-triggered early expiration'
    )
    stop_arg = DeclareLaunchArgument(
        'stop_type',
        default_value='velocity_ramp',
        description='Safe stop behavior: velocity_ramp | immediate_hold | return_home'
    )

    # ── Nodes ──────────────────────────────────────────────────────────────────
    checkpoint_registry_node = Node(
        package='apoptotic_loader',
        executable='checkpoint_registry',
        name='checkpoint_registry',
        output='screen',
        parameters=[config_file]
    )

    apoptotic_manager_node = Node(
        package='apoptotic_loader',
        executable='apoptotic_manager',
        name='apoptotic_manager',
        output='screen',
        parameters=[
            config_file,
            {'kl_threshold': LaunchConfiguration('kl_threshold')},
            {'stop_type': LaunchConfiguration('stop_type')},
        ]
    )

    drift_observer_node = Node(
        package='apoptotic_loader',
        executable='drift_observer',
        name='drift_observer',
        output='screen',
        parameters=[
            config_file,
            {'kl_threshold': LaunchConfiguration('kl_threshold')},
        ]
    )

    safe_stop_node = Node(
        package='apoptotic_loader',
        executable='safe_stop_controller',
        name='safe_stop_controller',
        output='screen',
        parameters=[
            config_file,
            {'stop_type': LaunchConfiguration('stop_type')},
        ]
    )

    return LaunchDescription([
        ttl_arg,
        model_arg,
        kl_arg,
        stop_arg,
        checkpoint_registry_node,
        apoptotic_manager_node,
        drift_observer_node,
        safe_stop_node,
    ])
