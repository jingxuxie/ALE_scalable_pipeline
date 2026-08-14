from __future__ import annotations

from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
import warnings
import zipfile


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from paper2ale.packaging import BuildFile, write_manifest, write_projection  # noqa: E402
from paper2ale.validation import (  # noqa: E402
    PackageValidationError,
    assert_valid_zip,
    audit_visibility,
    inspect_zip,
    validate_package_dir,
    validate_zip,
)


class VisibilityAuditTests(unittest.TestCase):
    def test_detects_conflicts_leakage_private_paths_and_empty_data(self) -> None:
        files = [
            BuildFile("input/task.txt", b"public SECRET_TARGET public", "agent"),
            BuildFile("Input/task.txt", b"collision", "evaluator"),
            BuildFile("reference_output/metrics.json", b"{}", "agent"),
            BuildFile("input/empty.bin", b"", "agent"),
        ]
        issues = audit_visibility(files, private_sentinels=(b"SECRET_TARGET",))
        codes = {issue.code for issue in issues}
        self.assertEqual(
            codes,
            {
                "conflicting_path",
                "empty_data",
                "private_path_visible_to_agent",
                "private_sentinel_leak",
            },
        )
        self.assertTrue(all(issue.path for issue in issues))

    def test_evaluation_config_and_submission_checker_are_not_false_positives(self) -> None:
        files = [
            BuildFile("input_materials/evaluation_config.json", b"{}", "agent"),
            BuildFile("input_materials/starter/evaluate_submission.py", b"pass\n", "agent"),
        ]
        self.assertEqual(audit_visibility(files), ())


class ZipValidationTests(unittest.TestCase):
    def _write_zip(self, path: Path, members: list[tuple[zipfile.ZipInfo | str, bytes]]) -> None:
        with zipfile.ZipFile(path, "w") as archive:
            for name, data in members:
                archive.writestr(name, data)

    def test_rejects_traversal_drive_and_absolute_members(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "unsafe.zip"
            self._write_zip(
                archive,
                [
                    ("../escape.txt", b"x"),
                    ("C:/drive.txt", b"x"),
                    ("/absolute.txt", b"x"),
                ],
            )
            with self.assertRaises(PackageValidationError):
                assert_valid_zip(archive)
            self.assertEqual(
                {issue.code for issue in inspect_zip(archive)}, {"unsafe_zip_path"}
            )

    def test_rejects_win32_devices_ads_and_ignored_suffixes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "unsafe-windows.zip"
            self._write_zip(
                archive,
                [
                    ("NUL", b"x"),
                    ("folder/CON.txt", b"x"),
                    ("payload.json:secret", b"x"),
                    ("folder/name.", b"x"),
                    ("folder/name ", b"x"),
                ],
            )
            issues = inspect_zip(archive)
            unsafe_paths = {
                issue.path for issue in issues if issue.code == "unsafe_zip_path"
            }
            self.assertEqual(
                unsafe_paths,
                {
                    "NUL",
                    "folder/CON.txt",
                    "payload.json:secret",
                    "folder/name.",
                    "folder/name ",
                },
            )
            with self.assertRaises(PackageValidationError):
                assert_valid_zip(archive)

    def test_rejects_win32_normalized_zip_member_collisions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "win32-collision.zip"
            self._write_zip(
                archive,
                [("Docs/first.txt", b"one"), ("docs/second.txt", b"two")],
            )
            conflicts = [
                issue
                for issue in inspect_zip(archive)
                if issue.code == "duplicate_zip_member"
            ]
            self.assertEqual(len(conflicts), 1)
            self.assertEqual(conflicts[0].path, "docs/second.txt")
            self.assertIn("Docs", conflicts[0].message)

    def test_rejects_symlink_and_duplicate_members(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "unsafe.zip"
            link = zipfile.ZipInfo("link")
            link.create_system = 3
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                self._write_zip(
                    archive,
                    [("duplicate.txt", b"one"), ("duplicate.txt", b"two"), (link, b"target")],
                )
            codes = {issue.code for issue in inspect_zip(archive)}
            self.assertIn("duplicate_zip_member", codes)
            self.assertIn("zip_symlink", codes)
            with self.assertRaises(PackageValidationError):
                assert_valid_zip(archive)

    def test_rejects_excessive_uncompressed_size(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "large.zip"
            self._write_zip(archive, [("payload.bin", b"0123456789")])
            issues = validate_zip(archive, max_uncompressed_bytes=9)
            self.assertIn("zip_too_large", {issue.code for issue in issues})
            with self.assertRaises(PackageValidationError):
                assert_valid_zip(archive, max_uncompressed_bytes=9)


class PackageDirectoryValidationTests(unittest.TestCase):
    def test_manifest_passes_then_detects_checksum_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "package"
            write_projection(
                [BuildFile("task/input.txt", b"trusted\n", "agent")], root, "agent"
            )
            write_manifest(root)
            self.assertEqual(validate_package_dir(root), ())

            (root / "task/input.txt").write_bytes(b"tampered\n")
            issues = validate_package_dir(root)
            self.assertIn("checksum_mismatch", {issue.code for issue in issues})

    def test_detects_unmanifested_file_and_unsafe_manifest_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "package"
            root.mkdir()
            (root / "visible.txt").write_text("visible", encoding="utf-8")
            (root / "MANIFEST.sha256").write_text(
                f"{'0' * 64}  ./../escape.txt\n", encoding="utf-8"
            )
            codes = {issue.code for issue in validate_package_dir(root)}
            self.assertIn("unsafe_manifest_path", codes)
            self.assertIn("unmanifested_file", codes)

    @unittest.skipUnless(sys.platform == "win32", "Windows junction semantics")
    def test_rejects_directory_junction_without_traversing_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "package"
            outside = base / "outside"
            root.mkdir()
            outside.mkdir()
            (outside / "secret.txt").write_text("secret", encoding="utf-8")
            (root / "MANIFEST.sha256").write_text("", encoding="utf-8")
            junction = root / "linked"
            result = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode:
                self.skipTest(f"junction creation unavailable: {result.stderr.strip()}")
            issues = validate_package_dir(root)
            self.assertIn(
                "package_reparse_point", {issue.code for issue in issues}
            )
            self.assertFalse(
                any(issue.path == "linked/secret.txt" for issue in issues),
                "validator must reject the junction itself without walking its target",
            )


if __name__ == "__main__":
    unittest.main()
