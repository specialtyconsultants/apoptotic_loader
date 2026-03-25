"""
Drift Observer Node
===================
Monitors behavioral divergence using KL Divergence.
Triggers early model expiration if drift exceeds threshold.
Craig McClurkin / Specialty Consultants — Apache-2.0
"""

import rclpy
from rclpy.node import Node
from std_msgs.msg import String, Float64
import math
import random
import time


class DriftObserverNode(Node):
    """
    Lightweight behavioral observer.
    Computes KL Divergence between baseline and current output distribution.

    D_KL(P || Q) = sum_x P(x) * log(P(x) / Q(x))

    Publishes drift reports and triggers early expiration when threshold exceeded.
    """

    def __init__(self):
        super().__init__('drift_observer')

        # ── Parameters ────────────────────────────────────────────────────────
        self.declare_parameter('kl_threshold', 0.05)
        self.declare_parameter('sample_rate', 100)         # Check every N inferences
        self.declare_parameter('early_expire_on_drift', True)

        self.kl_threshold = self.get_parameter('kl_threshold').value
        self.sample_rate  = self.get_parameter('sample_rate').value

        # ── Publishers ─────────────────────────────────────────────────────────
        self.drift_report_pub = self.create_publisher(Float64, '~/drift_report', 10)
        self.drift_alert_pub  = self.create_publisher(String,  '~/drift_alert',  10)

        # ── Subscribers ────────────────────────────────────────────────────────
        self.model_status_sub = self.create_subscription(
            String, '/apoptotic_manager/model_status', self.model_status_callback, 10)

        # ── State ──────────────────────────────────────────────────────────────
        self.baseline_distribution = None
        self.inference_count = 0
        self.is_monitoring = False

        # Simulate baseline: uniform-ish distribution over 10 output classes
        self.baseline_distribution = [0.1] * 10

        # ── Simulation Timer (fires every 5s to simulate inference stream) ────
        self.sim_timer = self.create_timer(5.0, self.simulate_inference_check)

        self.get_logger().info('Drift Observer initialized.')
        self.get_logger().info(f'KL threshold: {self.kl_threshold} | Sample rate: every {self.sample_rate} inferences')

    def model_status_callback(self, msg):
        if msg.data == "LOADED_AND_VERIFIED":
            self.is_monitoring = True
            self.inference_count = 0
            self.get_logger().info('🔍 Model loaded — drift monitoring ACTIVE.')
        elif msg.data in ("DESTROYED_CLEANLY", "UNLOADED"):
            self.is_monitoring = False
            self.get_logger().info('⏸  Model destroyed — drift monitoring PAUSED.')

    def kl_divergence(self, p: list, q: list) -> float:
        """
        Compute KL Divergence D_KL(P || Q).
        P = baseline (true reference distribution)
        Q = current live distribution
        """
        eps = 1e-10  # Prevent log(0)
        kl = 0.0
        for px, qx in zip(p, q):
            if px > 0:
                kl += px * math.log((px + eps) / (qx + eps))
        return kl

    def simulate_inference_check(self):
        """
        Simulate an inference check by generating a slightly perturbed distribution
        and computing KL divergence from baseline.
        In production, replace with actual model output distribution sampling.
        """
        if not self.is_monitoring:
            return

        self.inference_count += self.sample_rate

        # Simulate a slightly drifting distribution (random walk)
        drift_factor = random.uniform(0.0, 0.08)  # Simulate slow drift
        current_dist = [
            max(0.001, b + random.uniform(-drift_factor, drift_factor))
            for b in self.baseline_distribution
        ]
        # Normalize to sum to 1
        total = sum(current_dist)
        current_dist = [x / total for x in current_dist]

        kl = self.kl_divergence(self.baseline_distribution, current_dist)

        # Publish drift report
        msg = Float64()
        msg.data = kl
        self.drift_report_pub.publish(msg)

        status = "🟢 NORMAL" if kl < self.kl_threshold else "🔴 DRIFT ALERT"
        self.get_logger().info(
            f'[Drift Check #{self.inference_count}] KL={kl:.6f} | Threshold={self.kl_threshold} | {status}'
        )

        if kl >= self.kl_threshold:
            early_expire = self.get_parameter('early_expire_on_drift').value
            if early_expire:
                alert = String()
                alert.data = f"KL_DIVERGENCE:{kl:.6f}:THRESHOLD:{self.kl_threshold}"
                self.drift_alert_pub.publish(alert)
                self.get_logger().warn(
                    f'⚠  KL divergence {kl:.6f} ≥ threshold {self.kl_threshold} — drift alert published!'
                )


def main(args=None):
    rclpy.init(args=args)
    node = DriftObserverNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info('Drift Observer shutting down gracefully.')
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
