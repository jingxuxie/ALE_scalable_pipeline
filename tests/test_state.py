from __future__ import annotations

from pathlib import Path
import math
import tempfile
import unittest
from unittest import mock

from paper2ale.state import ContentStore, StageStateStore


class StateTests(unittest.TestCase):
    def test_content_store_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ContentStore(directory)
            digest = store.put_bytes(b"evidence")
            self.assertEqual(store.get_bytes(digest), b"evidence")
            self.assertEqual(store.put_bytes(b"evidence"), digest)

    def test_content_store_rejects_corrupt_existing_object(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ContentStore(directory)
            digest = store.put_bytes(b"expected")
            store.path_for(digest).write_bytes(b"tampered")
            with self.assertRaisesRegex(IOError, "content store corruption"):
                store.get_bytes(digest)
            with self.assertRaisesRegex(IOError, "content store corruption"):
                store.put_bytes(b"expected")

    def test_stage_lease_and_finish(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = StageStateStore(Path(directory) / "state.sqlite")
            self.assertTrue(state.claim("key", "stage", "worker-a"))
            self.assertFalse(state.claim("key", "stage", "worker-b"))
            state.finish("key", "worker-a", {"digest": "abc"})
            self.assertEqual(state.get("key")["status"], "succeeded")
            self.assertFalse(state.claim("key", "stage", "worker-b"))

    def test_fail_requires_current_running_owner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = StageStateStore(Path(directory) / "state.sqlite")
            self.assertTrue(state.claim("key", "stage", "worker-a"))
            with self.assertRaisesRegex(RuntimeError, "cannot fail"):
                state.fail("key", "worker-b", "not mine")
            self.assertEqual(state.get("key")["status"], "running")
            state.finish("key", "worker-a", {"ok": True})
            with self.assertRaisesRegex(RuntimeError, "cannot fail"):
                state.fail("key", "worker-a", "too late")
            self.assertEqual(state.get("key")["status"], "succeeded")

    def test_positive_finite_leases_and_renewal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = StageStateStore(Path(directory) / "state.sqlite")
            for bad in (0, -1, math.inf, -math.inf, math.nan):
                with self.subTest(lease_s=bad):
                    with self.assertRaises(ValueError):
                        state.claim("bad", "stage", "worker", lease_s=bad)
            self.assertTrue(state.claim("key", "stage", "worker-a", lease_s=30))
            before = state.get("key")["lease_until"]
            renewed = state.renew("key", "worker-a", lease_s=60)
            self.assertGreater(renewed, before)
            self.assertEqual(state.get("key")["lease_until"], renewed)
            with self.assertRaisesRegex(RuntimeError, "cannot renew"):
                state.renew("key", "worker-b", lease_s=60)
            for bad in (0, math.inf, math.nan):
                with self.subTest(renew_lease_s=bad):
                    with self.assertRaises(ValueError):
                        state.renew("key", "worker-a", lease_s=bad)

    def test_expired_lease_cannot_be_renewed_but_can_be_reclaimed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = StageStateStore(Path(directory) / "state.sqlite")
            with mock.patch("paper2ale.state.time.time", return_value=100.0):
                self.assertTrue(state.claim("key", "stage", "worker-a", lease_s=5))
            with mock.patch("paper2ale.state.time.time", return_value=106.0):
                with self.assertRaisesRegex(RuntimeError, "expired"):
                    state.renew("key", "worker-a", lease_s=5)
                self.assertTrue(state.claim("key", "stage", "worker-b", lease_s=5))
            self.assertEqual(state.get("key")["owner"], "worker-b")


if __name__ == "__main__":
    unittest.main()
