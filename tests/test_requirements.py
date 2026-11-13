"""O requirements.txt travado tem que continuar de acordo com o requirements.in (docs/instalacao.md)."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)")


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirement_lines(path: Path) -> list[str]:
    lines = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        # A linha de "via" do lock começa com espaços; comentários e vazias não contam.
        if not raw.strip() or raw.startswith((" ", "\t", "#")):
            continue
        lines.append(raw.strip())
    return lines


def _direct_names() -> dict[str, str]:
    names = {}
    for line in _requirement_lines(ROOT / "requirements.in"):
        match = NAME.match(line)
        names[_normalize(match.group(1))] = line
    return names


class RequirementsLockTests(unittest.TestCase):
    def test_every_line_of_the_lock_is_pinned(self):
        for line in _requirement_lines(ROOT / "requirements.txt"):
            with self.subTest(line=line):
                self.assertRegex(line.split(";")[0], r"==\S+\s*$", "dependência sem versão exata no lock")

    def test_every_direct_dependency_is_in_the_lock(self):
        locked = {_normalize(NAME.match(line).group(1)) for line in _requirement_lines(ROOT / "requirements.txt")}
        for name, line in _direct_names().items():
            with self.subTest(requirement=line):
                self.assertIn(name, locked, "falta no requirements.txt: regenere o lock (docs/instalacao.md)")

    def test_platform_markers_survive_in_the_lock(self):
        lock = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        for name in ("pycaw", "comtypes"):
            self.assertRegex(lock, rf"(?m)^{name}==\S+ ; sys_platform == 'win32'$")
        self.assertRegex(lock, r"(?m)^openwakeword==\S+ ; sys_platform != 'linux'$")

    def test_direct_dependencies_have_no_version_pins_of_their_own_except_floors(self):
        # O requirements.in só traz o piso (>=) quando existe um motivo; a versão exata é do lock.
        for name, line in _direct_names().items():
            with self.subTest(requirement=line):
                self.assertNotIn("==", line.split(";")[0].split("#")[0])


if __name__ == "__main__":
    unittest.main()
