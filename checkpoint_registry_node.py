"""
checkpoint_registry_node — SHA-256 verified model storage.

Manages the known-good checkpoint: stores its URI & hash, verifies integrity
before every serve, and publishes verification results. If the checkpoint is
tampered with or missing, the node raises an alert so the manager can trigger
safe-stop instead of loading a corrupt model.

Topics Published:
    ~/checkpoint_status  (std_msgs/String)  — periodic status JSON
    ~/verification_result (std_msgs/String) — per-request verification JSON

Topics Subscribed:
    ~/verify_request (std_msgs/String)      — triggers on-demand verification
"""

import hashlib
import json
import os
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from apoptotic_loader.types import CheckpointInfo, wall_now


class CheckpointRegistryNode(Node):
    """Store & verify model checkpoints with SHA-256 integrity checks."""

    def __init__(self):
        super().__init__('checkpoint_registry')

        # --- Parameters ---
        self.declare_parameter('checkpoint_uri', '')
        self.declare_parameter('checkpoint_hash', '')
        self.declare_parameter('integrity_check_interval', 3600.0)
        self.declare_parameter('max_verify_retries', 3)

        self._uri = self.get_parameter('checkpoint_uri').get_parameter_value().string_value
        self._expected_hash = self.get_parameter('checkpoint_hash').get_parameter_value().string_value
        self._check_interval = self.get_parameter('integrity_check_interval').get_parameter_value().double_value
        self._max_retries = self.get_parameter('max_verify_retries').get_parameter_value().integer_value

        # --- State ---
        self._info = CheckpointInfo(
            uri=self._uri,
            expected_hash=self._expected_hash,
        )

        # --- Publishers ---
        self._status_pub = self.create_publisher(String, '~/checkpoint_status', 10)
        self._verify_pub = self.create_publisher(String, '~/verification_result', 10)

        # --- Subscribers ---
        self._verify_sub = self.create_subscription(
            String, '~/verify_request', self._on_verify_request, 10
        )

        # --- Timers ---
        self._status_timer = self.create_timer(self._check_interval, self._periodic_check)

        self.get_logger().info(
            f'Checkpoint registry initialized: uri={self._uri}'
        )

        # Initial verification
        self._verify_checkpoint()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def get_checkpoint_info(self) -> CheckpointInfo:
        """Return current checkpoint metadata (for in-process use)."""
        return self._info

    # ------------------------------------------------------------------
    # Verification logic
    # ------------------------------------------------------------------

    def _verify_checkpoint(self) -> bool:
        """
        Verify the checkpoint file against the expected SHA-256 hash.
        Returns True if verified, False otherwise.
        """
        if not self._uri:
            self._info.last_error = "No checkpoint URI configured"
            self._info.verified = False
            self.get_logger().warn(self._info.last_error)
            self._publish_verification(False, self._info.last_error)
            return False

        if not self._expected_hash:
            # No hash configured — accept but warn
            self._info.last_error = "No expected hash configured — skipping verification"
            self._info.verified = True
            self._info.verified_at = wall_now()
            self.get_logger().warn(self._info.last_error)
            self._publish_verification(True, "no_hash_configured")
            return True

        # Resolve local file path
        path = self._resolve_path(self._uri)
        if path is None:
            self._info.last_error = f"Cannot resolve checkpoint path: {self._uri}"
            self._info.verified = False
            self.get_logger().error(self._info.last_error)
            self._publish_verification(False, self._info.last_error)
            return False

        if not os.path.isfile(path):
            self._info.last_error = f"Checkpoint file not found: {path}"
            self._info.verified = False
            self.get_logger().error(self._info.last_error)
            self._publish_verification(False, self._info.last_error)
            return False

        # Compute SHA-256
        try:
            actual_hash = self._compute_sha256(path)
            self._info.size_bytes = os.path.getsize(path)
        except Exception as e:
            self._info.last_error = f"Hash computation failed: {e}"
            self._info.verified = False
            self.get_logger().error(self._info.last_error)
            self._publish_verification(False, self._info.last_error)
            return False

        # Compare — strip 'sha256:' prefix if present
        expected = self._expected_hash
        if expected.startswith('sha256:'):
            expected = expected[7:]

        if actual_hash == expected:
            self._info.verified = True
            self._info.verified_at = wall_now()
            self._info.last_error = ""
            self.get_logger().info(f'Checkpoint verified: {actual_hash[:16]}...')
            self._publish_verification(True, "ok")
            return True
        else:
            self._info.last_error = (
                f"Hash mismatch: expected {expected[:16]}... "
                f"got {actual_hash[:16]}..."
            )
            self._info.verified = False
            self.get_logger().error(f'CHECKPOINT INTEGRITY FAILURE: {self._info.last_error}')
            self._publish_verification(False, self._info.last_error)
            return False

    def _compute_sha256(self, path: str) -> str:
        """Compute SHA-256 hash of a file."""
        sha = hashlib.sha256()
        with open(path, 'rb') as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                sha.update(chunk)
        return sha.hexdigest()

    @staticmethod
    def _resolve_path(uri: str) -> str | None:
        """
        Resolve a URI to a local path.
        Currently supports local paths only.
        S3/GCS support is a future extension point.
        """
        if uri.startswith('s3://') or uri.startswith('gs://'):
            # TODO: download from cloud storage to local cache
            return None
        return uri

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def _on_verify_request(self, msg: String):
        """Handle on-demand verification request from the manager."""
        self.get_logger().info(f'Verification requested: {msg.data}')
        retries = 0
        while retries < self._max_retries:
            if self._verify_checkpoint():
                return
            retries += 1
            self.get_logger().warn(
                f'Verification retry {retries}/{self._max_retries}'
            )
        self.get_logger().error('Verification failed after all retries')

    def _periodic_check(self):
        """Periodic integrity check."""
        self._verify_checkpoint()
        self._publish_status()

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------

    def _publish_verification(self, success: bool, detail: str):
        msg = String()
        msg.data = json.dumps({
            "verified": success,
            "detail": detail,
            "uri": self._uri,
            "hash": self._expected_hash[:16] + "..." if self._expected_hash else "",
            "timestamp": wall_now(),
        })
        self._verify_pub.publish(msg)

    def _publish_status(self):
        msg = String()
        msg.data = json.dumps({
            "uri": self._info.uri,
            "verified": self._info.verified,
            "verified_at": self._info.verified_at,
            "size_bytes": self._info.size_bytes,
            "last_error": self._info.last_error,
        })
        self._status_pub.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = CheckpointRegistryNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
