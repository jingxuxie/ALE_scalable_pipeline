from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from paper2ale.cli import _parser, main  # noqa: E402


class ParserTests(unittest.TestCase):
    def assert_parse_error(self, *arguments: str) -> None:
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            _parser().parse_args(arguments)
        self.assertEqual(raised.exception.code, 2)

    def test_positive_numeric_arguments_are_enforced(self) -> None:
        invalid_commands = (
            ("build", "project.json", "--jobs", "0"),
            ("build", "project.json", "--jobs", "-1"),
            ("build", "project.json", "--instances", "0"),
            ("audit", "project.json", "--instances", "-1"),
            ("validate", "package.zip", "--max-uncompressed-mb", "0"),
        )
        for arguments in invalid_commands:
            with self.subTest(arguments=arguments):
                self.assert_parse_error(*arguments)

        parsed = _parser().parse_args(
            ("build", "project.json", "--jobs", "2", "--instances", "3")
        )
        self.assertEqual(parsed.jobs, 2)
        self.assertEqual(parsed.instances, 3)

    def test_force_and_no_resume_are_mutually_exclusive(self) -> None:
        self.assert_parse_error(
            "build", "project.json", "--force", "--no-resume"
        )


class CommandDispatchTests(unittest.TestCase):
    def invoke_build(self, *flags: str) -> tuple[int, dict]:
        result = SimpleNamespace(to_dict=lambda: {"build_id": "test-build"})
        output = io.StringIO()
        with patch("paper2ale.cli.build_project", return_value=result) as build, redirect_stdout(
            output
        ):
            status = main(("build", "project.json", *flags))
        self.assertEqual(json.loads(output.getvalue()), {"build_id": "test-build"})
        return status, build.call_args.kwargs

    def test_default_build_resumes(self) -> None:
        status, arguments = self.invoke_build()
        self.assertEqual(status, 0)
        self.assertTrue(arguments["resume"])
        self.assertFalse(arguments["force"])

    def test_no_resume_refuses_reuse_without_forcing_replacement(self) -> None:
        status, arguments = self.invoke_build("--no-resume")
        self.assertEqual(status, 0)
        self.assertFalse(arguments["resume"])
        self.assertFalse(arguments["force"])

    def test_force_disables_resume_and_requests_quarantine_rebuild(self) -> None:
        status, arguments = self.invoke_build("--force")
        self.assertEqual(status, 0)
        self.assertFalse(arguments["resume"])
        self.assertTrue(arguments["force"])


class ValidateCommandTests(unittest.TestCase):
    def invoke_validate(self, path: Path) -> tuple[int, dict]:
        output = io.StringIO()
        with redirect_stdout(output):
            status = main(("validate", str(path)))
        return status, json.loads(output.getvalue())

    def test_validate_checks_embedded_manifest_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive_path = Path(temporary) / "package.zip"
            expected = hashlib.sha256(b"expected").hexdigest()
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr(
                    "MANIFEST.sha256", f"{expected}  ./payload.txt\n"
                )
                archive.writestr("payload.txt", b"actual")

            status, report = self.invoke_validate(archive_path)
            self.assertEqual(status, 2)
            self.assertFalse(report["passed"])
            self.assertIn(
                "checksum_mismatch", {issue["code"] for issue in report["issues"]}
            )

    def test_validate_accepts_matching_embedded_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive_path = Path(temporary) / "package.zip"
            payload = b"actual"
            expected = hashlib.sha256(payload).hexdigest()
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr(
                    "MANIFEST.sha256", f"{expected}  ./payload.txt\n"
                )
                archive.writestr("payload.txt", payload)

            status, report = self.invoke_validate(archive_path)
            self.assertEqual(status, 0)
            self.assertTrue(report["passed"])
            self.assertEqual(report["issues"], [])


if __name__ == "__main__":
    unittest.main()
