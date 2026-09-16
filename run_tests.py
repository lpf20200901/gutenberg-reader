#!/usr/bin/env python3
"""Run the test suite with no installation and no third-party dependencies.

    python run_tests.py

The suite is written against unittest, so this works on a bare Python install —
no pip, no pytest, no network.
"""

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))


def main() -> int:
    suite = unittest.TestLoader().discover(
        str(ROOT / "tests"), pattern="test_*.py", top_level_dir=str(ROOT / "tests")
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print()
    print(f"ran {result.testsRun} tests, "
          f"failures={len(result.failures)}, errors={len(result.errors)}, "
          f"skipped={len(result.skipped)}")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
