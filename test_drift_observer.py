"""Tests for drift_observer_node — KL divergence, entropy, drift detection."""

import json
import math

from apoptotic_loader.drift_observer_node import DriftObserverNode
from mock_std_msgs import String


class TestKLDivergenceMath:
    """Test the static KL divergence computation directly."""

    def test_identical_distributions_is_zero(self):
        p = {"a": 0.5, "b": 0.3, "c": 0.2}
        q = {"a": 0.5, "b": 0.3, "c": 0.2}
        kl = DriftObserverNode.kl_divergence(p, q)
        assert abs(kl) < 1e-8

    def test_different_distributions_is_positive(self):
        p = {"a": 0.9, "b": 0.1}
        q = {"a": 0.5, "b": 0.5}
        kl = DriftObserverNode.kl_divergence(p, q)
        assert kl > 0

    def test_kl_is_asymmetric(self):
        p = {"a": 0.7, "b": 0.3}
        q = {"a": 0.3, "b": 0.7}
        kl_pq = DriftObserverNode.kl_divergence(p, q)
        kl_qp = DriftObserverNode.kl_divergence(q, p)
        # Both positive but generally different
        assert kl_pq > 0
        assert kl_qp > 0
        # They happen to be equal for this symmetric swap, but the function
        # is asymmetric in general — test with unequal case
        p2 = {"a": 0.8, "b": 0.15, "c": 0.05}
        q2 = {"a": 0.33, "b": 0.33, "c": 0.34}
        kl_1 = DriftObserverNode.kl_divergence(p2, q2)
        kl_2 = DriftObserverNode.kl_divergence(q2, p2)
        assert abs(kl_1 - kl_2) > 0.01  # Asymmetric

    def test_missing_keys_handled(self):
        """Q has a class not in P — should not crash."""
        p = {"a": 0.6, "b": 0.4}
        q = {"a": 0.4, "b": 0.3, "c": 0.3}
        kl = DriftObserverNode.kl_divergence(p, q)
        assert kl >= 0  # Should compute without error

    def test_empty_distributions(self):
        kl = DriftObserverNode.kl_divergence({}, {})
        assert kl == 0.0

    def test_known_value(self):
        """Verify against hand-computed KL divergence."""
        # P = [0.5, 0.5], Q = [0.25, 0.75]
        # D_KL(P||Q) = 0.5*ln(0.5/0.25) + 0.5*ln(0.5/0.75)
        #            = 0.5*ln(2) + 0.5*ln(2/3)
        #            ≈ 0.5*0.6931 + 0.5*(-0.4055)
        #            ≈ 0.1438
        p = {"a": 0.5, "b": 0.5}
        q = {"a": 0.25, "b": 0.75}
        kl = DriftObserverNode.kl_divergence(p, q)
        expected = 0.5 * math.log(0.5 / 0.25) + 0.5 * math.log(0.5 / 0.75)
        assert abs(kl - expected) < 1e-6


class TestEntropy:
    def test_uniform_is_max(self):
        """Uniform distribution has maximum entropy."""
        uniform = {"a": 0.25, "b": 0.25, "c": 0.25, "d": 0.25}
        peaked = {"a": 0.97, "b": 0.01, "c": 0.01, "d": 0.01}
        h_uniform = DriftObserverNode.entropy(uniform)
        h_peaked = DriftObserverNode.entropy(peaked)
        assert h_uniform > h_peaked

    def test_single_class_is_zero(self):
        """Deterministic distribution has zero entropy."""
        det = {"a": 1.0}
        h = DriftObserverNode.entropy(det)
        assert abs(h) < 1e-8

    def test_binary_entropy(self):
        """H([0.5, 0.5]) = ln(2)."""
        dist = {"a": 0.5, "b": 0.5}
        h = DriftObserverNode.entropy(dist)
        assert abs(h - math.log(2)) < 1e-8


class TestNormalizeDistribution:
    def test_basic(self):
        counts = {"a": 3, "b": 7}
        norm = DriftObserverNode.normalize_distribution(counts)
        assert abs(norm["a"] - 0.3) < 1e-8
        assert abs(norm["b"] - 0.7) < 1e-8

    def test_sums_to_one(self):
        counts = {"x": 10, "y": 20, "z": 30}
        norm = DriftObserverNode.normalize_distribution(counts)
        assert abs(sum(norm.values()) - 1.0) < 1e-8

    def test_empty_returns_empty(self):
        assert DriftObserverNode.normalize_distribution({}) == {}


class TestDriftObserverNode:
    """Integration tests for the full node with mocked rclpy."""

    def _make_node(self, kl_threshold=0.05, sample_rate=5):
        node = DriftObserverNode()
        # Override parameters for testing
        node._kl_threshold = kl_threshold
        node._sample_rate = sample_rate
        node._early_expire = True
        node._entropy_threshold = 1.5
        node._latency_multiplier = 3.0
        return node

    def _send_samples(self, node, output_class: str, count: int,
                      latency_ms: float = 10.0):
        """Inject inference output samples into the node."""
        for _ in range(count):
            msg = String()
            msg.data = json.dumps({
                "output_class": output_class,
                "latency_ms": latency_ms,
            })
            node._on_inference_output(msg)

    def test_baseline_captured_on_first_window(self):
        node = self._make_node(sample_rate=10)
        self._send_samples(node, "classA", 5)
        self._send_samples(node, "classB", 5)
        # After 10 samples (sample_rate), baseline should be captured
        assert len(node._baseline_distribution) == 2
        assert abs(node._baseline_distribution["classA"] - 0.5) < 1e-8

    def test_no_alert_when_distribution_matches(self):
        node = self._make_node(sample_rate=10)
        # First window: baseline
        self._send_samples(node, "A", 5)
        self._send_samples(node, "B", 5)
        # Second window: same distribution
        self._send_samples(node, "A", 5)
        self._send_samples(node, "B", 5)
        assert node.latest_report.alert is False

    def test_alert_on_distribution_shift(self):
        node = self._make_node(kl_threshold=0.01, sample_rate=10)
        # Baseline: 50/50
        self._send_samples(node, "A", 5)
        self._send_samples(node, "B", 5)
        # Shift: 90/10 — should trigger KL alert
        self._send_samples(node, "A", 9)
        self._send_samples(node, "B", 1)
        assert node.latest_report.alert is True
        assert "kl_divergence" in node.latest_report.alert_reason

    def test_alert_publishes_to_drift_alert_topic(self):
        node = self._make_node(kl_threshold=0.01, sample_rate=10)
        alert_pub = node.get_publisher('drift_alert')
        # Baseline
        self._send_samples(node, "A", 5)
        self._send_samples(node, "B", 5)
        # Shift
        self._send_samples(node, "A", 10)
        assert len(alert_pub.published) > 0

    def test_latency_anomaly_detection(self):
        node = self._make_node(kl_threshold=1.0, sample_rate=10)
        # Baseline with low latency
        self._send_samples(node, "A", 10, latency_ms=10.0)
        # Spike latency (30x baseline = way over 3x multiplier)
        self._send_samples(node, "A", 10, latency_ms=300.0)
        assert node.latest_report.latency_anomaly is True

    def test_reset_baseline_clears_state(self):
        node = self._make_node(sample_rate=10)
        self._send_samples(node, "A", 10)
        assert len(node._baseline_distribution) > 0
        # Reset
        msg = String()
        msg.data = "new_model_loaded"
        node._on_reset_baseline(msg)
        assert len(node._baseline_distribution) == 0
        assert node._total_samples == 0
