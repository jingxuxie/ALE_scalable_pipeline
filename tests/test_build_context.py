from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from paper2ale.assets import AssetCache, snapshot_asset
from paper2ale.build_context import BuildContext


class BuildContextTests(unittest.TestCase):
    def test_asset_bytes_are_exact_snapshot_and_cache_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "data.json"
            source.write_bytes(b'{"value":7}\n')
            cache = AssetCache(root / "cache")
            snapshot = snapshot_asset(
                source,
                asset_id="dataset",
                kind="dataset",
                cache=cache,
            )
            context = BuildContext.from_project(
                {"asset_snapshots": [snapshot.to_dict()]},
                asset_cache=cache,
            )
            self.assertEqual(
                context.read_asset("dataset", "data.json"), b'{"value":7}\n'
            )
            self.assertNotIn(str(root), str(context.to_dict()))
            self.assertRegex(context.asset_bundle_digest, r"^[0-9a-f]{64}$")
            reordered = BuildContext.from_project(
                {
                    "asset_snapshots": [
                        {
                            "schema_version": "paper2ale.asset-snapshot/v1",
                            "asset_id": "z-empty",
                            "kind": "dataset",
                            "content_sha256": "0" * 64,
                            "size_bytes": 0,
                            "metadata": {},
                            "files": [],
                        },
                        snapshot.to_dict(),
                    ]
                },
                asset_cache=cache,
            )
            reverse = BuildContext.from_project(
                {
                    "asset_snapshots": [
                        snapshot.to_dict(),
                        {
                            "schema_version": "paper2ale.asset-snapshot/v1",
                            "asset_id": "z-empty",
                            "kind": "dataset",
                            "content_sha256": "0" * 64,
                            "size_bytes": 0,
                            "metadata": {},
                            "files": [],
                        },
                    ]
                },
                asset_cache=cache,
            )
            self.assertEqual(
                reordered.asset_bundle_digest, reverse.asset_bundle_digest
            )
            with self.assertRaises(TypeError):
                context.asset_snapshots[0]["files"] = ()

            with self.assertRaisesRegex(KeyError, "no file"):
                context.read_asset("dataset", "missing.json")
            without_cache = BuildContext.from_project(
                {"asset_snapshots": [snapshot.to_dict()]}
            )
            with self.assertRaisesRegex(RuntimeError, "no AssetCache"):
                without_cache.read_asset("dataset", "data.json")


if __name__ == "__main__":
    unittest.main()
