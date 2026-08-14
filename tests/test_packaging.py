from __future__ import annotations

import hashlib
from pathlib import Path
import stat
import sys
import tempfile
import unittest
import zipfile


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from paper2ale.packaging import (  # noqa: E402
    BuildFile,
    projection_files,
    write_deterministic_zip,
    write_manifest,
    write_projection,
)


class BuildFileTests(unittest.TestCase):
    def test_rejects_unsafe_or_non_posix_paths(self) -> None:
        unsafe = (
            "",
            "/absolute.txt",
            "../escape.txt",
            "safe/../escape.txt",
            "C:/drive.txt",
            "safe\\windows.txt",
            "./relative.txt",
            "double//separator.txt",
            "directory/",
        )
        for path in unsafe:
            with self.subTest(path=path), self.assertRaises((TypeError, ValueError)):
                BuildFile(path, b"data", "agent")

    def test_projection_visibility_and_order(self) -> None:
        files = [
            BuildFile("z-author.txt", b"author", "author"),
            BuildFile("b-evaluator.txt", b"evaluator", "evaluator"),
            BuildFile("a-agent.txt", b"agent", "agent"),
        ]
        self.assertEqual(
            [item.path for item in projection_files(files, "agent")],
            ["a-agent.txt"],
        )
        self.assertEqual(
            [item.path for item in projection_files(files, "evaluator")],
            ["a-agent.txt", "b-evaluator.txt"],
        )
        self.assertEqual(
            [item.path for item in projection_files(files, "author")],
            ["a-agent.txt", "b-evaluator.txt", "z-author.txt"],
        )

    def test_write_projection_rejects_case_collisions(self) -> None:
        files = [
            BuildFile("Data/value.txt", b"one", "agent"),
            BuildFile("data/value.txt", b"two", "agent"),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ValueError):
                write_projection(files, Path(temporary) / "projection", "agent")


class ManifestAndZipTests(unittest.TestCase):
    def _make_package(self, root: Path) -> None:
        write_projection(
            [
                BuildFile("task/README.md", b"hello\n", "agent"),
                BuildFile("task/bin/run.sh", b"#!/bin/sh\nexit 0\n", "agent", True),
                BuildFile("task/data.bin", bytes(range(64)), "agent"),
            ],
            root,
            "agent",
        )
        write_manifest(root)

    def test_manifest_is_sorted_repeatable_and_does_not_hash_itself(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "package"
            self._make_package(root)
            first = (root / "MANIFEST.sha256").read_bytes()
            returned = write_manifest(root).encode("utf-8")
            second = (root / "MANIFEST.sha256").read_bytes()
            self.assertEqual(first, returned)
            self.assertEqual(first, second)
            lines = first.decode("utf-8").splitlines()
            listed = [line.split("  ./", 1)[1] for line in lines]
            self.assertEqual(listed, sorted(listed))
            self.assertNotIn("MANIFEST.sha256", listed)
            expected = hashlib.sha256((root / "task/README.md").read_bytes()).hexdigest()
            self.assertIn(f"{expected}  ./task/README.md", lines)

    def test_zip_is_byte_identical_with_fixed_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "package"
            self._make_package(root)
            first_hash = write_deterministic_zip(
                root, base / "first.zip", executable_paths={"task/bin/run.sh"}
            )
            second_hash = write_deterministic_zip(
                root, base / "second.zip", executable_paths={"task/bin/run.sh"}
            )
            first = base / "first.zip"
            second = base / "second.zip"
            self.assertEqual(first_hash, second_hash)
            self.assertEqual(first_hash, hashlib.sha256(first.read_bytes()).hexdigest())
            self.assertEqual(first.read_bytes(), second.read_bytes())

            with zipfile.ZipFile(first) as archive:
                infos = archive.infolist()
                self.assertEqual([info.filename for info in infos], sorted(info.filename for info in infos))
                for info in infos:
                    self.assertEqual(info.date_time, (1980, 1, 1, 0, 0, 0))
                    mode = (info.external_attr >> 16) & 0o777
                    expected_mode = 0o755 if info.filename == "task/bin/run.sh" else 0o644
                    self.assertEqual(mode, expected_mode)
                    self.assertTrue(stat.S_ISREG((info.external_attr >> 16) & 0xFFFF))


if __name__ == "__main__":
    unittest.main()
