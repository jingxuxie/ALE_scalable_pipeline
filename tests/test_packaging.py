from __future__ import annotations

import hashlib
from pathlib import Path
import stat
import subprocess
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
    write_deterministic_zip_from_files,
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

    def test_rejects_win32_devices_ads_and_ignored_suffixes(self) -> None:
        unsafe = (
            "NUL",
            "nul.txt",
            "folder/CON.json",
            "COM1.log",
            "LPT9",
            "COM¹.txt",
            "payload.json:secret",
            "folder/name.",
            "folder/name ",
        )
        for path in unsafe:
            with self.subTest(path=path), self.assertRaisesRegex(
                ValueError, "Windows|Win32"
            ):
                BuildFile(path, b"data", "agent")

        for path in ("console.txt", "com10.txt", ".env", "folder/name.txt"):
            with self.subTest(path=path):
                self.assertEqual(BuildFile(path, b"data", "agent").path, path)

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

    def test_direct_inventory_zip_avoids_materializing_deep_member_paths(self) -> None:
        member = (
            "task-data/research_workflows/"
            + "t" * 128
            + "/000/reference/instances/000/evaluation.json"
        )
        files = [BuildFile(member, b'{"expected":42}\n', "evaluator")]
        with tempfile.TemporaryDirectory() as temporary:
            archive_path = Path(temporary) / "deployment.zip"
            first = write_deterministic_zip_from_files(files, archive_path)
            first_bytes = archive_path.read_bytes()
            second = write_deterministic_zip_from_files(files, archive_path)
            self.assertEqual(first, second)
            self.assertEqual(first_bytes, archive_path.read_bytes())
            with zipfile.ZipFile(archive_path) as archive:
                self.assertEqual(
                    set(archive.namelist()),
                    {"MANIFEST.sha256", member},
                )
                manifest = archive.read("MANIFEST.sha256").decode("utf-8")
                self.assertIn(hashlib.sha256(files[0].data).hexdigest(), manifest)
                self.assertIn(f"./{member}", manifest)

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

    @unittest.skipUnless(sys.platform == "win32", "Windows junction semantics")
    def test_package_walk_rejects_directory_junctions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "package"
            outside = base / "outside"
            root.mkdir()
            outside.mkdir()
            (outside / "secret.txt").write_text("secret", encoding="utf-8")
            junction = root / "linked"
            result = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode:
                self.skipTest(f"junction creation unavailable: {result.stderr.strip()}")
            self.assertTrue(junction.is_junction())
            self.assertFalse(junction.is_symlink())
            with self.assertRaisesRegex(ValueError, "junction|reparse"):
                write_manifest(root)

    @unittest.skipUnless(sys.platform == "win32", "Windows path-length semantics")
    def test_short_atomic_temp_name_works_near_windows_path_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "projection"
            parent = root / "nested"
            filename_length = 250 - len(str(parent.resolve())) - 1
            if not 32 <= filename_length <= 240:
                self.skipTest("temporary root does not leave a useful filename budget")
            filename = "x" * filename_length
            written = write_projection(
                [BuildFile(f"nested/{filename}", b"payload", "agent")],
                root,
                "agent",
            )
            self.assertEqual(len(str(written[0].resolve())), 250)
            self.assertEqual(written[0].read_bytes(), b"payload")

    @unittest.skipUnless(sys.platform == "win32", "Windows path-length semantics")
    def test_overlong_windows_destination_fails_with_actionable_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "projection"
            parent = root / "nested"
            filename_length = 265 - len(str(parent.resolve())) - 1
            if not 32 <= filename_length <= 240:
                self.skipTest("temporary root does not leave a useful filename budget")
            with self.assertRaisesRegex(ValueError, "shorter --out"):
                write_projection(
                    [
                        BuildFile(
                            f"nested/{'x' * filename_length}",
                            b"payload",
                            "agent",
                        )
                    ],
                    root,
                    "agent",
                )


if __name__ == "__main__":
    unittest.main()
