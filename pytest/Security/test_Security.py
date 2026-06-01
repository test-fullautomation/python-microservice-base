"""
Tests for MicroserviceBase security utilities (local_hub_manager.py).

Tests path validation functions that prevent directory traversal attacks.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))))

from MicroserviceBase.adapters.local_hub.local_hub_manager import (
    _validate_safe_name,
    _ensure_path_within,
)


class Test_ValidateSafeName:
    """Tests for _validate_safe_name."""

    def test_validate_safe_name_valid(self):
        _validate_safe_name("MyService")
        _validate_safe_name("service-1.0.0")
        _validate_safe_name("service_name")

    def test_validate_safe_name_empty(self):
        with pytest.raises(ValueError, match="must not be empty"):
            _validate_safe_name("")

    def test_validate_safe_name_with_slash(self):
        with pytest.raises(ValueError, match="path separators"):
            _validate_safe_name("path/to/evil")

    def test_validate_safe_name_with_backslash(self):
        with pytest.raises(ValueError, match="path separators"):
            _validate_safe_name("path\\to\\evil")

    def test_validate_safe_name_with_dotdot(self):
        with pytest.raises(ValueError, match="\\.\\."):
            _validate_safe_name("..")

    def test_validate_safe_name_embedded_dotdot(self):
        with pytest.raises(ValueError, match="\\.\\."):
            _validate_safe_name("foo..bar")


class Test_EnsurePathWithin:
    """Tests for _ensure_path_within."""

    def test_ensure_path_within_valid(self, tmp_path):
        child = tmp_path / "subdir" / "file.txt"
        child.parent.mkdir(parents=True, exist_ok=True)
        child.touch()
        result = _ensure_path_within(str(child), str(tmp_path))
        assert os.path.isabs(result)

    def test_ensure_path_within_exact_match(self, tmp_path):
        result = _ensure_path_within(str(tmp_path), str(tmp_path))
        assert result == os.path.realpath(str(tmp_path))

    def test_ensure_path_within_traversal(self, tmp_path):
        parent = tmp_path / "allowed"
        parent.mkdir()
        child = str(tmp_path / "allowed" / ".." / "escaped")
        with pytest.raises(ValueError, match="escapes the allowed directory"):
            _ensure_path_within(child, str(parent))
