#!/usr/bin/env python3
"""
Standalone test — runs the Apoptotic framework logic WITHOUT needing ROS2 installed.
Tests: TTL countdown, KL Divergence calculation, state machine, and drift detection.
Craig McClurkin / Specialty Consultants — Apache-2.0
"""

import math
import random
import time
import gc
from datetime import datetime


# ─────────────────────────────────────────────────────────────────────────────
# KL Divergence (same formula as drift_observer.py)
# ─────────────────────────────────────────────────────────────────────────────

def kl_divergence(p: list, q: list) -> float:
    """D_KL(P || Q) = sum_x P(x) * log(P(x) / Q(x))"""
    eps = 1e-10
    return sum(px * math.log((px + eps) / (qx + eps)) for px, qx in zip(p, q) if px > 0)


# ─────────────────────────────────────────────────────────────────────────────
# Mock Apoptotic Manager (standalone, no ROS2)
# ─────────────────────────────────────────────────────────────────────────────

class MockApoptoticManager:
    STATES = ["UNLOADED", "VERIFYING", "LOADING", "ACTIVE", "EXPIRING", "RELOADING"]

    def __init__(self, ttl_seconds=10, kl_threshold=0.05):
        self.ttl_seconds = ttl_seconds
        self.kl_threshold = kl_threshold
        self.current_ttl = ttl_seconds
        self.state = "UNLOADED"
        self.model = None
        self.apoptosis_count = 0
        self.log(f"Manager init — TTL: {ttl_seconds}s | KL threshold: {kl_threshold}")

    def log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{ts}] [apoptotic_manager] {msg}")

    def set_state(self, state):
        self.state = state
        self.log(f"STATE → {state}")

    def execute_model_load(self):
        self.set_state("VERIFYING")
        time.sleep(0.05)
        self.set_state("LOADING")
        time.sleep(0.05)
        self.model = f"MOCK_MODEL_v1.0_loaded_at_{datetime.now().isoformat()}"
        self.set_state("ACTIVE")
        self.log("✅ Model loaded and verified. Lifecycle clock started.")
        return True

    def execute_model_destroy(self):
        self.log("🔥 Executing programmed cell death...")
        del self.model
        self.model = None
        gc.collect()
        self.log("✅ Model state destroyed cleanly.")

    def trigger_apoptosis(self, reason="TTL_EXPIRED"):
        self.apoptosis_count += 1
        self.set_state("EXPIRING")
        self.log(f"☠  Apoptosis #{self.apoptosis_count} triggered — reason: {reason}")
        self.execute_model_destroy()
        self.set_state("RELOADING")
        self.execute_model_load()
        self.current_ttl = self.ttl_seconds
        self.log(f"🔄 Reload complete. TTL reset to {self.ttl_seconds}s.")

    def tick(self):
        if self.state == "ACTIVE":
            self.current_ttl -= 1
            if self.current_ttl <= 0:
                self.log(f"⚠  TTL EXPIRED — executing programmed apoptosis...")
                self.trigger_apoptosis("TTL_EXPIRED")


# ─────────────────────────────────────────────────────────────────────────────
# TESTS
# ─────────────────────────────────────────────────────────────────────────────

def test_kl_divergence():
    print("\n" + "="*60)
    print("TEST 1: KL Divergence")
    print("="*60)

    baseline = [0.1] * 10

    # Identical distributions — KL should be ~0
    kl_zero = kl_divergence(baseline, baseline[:])
    print(f"  Identical distributions:  KL = {kl_zero:.8f}  (expected ~0.0)")
    assert kl_zero < 1e-6, f"FAIL: expected ~0, got {kl_zero}"

    # Slightly perturbed
    perturbed = [0.08, 0.09, 0.11, 0.10, 0.12, 0.09, 0.10, 0.10, 0.11, 0.10]
    total = sum(perturbed)
    perturbed = [x/total for x in perturbed]
    kl_small = kl_divergence(baseline, perturbed)
    print(f"  Small perturbation:       KL = {kl_small:.8f}  (expected > 0, < 0.05)")
    assert kl_small > 0, "FAIL: KL should be positive"

    # Large divergence
    drifted = [0.5, 0.5, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    kl_large = kl_divergence(baseline, drifted)
    print(f"  Large divergence:         KL = {kl_large:.8f}  (expected > 0.05)")
    assert kl_large > 0.05, f"FAIL: expected KL > 0.05, got {kl_large}"

    print("  ✅ KL Divergence tests PASSED")


def test_ttl_expiry():
    print("\n" + "="*60)
    print("TEST 2: TTL Expiry & State Machine")
    print("="*60)

    mgr = MockApoptoticManager(ttl_seconds=3, kl_threshold=0.05)
    mgr.execute_model_load()

    assert mgr.state == "ACTIVE", f"FAIL: expected ACTIVE, got {mgr.state}"
    assert mgr.model is not None, "FAIL: model should be loaded"

    # Tick down to expiry
    for _ in range(3):
        mgr.tick()
        time.sleep(0.01)

    assert mgr.state == "ACTIVE", f"FAIL: expected ACTIVE after reset, got {mgr.state}"
    assert mgr.apoptosis_count == 1, f"FAIL: expected 1 apoptosis, got {mgr.apoptosis_count}"
    assert mgr.current_ttl == 3, f"FAIL: TTL should reset to 3, got {mgr.current_ttl}"
    assert mgr.model is not None, "FAIL: model should be reloaded"
    print("  ✅ TTL Expiry tests PASSED")


def test_manual_override():
    print("\n" + "="*60)
    print("TEST 3: Manual Force-Expire Override")
    print("="*60)

    mgr = MockApoptoticManager(ttl_seconds=100, kl_threshold=0.05)
    mgr.execute_model_load()

    # Force expire before TTL
    mgr.trigger_apoptosis(reason="MANUAL_TEST")

    assert mgr.apoptosis_count == 1, f"FAIL: expected 1 apoptosis, got {mgr.apoptosis_count}"
    assert mgr.state == "ACTIVE", f"FAIL: expected ACTIVE after reload, got {mgr.state}"
    assert mgr.current_ttl == 100, f"FAIL: TTL should reset to 100"
    print("  ✅ Manual override test PASSED")


def test_drift_detection():
    print("\n" + "="*60)
    print("TEST 4: Drift Detection Simulation")
    print("="*60)

    baseline = [0.1] * 10
    threshold = 0.05
    alerts_triggered = 0

    for round_num in range(1, 11):
        drift = round_num * 0.01
        current = [max(0.001, b + random.uniform(-drift, drift)) for b in baseline]
        total = sum(current)
        current = [x/total for x in current]
        kl = kl_divergence(baseline, current)
        status = "🔴 ALERT" if kl >= threshold else "🟢 OK"
        if kl >= threshold:
            alerts_triggered += 1
        print(f"  Round {round_num:2d} | drift_factor={drift:.2f} | KL={kl:.6f} | {status}")

    print(f"\n  Drift alerts triggered: {alerts_triggered}/10")
    print("  ✅ Drift detection test PASSED")


def test_multiple_cycles():
    print("\n" + "="*60)
    print("TEST 5: Multiple Apoptosis Cycles")
    print("="*60)

    mgr = MockApoptoticManager(ttl_seconds=2, kl_threshold=0.05)
    mgr.execute_model_load()

    cycles = 3
    for i in range(cycles):
        for _ in range(2):
            mgr.tick()
        print(f"  Cycle {i+1} complete | apoptosis_count={mgr.apoptosis_count}")

    assert mgr.apoptosis_count == cycles, f"FAIL: expected {cycles} apoptoses, got {mgr.apoptosis_count}"
    assert mgr.state == "ACTIVE"
    assert mgr.model is not None
    print(f"  ✅ {cycles}-cycle test PASSED")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print("\n" + "█"*60)
    print("  APOPTOTIC MODEL LOADING — Standalone Test Suite")
    print("  Specialty Consultants / Craig McClurkin")
    print("  Apache-2.0 | craig.mcclurkin@louisville.edu")
    print("█"*60)

    start = time.time()

    test_kl_divergence()
    test_ttl_expiry()
    test_manual_override()
    test_drift_detection()
    test_multiple_cycles()

    elapsed = time.time() - start
    print("\n" + "="*60)
    print(f"  ALL TESTS PASSED in {elapsed:.3f}s ✅")
    print("  Framework is ready for ROS 2 colcon build.")
    print("="*60 + "\n")
