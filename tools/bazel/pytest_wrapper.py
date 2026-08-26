# **************************************************************************************************************
#
#  Copyright 2020-2026 Robert Bosch GmbH
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#
# **************************************************************************************************************
#
# Shared Bazel entry point for pytest.
#
# `py_test` executes a Python *script*, not a pytest session, so every
# test target points its `main` here and passes its test files as srcs.
#
"""Run pytest over the files Bazel passed us, and forward the exit code."""

from __future__ import annotations

import os
import sys

import pytest


def _test_files(argv: list[str]) -> list[str]:
    """Test files from argv, excluding this wrapper itself."""
    return [
        a for a in argv
        if a.endswith(".py") and not a.endswith("pytest_wrapper.py")
    ]


def main() -> int:
    args = _test_files(sys.argv[1:])
    if not args:
        # No files given -- fall back to the directory Bazel started us in.
        args = [os.getcwd()]

    # `-p no:cacheprovider`: Bazel's runfiles tree is read-only, and
    # pytest's cache would try to write .pytest_cache into it.
    # `-ra`: without it, skip/xfail reasons never reach the Bazel log,
    # which is the only record of why a test did not run.
    return pytest.main(["-ra", "-p", "no:cacheprovider", *args])


if __name__ == "__main__":
    sys.exit(main())
