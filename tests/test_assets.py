from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from paper2ale.assets import (
    AssetCache,
    AssetFile,
    AssetLimits,
    AssetSnapshot,
    AssetSpec,
    asset_bundle_digest,
    resolve_assets,
    snapshot_asset,
)


def _create_junction(link: Path, target: Path) -> bool:
    if os.name != "nt":
        return False
    result = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        check=False,
        text=True,
    )
    return result.returncode == 0


def _empty_asset_file(relative_path: str) -> AssetFile:
    return AssetFile(
        relative_path=relative_path,
        size_bytes=0,
        sha256=hashlib.sha256(b"").hexdigest(),
        media_type="application/octet-stream",
        extraction_status="empty",
    )


class AssetTests(unittest.TestCase):
    def test_repository_snapshot_is_sorted_hashed_and_path_free(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            (root / "z").mkdir(parents=True)
            (root / "z" / "last.py").write_text("print('z')\n", encoding="utf-8")
            (root / "first.txt").write_bytes(b"first\n")
            (root / ".git").mkdir()
            (root / ".git" / "secret").write_text("ignored", encoding="utf-8")
            cache = AssetCache(Path(directory) / "cache")
            snapshot = snapshot_asset(
                root,
                asset_id="repo.main",
                kind="repository",
                metadata={"license": "MIT", "commit": "abc123"},
                cache=cache,
            )
            self.assertEqual([item.relative_path for item in snapshot.files], ["first.txt", "z/last.py"])
            self.assertEqual(snapshot.metadata["commit"], "abc123")
            manifest = snapshot.to_dict()
            serialized = json.dumps(manifest)
            self.assertNotIn(str(root), serialized)
            self.assertNotIn("secret", serialized)
            self.assertNotIn("text", manifest["files"][0])
            self.assertEqual(
                cache.read(snapshot.files[0].sha256, max_bytes=1024),
                b"first\n",
            )

    def test_snapshot_content_hash_is_deterministic_and_content_sensitive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "paper.txt"
            path.write_text("alpha", encoding="utf-8")
            first = snapshot_asset(path, asset_id="paper", metadata={"title": "A"})
            repeated = snapshot_asset(path, asset_id="paper", metadata={"title": "B"})
            self.assertEqual(first.content_sha256, repeated.content_sha256)
            path.write_text("beta", encoding="utf-8")
            changed = snapshot_asset(path, asset_id="paper", metadata={"title": "A"})
            self.assertNotEqual(first.content_sha256, changed.content_sha256)
            self.assertEqual(first.files[0].text, "alpha")

    def test_bounds_fail_closed_without_truncation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "large.txt"
            path.write_text("x" * 100, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "byte limit"):
                snapshot_asset(
                    path,
                    asset_id="large",
                    limits=AssetLimits(max_file_bytes=32),
                )
            snapshot = snapshot_asset(
                path,
                asset_id="large",
                limits=AssetLimits(max_text_chars_per_file=20),
            )
            self.assertEqual(snapshot.files[0].extraction_status, "omitted_limit")
            self.assertIsNone(snapshot.files[0].text)

    def test_cache_detects_tampering_and_bounds_reads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = AssetCache(directory)
            digest = cache.put(b"trusted bytes")
            with self.assertRaisesRegex(ValueError, "read limit"):
                cache.read(digest, max_bytes=2)
            blob = Path(directory) / "blobs" / digest[:2] / digest
            blob.write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "corrupt"):
                cache.read(digest, max_bytes=100)

    def test_resolve_assets_has_stable_order_and_rejects_duplicate_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            a = root / "a.txt"
            b = root / "b.csv"
            a.write_text("a", encoding="utf-8")
            b.write_text("x,y\n1,2\n", encoding="utf-8")
            specs = [AssetSpec("z", b), AssetSpec("a", a)]
            assets = resolve_assets(specs)
            self.assertEqual([item.asset_id for item in assets], ["a", "z"])
            self.assertEqual(len(asset_bundle_digest(assets)), 64)
            with self.assertRaisesRegex(ValueError, "duplicate"):
                resolve_assets([AssetSpec("same", a), AssetSpec("same", b)])

    def test_metadata_is_strict_and_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.json"
            path.write_text("{}", encoding="utf-8")
            metadata = {"nested": {"items": [1]}}
            snapshot = snapshot_asset(path, asset_id="data", metadata=metadata)
            metadata["nested"]["items"].append(2)
            self.assertEqual(snapshot.to_dict()["metadata"]["nested"]["items"], [1])
            with self.assertRaises(TypeError):
                snapshot.metadata["x"] = 1
            with self.assertRaisesRegex(ValueError, "strict JSON"):
                snapshot_asset(path, asset_id="bad", metadata={"value": float("nan")})

    def test_sensitive_filenames_fail_before_any_bytes_are_cached(self) -> None:
        sensitive_names = (
            ".env",
            ".env.production",
            "credentials.json",
            "keys/id_rsa",
            "keys/signing.PEM",
            "state/terraform.tfstate",
        )
        for sensitive_name in sensitive_names:
            with self.subTest(sensitive_name=sensitive_name), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                root = base / "repo"
                cache_root = base / "cache"
                sensitive = root.joinpath(*sensitive_name.split("/"))
                sensitive.parent.mkdir(parents=True, exist_ok=True)
                (root / "ordinary.txt").write_text("ordinary", encoding="utf-8")
                sensitive.write_text("do-not-cache", encoding="utf-8")
                cache = AssetCache(cache_root)
                with self.assertRaisesRegex(ValueError, "sensitive filename"):
                    snapshot_asset(root, asset_id="repo", cache=cache)
                self.assertEqual(list(cache_root.rglob("*")), [])

    def test_sensitive_single_file_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env.example"
            path.write_text("placeholder=true", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "sensitive filename"):
                snapshot_asset(path, asset_id="environment")

    def test_symlinks_are_rejected_when_supported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target.txt"
            target.write_text("target", encoding="utf-8")
            link = root / "link.txt"
            try:
                os.symlink(target, link)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable on this host")
            with self.assertRaisesRegex(ValueError, "symbolic link"):
                snapshot_asset(link, asset_id="link")

    def test_junction_descendant_is_rejected_when_supported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "repo"
            outside = base / "outside"
            root.mkdir()
            outside.mkdir()
            (outside / "secret.txt").write_text("secret", encoding="utf-8")
            junction = root / "linked"
            if not _create_junction(junction, outside):
                self.skipTest("directory junctions unavailable on this host")
            try:
                with self.assertRaisesRegex(ValueError, "reparse point"):
                    snapshot_asset(root, asset_id="repo")
            finally:
                os.rmdir(junction)
            self.assertEqual((outside / "secret.txt").read_text(encoding="utf-8"), "secret")

    def test_cache_rejects_junction_descendant_when_supported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            cache_root = base / "cache"
            outside = base / "outside"
            cache_root.mkdir()
            outside.mkdir()
            cache = AssetCache(cache_root)
            junction = cache_root / "blobs"
            if not _create_junction(junction, outside):
                self.skipTest("directory junctions unavailable on this host")
            try:
                with self.assertRaisesRegex(ValueError, "reparse point"):
                    cache.put(b"must stay in the cache")
            finally:
                os.rmdir(junction)
            self.assertEqual(list(outside.iterdir()), [])

    def test_win32_unsafe_relative_path_components_are_rejected(self) -> None:
        unsafe_paths = (
            "NUL",
            "CLOCK$",
            "CON.txt",
            "folder/LPT9.csv",
            "folder/COM\u00b9.log",
            "folder/payload.json:stream",
            "folder/trailing.",
            "folder/trailing ",
        )
        for relative_path in unsafe_paths:
            with self.subTest(relative_path=relative_path):
                with self.assertRaisesRegex(ValueError, "unsafe asset relative path"):
                    _empty_asset_file(relative_path)

    def test_win32_normalized_file_and_directory_collisions_are_rejected(self) -> None:
        collisions = (
            ("README.txt", "readme.TXT"),
            ("Docs/a.txt", "docs/b.txt"),
            ("folder", "folder/child.txt"),
        )
        for relative_paths in collisions:
            with self.subTest(relative_paths=relative_paths):
                files = tuple(
                    sorted(
                        (_empty_asset_file(path) for path in relative_paths),
                        key=lambda item: item.relative_path,
                    )
                )
                with self.assertRaisesRegex(ValueError, "Win32-normalized collision"):
                    AssetSnapshot(
                        asset_id="collision",
                        kind="repository",
                        content_sha256=hashlib.sha256(b"collision").hexdigest(),
                        files=files,
                        metadata={},
                    )

    def test_excluded_junction_is_still_rejected_when_supported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "repo"
            outside = base / "outside"
            root.mkdir()
            outside.mkdir()
            (root / "included.txt").write_text("included", encoding="utf-8")
            (outside / "secret.txt").write_text("secret", encoding="utf-8")
            junction = root / ".git"
            if not _create_junction(junction, outside):
                self.skipTest("directory junctions unavailable on this host")
            try:
                with self.assertRaisesRegex(ValueError, "reparse point"):
                    snapshot_asset(root, asset_id="repo")
            finally:
                os.rmdir(junction)

    def test_invalid_pdf_suffix_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fake.pdf"
            path.write_bytes(b"not a PDF")
            with self.assertRaisesRegex(ValueError, "no PDF header"):
                snapshot_asset(path, asset_id="paper", kind="document")


if __name__ == "__main__":
    unittest.main()
