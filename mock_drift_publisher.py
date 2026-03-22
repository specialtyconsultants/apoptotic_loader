'''Instructions for Claude: Place this script in your ROS 2 workspace
(e.g., ~/ros2_ws/src/apoptotic_loader/scripts/). Make it executable
(chmod +x mock_drift_publisher.py). Run this in a separate terminal while 
the main apoptotic_stack is active. It will gradually increase the simulated
Kullback-Leibler divergence until it intentionally breaches the kl_threshold 
to trigger an early apoptotic reset'''

#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from std_msgs.msg import Float64

class MockDriftPublisher(Node):
    """
    Simulates the behavioral divergence tracking of a physical AI model.
    Gradually increases KL Divergence to test the Apoptotic Manager's 
    early expiration and safe-stop triggers.
    """
    def __init__(self):
        super().__init__('mock_drift_publisher')
        
        # Publishing to the metric topic monitored by the drift_observer
        self.publisher_ = self.create_publisher(Float64, '/drift_observer/kl_metric', 10)
        
        # Publish every 2 seconds
        self.timer = self.create_timer(2.0, self.publish_mock_drift) 
        
        # Initialize at a healthy baseline
        self.current_kl = 0.001 
        
        # Default sensitive threshold from config/default.yaml
        self.kl_threshold = 0.01 

    def publish_mock_drift(self):
        msg = Float64()
        msg.data = self.current_kl
        self.publisher_.publish(msg)
        self.get_logger().info(f'Publishing Simulated KL Divergence: {self.current_kl:.4f}')

        # Simulate gradual contextual degradation (sensor noise/hallucination)
        self.current_kl += 0.002 

        if self.current_kl >= self.kl_threshold:
            self.get_logger().warn(
                f'CRITICAL: KL Divergence ({self.current_kl:.4f}) breached threshold ({self.kl_threshold}). '
                'Drift Observer should now broadcast to ~/drift_alert and trigger Apoptosis.'
            )

def main(args=None):
    rclpy.init(args=args)
    node = MockDriftPublisher()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info('Mock drift injection terminated.')
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
