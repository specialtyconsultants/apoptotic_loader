#!/usr/bin/env python3
"""
Standalone test runner for apoptotic_loader.
Runs without pytest — uses Python's built-in capabilities.
Loads the mock rclpy via conftest before importing any nodes.
"""

import sys
import os
import traceback
import time

# ── Setup paths and mocks (same as conftest.py) ──────────────────────

TEST_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test')
PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, TEST_DIR)
sys.path.insert(0, PACKAGE_DIR)

# Patch rclpy BEFORE any imports
import mock_rclpy
import mock_std_msgs

class _StdMsgsPackage:
    msg = mock_std_msgs

sys.modules['rclpy'] = mock_rclpy
sys.modules['rclpy.node'] = mock_rclpy.node
sys.modules['std_msgs'] = _StdMsgsPackage
sys.modules['std_msgs.msg'] = mock_std_msgs
sys.modules['std_srvs'] = type(sys)('std_srvs')

# ── Now import tests ──────────────────────────────────────────────────

from test.test_types import (
    TestLifecycleState, TestStopType, TestExpireReason,
    TestDriftReport, TestLifecycleEvent, TestCheckpointInfo, TestTimeFunctions,
)
from test.test_drift_observer import (
    TestKLDivergenceMath, TestEntropy, TestNormalizeDistribution,
    TestDriftObserverNode,
)
from test.test_manager import (
    TestManagerNodeInit, TestStateMachine, TestModelLoadDestroy,
    TestTTLExpiration, TestDriftTriggeredExpire, TestForceExpire,
)
from test.test_checkpoint_registry import (
    TestSHA256Verification, TestResolveURI,
)
from test.test_safe_stop import (
    TestSafeStopInit, TestTriggerStop, TestImmediateHold,
    TestReturnHome, TestVelocityRamp, TestClearanceGate,
)


# ── Runner ────────────────────────────────────────────────────────────

def run_test_class(cls):
    """Run all test_* methods on a class, return (passed, failed, errors)."""
    instance = cls()
    methods = [m for m in dir(instance) if m.startswith('test_')]
    passed = 0
    failed = 0
    errors = []

    for method_name in sorted(methods):
        method = getattr(instance, method_name)
        full_name = f"{cls.__name__}.{method_name}"
        try:
            method()
            passed += 1
            print(f"  \033[32m✓\033[0m {full_name}")
        except AssertionError as e:
            failed += 1
            errors.append((full_name, 'FAIL', e))
            print(f"  \033[31m✗\033[0m {full_name} — {e}")
        except Exception as e:
            failed += 1
            errors.append((full_name, 'ERROR', e))
            print(f"  \033[31m✗\033[0m {full_name} — {type(e).__name__}: {e}")

    return passed, failed, errors


def main():
    test_classes = [
        # types.py
        TestLifecycleState, TestStopType, TestExpireReason,
        TestDriftReport, TestLifecycleEvent, TestCheckpointInfo,
        TestTimeFunctions,
        # drift_observer_node.py
        TestKLDivergenceMath, TestEntropy, TestNormalizeDistribution,
        TestDriftObserverNode,
        # manager_node.py
        TestManagerNodeInit, TestStateMachine, TestModelLoadDestroy,
        TestTTLExpiration, TestDriftTriggeredExpire, TestForceExpire,
        # checkpoint_registry_node.py
        TestSHA256Verification, TestResolveURI,
        # safe_stop_node.py
        TestSafeStopInit, TestTriggerStop, TestImmediateHold,
        TestReturnHome, TestVelocityRamp, TestClearanceGate,
    ]

    total_passed = 0
    total_failed = 0
    all_errors = []

    print("\n" + "=" * 70)
    print("APOPTOTIC MODEL LOADING — TEST SUITE")
    print("=" * 70)

    t0 = time.time()

    for cls in test_classes:
        module_name = cls.__module__.split('.')[-1] if '.' in cls.__module__ else cls.__module__
        print(f"\n\033[1m{cls.__name__}\033[0m ({module_name})")
        p, f, errs = run_test_class(cls)
        total_passed += p
        total_failed += f
        all_errors.extend(errs)

    elapsed = time.time() - t0

    print("\n" + "=" * 70)
    if total_failed == 0:
        print(f"\033[32m ALL {total_passed} TESTS PASSED\033[0m in {elapsed:.2f}s")
    else:
        print(f"\033[31m {total_failed} FAILED\033[0m, {total_passed} passed in {elapsed:.2f}s")
        print("\nFailures:")
        for name, kind, err in all_errors:
            print(f"  {kind}: {name}")
            traceback.print_exception(type(err), err, err.__traceback__)
    print("=" * 70 + "\n")

    return 0 if total_failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
