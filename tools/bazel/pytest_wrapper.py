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
# test target points its `main` here and names its test files in `args`
# (`$(rootpath <file>)`): a file in srcs alone is never on argv.
#
"""Run pytest over the files Bazel passed us, and forward the exit code."""

from __future__ import annotations

import os
import sys

import pytest

# This file is <runfiles root>/tools/bazel/pytest_wrapper.py, both in a
# runfiles tree and in the zip Bazel extracts on Windows -- a better anchor
# than the working directory, which differs between the two.
RUNFILES_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _test_files(argv: list[str]) -> list[str]:
    """Test files from argv, excluding this wrapper itself."""
    return [
        a for a in argv
        if a.endswith(".py") and not a.endswith("pytest_wrapper.py")
    ]


def main() -> int:
    args = [a if os.path.isabs(a) else os.path.join(RUNFILES_ROOT, a)
            for a in _test_files(sys.argv[1:])]
    if not args:
        # Scanning the working directory instead would collect whatever
        # happens to be in the runfiles (or nothing at all on Windows).
        print("pytest_wrapper: no test files given; set args = [\"$(rootpath <file>)\"] "
              "on the py_test", file=sys.stderr)
        return 4   # pytest's own "usage error"
    missing = [a for a in args if not os.path.isfile(a)]
    if missing:
        print("pytest_wrapper: test file(s) not in the runfiles: " + ", ".join(missing),
              file=sys.stderr)
        return 4

    # Processes the tests start (the MSB suites run component_test.py as a
    # child) get the same import path as this one.
    os.environ["PYTHONPATH"] = os.pathsep.join(
        [p for p in sys.path if p] + [os.environ.get("PYTHONPATH", "")]).strip(os.pathsep)

    # `-p no:cacheprovider`: Bazel's runfiles tree is read-only, and
    # pytest's cache would try to write .pytest_cache into it.
    # `-ra`: without it, skip/xfail reasons never reach the Bazel log,
    # which is the only record of why a test did not run.
    return pytest.main(["-ra", "-p", "no:cacheprovider", *args])


if __name__ == "__main__":
    sys.exit(main())
