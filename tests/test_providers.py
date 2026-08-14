from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

from paper2ale.providers import (
    CommandProvider,
    CompletionRequest,
    MockProvider,
    ReplayProvider,
)


class ProviderTests(unittest.TestCase):
    def request(self) -> CompletionRequest:
        return CompletionRequest(
            messages=({"role": "user", "content": "x"},),
            output_schema={"type": "object"},
            idempotency_key="request-1",
        )

    def test_mock_records_requests(self) -> None:
        original = {"ok": True, "nested": {"items": [1]}}
        provider = MockProvider([original])
        original["nested"]["items"].append(2)
        response = provider.complete(self.request())
        self.assertEqual(response.data["nested"]["items"], [1])
        with self.assertRaises(TypeError):
            response.data["nested"]["items"].append(3)
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(len(response.raw_digest), 64)

    def test_replay_is_keyed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "replay.json"
            path.write_text(json.dumps({"request-1": {"ok": True}}), encoding="utf-8")
            response = ReplayProvider(path).complete(self.request())
            self.assertEqual(response.data["ok"], True)
            with self.assertRaises(TypeError):
                response.data["ok"] = False
            repeated = ReplayProvider(path).complete(self.request())
            self.assertEqual(repeated.data, response.data)

    def test_replay_jsonl_rejects_duplicate_keys_and_nonfinite_numbers(self) -> None:
        cases = {
            "duplicate request key": (
                '{"idempotency_key":"request-1","data":{}}\n'
                '{"idempotency_key":"request-1","data":{}}\n',
                "duplicate replay idempotency key",
            ),
            "duplicate object key": (
                '{"idempotency_key":"request-1","idempotency_key":"request-2","data":{}}\n',
                "duplicate object key",
            ),
            "nan": (
                '{"idempotency_key":"request-1","data":{"score":NaN}}\n',
                "forbidden numeric constant",
            ),
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "replay.jsonl"
            for name, (text, message) in cases.items():
                with self.subTest(name=name):
                    path.write_text(text, encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, message):
                        ReplayProvider(path)

    def test_replay_file_size_is_bounded_before_parsing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "replay.json"
            path.write_text('{"request-1":{"payload":"large"}}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "exceeds the 8-byte limit"):
                ReplayProvider(path, max_bytes=8)
            with self.assertRaisesRegex(ValueError, "positive integer"):
                ReplayProvider(path, max_bytes=0)

    def test_request_is_a_deep_snapshot_and_rejects_nan(self) -> None:
        schema = {"type": "object", "properties": {"x": {"type": "number"}}}
        request = CompletionRequest(
            messages=({"role": "user", "content": "x"},),
            output_schema=schema,
        )
        schema["properties"]["x"]["type"] = "string"
        self.assertEqual(request.output_schema["properties"]["x"]["type"], "number")
        with self.assertRaises(TypeError):
            request.output_schema["properties"]["x"]["type"] = "integer"
        with self.assertRaisesRegex(ValueError, "non-finite"):
            CompletionRequest(
                messages=({"role": "user", "content": "x"},),
                output_schema={"example": float("nan")},
            )

    def test_command_provider_requires_envelope(self) -> None:
        raw_object = CommandProvider(
            [sys.executable, "-c", 'print("{\\\"ok\\\": true}")']
        )
        with self.assertRaisesRegex(ValueError, "explicit response envelope"):
            raw_object.complete(self.request())

        enveloped = CommandProvider(
            [
                sys.executable,
                "-c",
                'print("{\\\"data\\\":{\\\"ok\\\":true},'
                '\\\"usage\\\":{\\\"output_tokens\\\":2},'
                '\\\"finish_reason\\\":\\\"stop\\\"}")',
            ]
        )
        response = enveloped.complete(self.request())
        self.assertTrue(response.data["ok"])
        self.assertEqual(response.usage["output_tokens"], 2)

    def test_command_provider_bounds_output(self) -> None:
        provider = CommandProvider(
            [sys.executable, "-c", "import sys; sys.stdout.write('x' * 128)"],
            max_output_bytes=32,
        )
        with self.assertRaisesRegex(RuntimeError, "stdout exceeded"):
            provider.complete(self.request())


if __name__ == "__main__":
    unittest.main()
