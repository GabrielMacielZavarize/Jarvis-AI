from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from jarvis import _dependencies_stale


class WebDependenciesTests(unittest.TestCase):
    def test_installs_when_missing_or_when_the_lock_is_newer(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            web = Path(folder)
            lock = web / "package-lock.json"
            lock.write_text("{}", encoding="utf-8")
            self.assertTrue(_dependencies_stale(web))  # nunca instalado

            installed = web / "node_modules" / ".package-lock.json"
            installed.parent.mkdir()
            installed.write_text("{}", encoding="utf-8")
            os.utime(lock, (1_000, 1_000))
            os.utime(installed, (2_000, 2_000))
            self.assertFalse(_dependencies_stale(web))  # instalado depois do lock

            os.utime(lock, (3_000, 3_000))  # um pull trouxe dependência nova
            self.assertTrue(_dependencies_stale(web))


if __name__ == "__main__":
    unittest.main()
