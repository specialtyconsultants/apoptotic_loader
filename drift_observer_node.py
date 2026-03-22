"""
drift_observer_node — Behavioral divergence tracking.

A lightweight observer that monitors the model's output distribution,
comparing against the checkpoint baseline. Anomalies trigger early
expiration via the drift_alert topic.

Drift Detection Methods:
    1. KL Divergence — core metric comparing current vs baseline distribution
    2. Entropy Ratio — detects distribution collapse or explosion
    3. Latency Anomaly — flags inference time spikes (hardware/model issues)

Topics Published:
    ~/drift_report  (std_msgs/String)  — periodic drift metrics JSON
    ~/drift_alert   (std_msgs/String)  — alert when threshold exceeded

Topics Subscribed:
    ~/inference_output (std_msgs/String) — model output samples (JSON)
    ~/reset_baseline   (std_msgs/String) — reset baseline (on new model load)
"""

import json
import math
from collections import deque

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from apoptotic_loader.types import DriftReport, wall_now


class DriftObserverNode(Node):
    """
    Monitor model output distributions for behavioral drift.

    Accepts inference output samples via ~/inference_output and computes
    KL divergence against the recorded baseline distribution.
    """

    def __init__(self):
        super().__init__('drift_observer')

        # --- Parameters ---
        self.declare_parameter('kl_threshold', 0.05)
        self.declare_parameter('sample_rate', 100)
        self.declare_parameter('early_expire', True)
        self.declare_parameter('entropy_ratio_threshold', 1.5)
        self.declare_parameter('latency_anomaly_multiplier', 3.0)
        self.declare_parameter('baseline_window_size', 1000)
        self.declare_parameter('drift_report_interval', 60.0)

        self._kl_threshold = self.get_parameter('kl_threshold').get_parameter_value().double_value
        self._sample_rate = self.get_parameter('sample_rate').get_parameter_value().integer_value
        self._early_expire = self.get_parameter('early_expire').get_parameter_value().bool_value
        self._entropy_threshold = self.get_parameter('entropy_ratio_threshold').get_parameter_value().double_value
        self._latency_multiplier = self.get_parameter('latency_anomaly_multiplier').get_parameter_value().double_value
        self._window_size = self.get_parameter('baseline_window_size').get_parameter_value().integer_value
        self._report_interval = self.get_parameter('drift_report_interval').get_parameter_value().double_value

        # --- State ---
        self._baseline_distribution: dict[str, float] = {}
        self._current_distribution: dict[str, float] = {}
        self._sample_count: int = 0
        self._total_samples: int = 0
        self._latencies: deque = deque(maxlen=self._window_size)
        self._baseline_latency_mean: float = 0.0
        self._baseline_latency_set: bool = False
        self._latest_report = DriftReport()

        # --- Publishers ---
        self._report_pub = self.create_publisher(String, '~/drift_report', 10)
        self._alert_pub = self.create_publisher(String, '~/drift_alert', 10)

        # --- Subscribers ---
        self._output_sub = self.create_subscription(
            String, '~/inference_output', self._on_inference_output, 10
        )
        self._reset_sub = self.create_subscription(
            String, '~/reset_baseline', self._on_reset_baseline, 10
        )

        # --- Timers ---
        self._report_timer = self.create_timer(
            self._report_interval, self._publish_report
        )

        self.get_logger().info(
            f'Drift observer initialized: kl_threshold={self._kl_threshold}, '
            f'sample_rate={self._sample_rate}'
        )

    # ==================================================================
    # CORE MATH
    # ==================================================================

    @staticmethod
    def kl_divergence(p: dict[str, float], q: dict[str, float],
                      epsilon: float = 1e-10) -> float:
        """
        Compute KL divergence D_KL(P || Q) for discrete distributions.

        D_KL(P || Q) = Σ P(x) · log(P(x) / Q(x))

        P is the baseline (truth), Q is the current (approximation).
        Uses epsilon smoothing to avoid log(0).
        """
        all_keys = set(p.keys()) | set(q.keys())
        kl = 0.0
        for key in all_keys:
            p_val = p.get(key, epsilon)
            q_val = q.get(key, epsilon)
            if p_val > epsilon:
                kl += p_val * math.log(p_val / q_val)
        return max(0.0, kl)

    @staticmethod
    def entropy(dist: dict[str, float], epsilon: float = 1e-10) -> float:
        """Compute Shannon entropy H(P) = -Σ P(x) · log(P(x))."""
        h = 0.0
        for val in dist.values():
            if val > epsilon:
                h -= val * math.log(val)
        return h

    @staticmethod
    def normalize_distribution(counts: dict[str, int]) -> dict[str, float]:
        """Convert raw counts to a probability distribution."""
        total = sum(counts.values())
        if total == 0:
            return {}
        return {k: v / total for k, v in counts.items()}

    # ==================================================================
    # INFERENCE OUTPUT PROCESSING
    # ==================================================================

    def _on_inference_output(self, msg: String):
        """
        Process an inference output sample.

        Expected JSON format:
        {
            "output_class": "category_name",  // or "output_bin": "0.5-0.6"
            "latency_ms": 12.3
        }
        """
        try:
            data = json.loads(msg.data)
        except json.JSONDecodeError:
            return

        # Extract output category
        output_key = data.get("output_class") or data.get("output_bin", "unknown")
        latency = data.get("latency_ms", 0.0)

        # Update current distribution counts
        self._current_distribution[output_key] = (
            self._current_distribution.get(output_key, 0) + 1
        )
        self._sample_count += 1
        self._total_samples += 1

        # Track latency
        if latency > 0:
            self._latencies.append(latency)

        # Check drift every sample_rate inferences
        if self._sample_count >= self._sample_rate:
            self._evaluate_drift()
            self._sample_count = 0

    def _on_reset_baseline(self, msg: String):
        """Reset baseline distribution (called when a new model loads)."""
        self.get_logger().info('Baseline reset — new model loaded')
        self._baseline_distribution = {}
        self._current_distribution = {}
        self._sample_count = 0
        self._total_samples = 0
        self._latencies.clear()
        self._baseline_latency_set = False
        self._latest_report = DriftReport()

    # ==================================================================
    # DRIFT EVALUATION
    # ==================================================================

    def _evaluate_drift(self):
        """Run all drift detection checks."""
        current_norm = self.normalize_distribution(self._current_distribution)

        # If no baseline yet, the first window becomes the baseline
        if not self._baseline_distribution:
            self._baseline_distribution = current_norm.copy()
            if self._latencies:
                self._baseline_latency_mean = (
                    sum(self._latencies) / len(self._latencies)
                )
                self._baseline_latency_set = True
            self.get_logger().info(
                f'Baseline captured: {len(self._baseline_distribution)} classes, '
                f'{self._total_samples} samples'
            )
            return

        # 1) KL Divergence
        kl = self.kl_divergence(self._baseline_distribution, current_norm)

        # 2) Entropy ratio
        baseline_entropy = self.entropy(self._baseline_distribution)
        current_entropy = self.entropy(current_norm)
        entropy_ratio = (
            current_entropy / baseline_entropy
            if baseline_entropy > 0 else 1.0
        )

        # 3) Latency anomaly
        latency_anomaly = False
        mean_latency = 0.0
        if self._latencies and self._baseline_latency_set:
            mean_latency = sum(self._latencies) / len(self._latencies)
            if mean_latency > self._baseline_latency_mean * self._latency_multiplier:
                latency_anomaly = True

        # Build report
        alert = False
        alert_reason = ""

        if kl > self._kl_threshold:
            alert = True
            alert_reason = f"kl_divergence={kl:.6f} > threshold={self._kl_threshold}"

        if entropy_ratio > self._entropy_threshold or (
            self._entropy_threshold > 0 and entropy_ratio < 1.0 / self._entropy_threshold
        ):
            alert = True
            reason = f"entropy_ratio={entropy_ratio:.4f} outside bounds"
            alert_reason = f"{alert_reason}; {reason}" if alert_reason else reason

        if latency_anomaly:
            alert = True
            reason = (
                f"latency={mean_latency:.1f}ms > "
                f"{self._baseline_latency_mean * self._latency_multiplier:.1f}ms"
            )
            alert_reason = f"{alert_reason}; {reason}" if alert_reason else reason

        self._latest_report = DriftReport(
            timestamp=wall_now(),
            kl_divergence=kl,
            entropy_ratio=entropy_ratio,
            mean_latency_ms=mean_latency,
            latency_anomaly=latency_anomaly,
            samples_since_load=self._total_samples,
            alert=alert,
            alert_reason=alert_reason,
        )

        # Publish alert if triggered
        if alert:
            self.get_logger().warn(f'DRIFT ALERT: {alert_reason}')
            if self._early_expire:
                alert_msg = String()
                alert_msg.data = json.dumps(self._latest_report.to_dict())
                self._alert_pub.publish(alert_msg)

    # ==================================================================
    # REPORTING
    # ==================================================================

    def _publish_report(self):
        """Periodic drift report."""
        msg = String()
        msg.data = json.dumps(self._latest_report.to_dict())
        self._report_pub.publish(msg)

    # ==================================================================
    # Properties (for testing / in-process access)
    # ==================================================================

    @property
    def baseline_distribution(self) -> dict[str, float]:
        return self._baseline_distribution.copy()

    @property
    def latest_report(self) -> DriftReport:
        return self._latest_report


def main(args=None):
    rclpy.init(args=args)
    node = DriftObserverNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
