"""Provider-neutral, strict structured-completion adapters.

Provider requests and responses are snapshotted as immutable JSON values.
Replay files reject ambiguous JSON, and command adapters use an explicit,
size-bounded response envelope.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
from pathlib import Path
import subprocess
import threading
from typing import Any, Mapping, Protocol, Sequence


class _FrozenDict(dict):
    """A JSON-serializable dict whose public mutation APIs are disabled."""

    @staticmethod
    def _immutable(*_args: Any, **_kwargs: Any) -> None:
        raise TypeError("structured JSON snapshot is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable


class _FrozenList(list):
    """A JSON-serializable list whose public mutation APIs are disabled."""

    @staticmethod
    def _immutable(*_args: Any, **_kwargs: Any) -> None:
        raise TypeError("structured JSON snapshot is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    append = _immutable
    clear = _immutable
    extend = _immutable
    insert = _immutable
    pop = _immutable
    remove = _immutable
    reverse = _immutable
    sort = _immutable
    __iadd__ = _immutable
    __imul__ = _immutable


def _freeze_json(value: Any, path: str = "$") -> Any:
    """Validate a strict JSON value and return an immutable deep snapshot."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path}: non-finite JSON number is not allowed")
        return value
    if isinstance(value, Mapping):
        for key in value:
            if not isinstance(key, str):
                raise TypeError(f"{path}: JSON object keys must be strings")
        return _FrozenDict(
            (key, _freeze_json(value[key], f"{path}.{key}")) for key in sorted(value)
        )
    if isinstance(value, (list, tuple)):
        return _FrozenList(
            _freeze_json(item, f"{path}[{index}]") for index, item in enumerate(value)
        )
    raise TypeError(f"{path}: {type(value).__name__} is not a JSON value")


def _mutable_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _mutable_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_mutable_json(item) for item in value]
    return value


def _canonical(value: Any) -> bytes:
    snapshot = _freeze_json(value)
    return (
        json.dumps(
            snapshot,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _strict_loads(text: str | bytes, *, context: str) -> Any:
    if isinstance(text, bytes):
        try:
            text = text.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"{context} is not valid UTF-8") from exc

    def reject_constant(token: str) -> None:
        raise ValueError(f"{context} contains forbidden numeric constant {token}")

    def object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{context} contains duplicate object key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(
            text,
            object_pairs_hook=object_without_duplicates,
            parse_constant=reject_constant,
        )
    except json.JSONDecodeError as exc:
        raise ValueError(f"{context} is not valid JSON: {exc.msg}") from exc
    return _freeze_json(value)


@dataclass(frozen=True)
class CompletionRequest:
    messages: tuple[Mapping[str, str], ...]
    output_schema: Mapping[str, Any]
    parameters: Mapping[str, Any] = field(default_factory=dict)
    timeout_s: float = 120.0
    idempotency_key: str = ""

    def __post_init__(self) -> None:
        messages = _freeze_json(tuple(self.messages), "$.messages")
        if not messages:
            raise ValueError("completion request requires at least one message")
        for index, message in enumerate(messages):
            if not isinstance(message, Mapping):
                raise TypeError(f"$.messages[{index}] must be an object")
            if not isinstance(message.get("role"), str) or not message["role"]:
                raise ValueError(f"$.messages[{index}].role must be a nonempty string")
            if not isinstance(message.get("content"), str):
                raise TypeError(f"$.messages[{index}].content must be a string")
        output_schema = _freeze_json(self.output_schema, "$.output_schema")
        parameters = _freeze_json(self.parameters, "$.parameters")
        if not isinstance(output_schema, Mapping) or not isinstance(parameters, Mapping):
            raise TypeError("output_schema and parameters must be objects")
        if isinstance(self.timeout_s, bool) or not isinstance(self.timeout_s, (int, float)):
            raise TypeError("timeout_s must be a number")
        timeout_s = float(self.timeout_s)
        if not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("timeout_s must be positive and finite")
        if not isinstance(self.idempotency_key, str):
            raise TypeError("idempotency_key must be a string")
        object.__setattr__(self, "messages", tuple(messages))
        object.__setattr__(self, "output_schema", output_schema)
        object.__setattr__(self, "parameters", parameters)
        object.__setattr__(self, "timeout_s", timeout_s)

    def normalized(self) -> dict[str, Any]:
        body = {
            "messages": _mutable_json(self.messages),
            "output_schema": _mutable_json(self.output_schema),
            "parameters": _mutable_json(self.parameters),
        }
        key = self.idempotency_key or hashlib.sha256(_canonical(body)).hexdigest()
        return {**body, "idempotency_key": key}


@dataclass(frozen=True)
class CompletionResponse:
    data: Mapping[str, Any]
    finish_reason: str = "stop"
    usage: Mapping[str, int] = field(default_factory=dict)
    raw_digest: str = ""

    def __post_init__(self) -> None:
        data = _freeze_json(self.data, "$.data")
        usage = _freeze_json(self.usage, "$.usage")
        if not isinstance(data, Mapping) or not isinstance(usage, Mapping):
            raise TypeError("completion data and usage must be objects")
        for name, amount in usage.items():
            if not isinstance(amount, int) or isinstance(amount, bool) or amount < 0:
                raise ValueError(f"$.usage.{name} must be a nonnegative integer")
        if not isinstance(self.finish_reason, str) or not self.finish_reason:
            raise ValueError("finish_reason must be a nonempty string")
        if not isinstance(self.raw_digest, str):
            raise TypeError("raw_digest must be a string")
        object.__setattr__(self, "data", data)
        object.__setattr__(self, "usage", usage)

    @classmethod
    def from_data(
        cls,
        data: Mapping[str, Any],
        *,
        finish_reason: str = "stop",
        usage: Mapping[str, int] | None = None,
    ) -> "CompletionResponse":
        snapshot = _freeze_json(data)
        if not isinstance(snapshot, Mapping):
            raise TypeError("completion data must be an object")
        return cls(
            data=snapshot,
            finish_reason=finish_reason,
            usage={} if usage is None else usage,
            raw_digest=hashlib.sha256(_canonical(snapshot)).hexdigest(),
        )


class CompletionProvider(Protocol):
    def complete(self, request: CompletionRequest) -> CompletionResponse: ...


class MockProvider:
    """Return immutable queued response snapshots without network access."""

    def __init__(self, responses: Sequence[Mapping[str, Any]]) -> None:
        self._responses = [_canonical(response) for response in responses]
        self.requests: list[CompletionRequest] = []

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        self.requests.append(request)
        if not self._responses:
            raise RuntimeError("mock provider has no response remaining")
        data = _strict_loads(self._responses.pop(0), context="mock response")
        if not isinstance(data, Mapping):
            raise ValueError("mock response must be an object")
        return CompletionResponse.from_data(data)


class ReplayProvider:
    """Replay responses by normalized request idempotency key.

    A replay file is either a JSON object mapping keys to response-data
    objects, or JSONL records with exactly ``idempotency_key`` and ``data``.
    Duplicate keys and non-finite numbers are rejected.
    """

    def __init__(self, path: str | Path) -> None:
        replay_path = Path(path)
        text = replay_path.read_text(encoding="utf-8")
        self._responses: dict[str, bytes] = {}
        if replay_path.suffix.lower() == ".jsonl":
            for line_number, line in enumerate(text.splitlines(), start=1):
                if not line.strip():
                    continue
                record = _strict_loads(
                    line, context=f"replay JSONL line {line_number}"
                )
                if not isinstance(record, Mapping):
                    raise ValueError(f"replay JSONL line {line_number} must be an object")
                if set(record) != {"idempotency_key", "data"}:
                    raise ValueError(
                        f"replay JSONL line {line_number} must contain exactly "
                        "'idempotency_key' and 'data'"
                    )
                self._add_response(record["idempotency_key"], record["data"])
        else:
            value = _strict_loads(text, context="replay JSON")
            if not isinstance(value, Mapping):
                raise ValueError("replay JSON must be an object")
            for key, data in value.items():
                self._add_response(key, data)

    def _add_response(self, key: Any, data: Any) -> None:
        if not isinstance(key, str) or not key:
            raise ValueError("replay idempotency keys must be nonempty strings")
        if key in self._responses:
            raise ValueError(f"duplicate replay idempotency key {key!r}")
        if not isinstance(data, Mapping):
            raise ValueError(f"replay response for {key} must be an object")
        self._responses[key] = _canonical(data)

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        key = request.normalized()["idempotency_key"]
        if key not in self._responses:
            raise KeyError(f"no replay response for request {key}")
        data = _strict_loads(self._responses[key], context=f"replay response {key}")
        if not isinstance(data, Mapping):
            raise ValueError(f"replay response for {key} must be an object")
        return CompletionResponse.from_data(data, finish_reason="replay")


class CommandProvider:
    """Run an adapter command that accepts one JSON request on stdin.

    The adapter must emit the explicit envelope ``{"data": object,
    "usage": object?, "finish_reason": string?}``. Commands run directly with
    ``shell=False``. Captured stdout and stderr have configurable hard limits.
    """

    def __init__(
        self,
        command: Sequence[str],
        *,
        cwd: str | Path | None = None,
        max_output_bytes: int = 4 * 1024 * 1024,
        max_error_bytes: int = 64 * 1024,
    ) -> None:
        if not command or any(not isinstance(part, str) or not part for part in command):
            raise ValueError("command provider requires a non-empty string command")
        for name, value in (
            ("max_output_bytes", max_output_bytes),
            ("max_error_bytes", max_error_bytes),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        self.command = tuple(command)
        self.cwd = None if cwd is None else Path(cwd)
        self.max_output_bytes = max_output_bytes
        self.max_error_bytes = max_error_bytes

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        request_bytes = _canonical(request.normalized())
        process = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self.cwd,
        )
        stdout = bytearray()
        stderr = bytearray()
        overflow: set[str] = set()
        reader_errors: list[BaseException] = []

        def write_input() -> None:
            assert process.stdin is not None
            try:
                process.stdin.write(request_bytes)
                process.stdin.flush()
            except OSError:
                pass
            finally:
                try:
                    process.stdin.close()
                except OSError:
                    pass

        def read_bounded(
            stream: Any, destination: bytearray, limit: int, stream_name: str
        ) -> None:
            try:
                while True:
                    chunk = stream.read(64 * 1024)
                    if not chunk:
                        break
                    remaining = limit - len(destination)
                    if remaining > 0:
                        destination.extend(chunk[:remaining])
                    if len(chunk) > remaining:
                        overflow.add(stream_name)
                        try:
                            process.kill()
                        except OSError:
                            pass
                        break
            except BaseException as exc:  # surfaced on the calling thread below
                reader_errors.append(exc)
                try:
                    process.kill()
                except OSError:
                    pass
            finally:
                stream.close()

        assert process.stdout is not None and process.stderr is not None
        threads = [
            threading.Thread(target=write_input, daemon=True),
            threading.Thread(
                target=read_bounded,
                args=(process.stdout, stdout, self.max_output_bytes, "stdout"),
                daemon=True,
            ),
            threading.Thread(
                target=read_bounded,
                args=(process.stderr, stderr, self.max_error_bytes, "stderr"),
                daemon=True,
            ),
        ]
        for thread in threads:
            thread.start()
        try:
            process.wait(timeout=request.timeout_s)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            for thread in threads:
                thread.join()
            raise
        for thread in threads:
            thread.join()
        if reader_errors:
            raise RuntimeError("completion adapter stream read failed") from reader_errors[0]
        if "stdout" in overflow:
            raise RuntimeError(
                f"completion adapter stdout exceeded {self.max_output_bytes} bytes"
            )
        if "stderr" in overflow:
            raise RuntimeError(
                f"completion adapter stderr exceeded {self.max_error_bytes} bytes"
            )
        if process.returncode != 0:
            error_text = bytes(stderr).decode("utf-8", errors="replace")
            raise RuntimeError(
                f"completion adapter failed with exit {process.returncode}: {error_text}"
            )
        raw_stdout = bytes(stdout)
        payload = _strict_loads(raw_stdout, context="completion adapter response")
        if not isinstance(payload, Mapping):
            raise ValueError("completion adapter response must be an object")
        allowed = {"data", "usage", "finish_reason"}
        unknown = set(payload) - allowed
        if "data" not in payload or unknown:
            detail = "missing 'data'" if "data" not in payload else f"unknown fields {sorted(unknown)}"
            raise ValueError(f"completion adapter must emit an explicit response envelope: {detail}")
        data = payload["data"]
        usage = payload.get("usage", {})
        finish_reason = payload.get("finish_reason", "stop")
        if not isinstance(data, Mapping):
            raise ValueError("completion adapter envelope data must be an object")
        if not isinstance(usage, Mapping):
            raise ValueError("completion adapter envelope usage must be an object")
        if not isinstance(finish_reason, str) or not finish_reason:
            raise ValueError("completion adapter finish_reason must be a nonempty string")
        return CompletionResponse(
            data=data,
            finish_reason=finish_reason,
            usage=usage,
            raw_digest=hashlib.sha256(raw_stdout).hexdigest(),
        )


__all__ = [
    "CommandProvider",
    "CompletionProvider",
    "CompletionRequest",
    "CompletionResponse",
    "MockProvider",
    "ReplayProvider",
]
