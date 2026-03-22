"""Tests for checkpoint_registry_node — SHA-256 verification logic."""

import hashlib
import json
import os
import tempfile

from apoptotic_loader.checkpoint_registry_node import CheckpointRegistryNode
from mock_std_msgs import String


class TestSHA256Verification:
    def _make_node_with_file(self, content: bytes, correct_hash: bool = True):
        """Create a temp checkpoint file and a registry node pointing to it."""
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.pt')
        tmp.write(content)
        tmp.close()

        actual_hash = hashlib.sha256(content).hexdigest()
        if correct_hash:
            use_hash = actual_hash
        else:
            use_hash = "0" * 64  # Wrong hash

        node = CheckpointRegistryNode()
        node._uri = tmp.name
        node._expected_hash = use_hash
        node._info.uri = tmp.name
        node._info.expected_hash = use_hash
        return node, tmp.name, actual_hash

    def test_valid_checkpoint_verifies(self):
        content = b"fake model weights v2.4"
        node, path, _ = self._make_node_with_file(content, correct_hash=True)
        try:
            result = node._verify_checkpoint()
            assert result is True
            assert node._info.verified is True
            assert node._info.last_error == ""
        finally:
            os.unlink(path)

    def test_hash_mismatch_fails(self):
        content = b"fake model weights v2.4"
        node, path, _ = self._make_node_with_file(content, correct_hash=False)
        try:
            result = node._verify_checkpoint()
            assert result is False
            assert node._info.verified is False
            assert "mismatch" in node._info.last_error.lower()
        finally:
            os.unlink(path)

    def test_missing_file_fails(self):
        node = CheckpointRegistryNode()
        node._uri = "/nonexistent/model.pt"
        node._expected_hash = "abc123"
        result = node._verify_checkpoint()
        assert result is False
        assert "not found" in node._info.last_error.lower()

    def test_no_uri_fails(self):
        node = CheckpointRegistryNode()
        node._uri = ""
        result = node._verify_checkpoint()
        assert result is False

    def test_no_hash_warns_but_passes(self):
        """If no expected hash configured, verification passes with warning."""
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.pt')
        tmp.write(b"model data")
        tmp.close()
        try:
            node = CheckpointRegistryNode()
            node._uri = tmp.name
            node._expected_hash = ""
            result = node._verify_checkpoint()
            assert result is True  # Passes with warning
        finally:
            os.unlink(tmp.name)

    def test_sha256_prefix_stripped(self):
        """Hash with 'sha256:' prefix should work."""
        content = b"test model"
        node, path, actual_hash = self._make_node_with_file(content)
        node._expected_hash = f"sha256:{actual_hash}"
        node._info.expected_hash = f"sha256:{actual_hash}"
        try:
            result = node._verify_checkpoint()
            assert result is True
        finally:
            os.unlink(path)

    def test_compute_sha256_correctness(self):
        content = b"hello world"
        expected = hashlib.sha256(content).hexdigest()
        tmp = tempfile.NamedTemporaryFile(delete=False)
        tmp.write(content)
        tmp.close()
        try:
            actual = CheckpointRegistryNode._compute_sha256(None, tmp.name)
            assert actual == expected
        finally:
            os.unlink(tmp.name)

    def test_verification_publishes_result(self):
        content = b"model bytes"
        node, path, _ = self._make_node_with_file(content, correct_hash=True)
        try:
            verify_pub = node.get_publisher('verification_result')
            before = len(verify_pub.published)
            node._verify_checkpoint()
            assert len(verify_pub.published) > before
            data = json.loads(verify_pub.published[-1].data)
            assert data["verified"] is True
        finally:
            os.unlink(path)


class TestResolveURI:
    def test_local_path(self):
        result = CheckpointRegistryNode._resolve_path("/opt/models/test.pt")
        assert result == "/opt/models/test.pt"

    def test_s3_returns_none(self):
        """S3 not implemented yet — should return None."""
        result = CheckpointRegistryNode._resolve_path("s3://bucket/model.pt")
        assert result is None

    def test_gcs_returns_none(self):
        result = CheckpointRegistryNode._resolve_path("gs://bucket/model.pt")
        assert result is None
