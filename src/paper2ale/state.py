"""Content-addressed storage and resumable stage state."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import hmac
import json
import math
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
from typing import Any, Iterator, Mapping


class ContentStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, digest: str) -> Path:
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("invalid SHA-256 digest")
        return self.root / "sha256" / digest[:2] / digest[2:]

    def put_bytes(self, data: bytes) -> str:
        if not isinstance(data, bytes):
            raise TypeError("content must be bytes")
        digest = hashlib.sha256(data).hexdigest()
        target = self.path_for(digest)
        if target.exists():
            self._validate_existing(target, digest)
            return digest

        target.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=target.parent,
                prefix=f".{target.name}.tmp-",
                delete=False,
            ) as handle:
                handle.write(data)
                handle.flush()
                temporary = Path(handle.name)
            # Another writer may have committed the same digest while this
            # process wrote its temporary file.  Never trust an existing CAS
            # path solely because its name looks like a digest.
            if target.exists():
                self._validate_existing(target, digest)
            else:
                temporary.replace(target)
                temporary = None
            self._validate_existing(target, digest)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return digest

    def get_bytes(self, digest: str) -> bytes:
        target = self.path_for(digest)
        return self._validate_existing(target, digest)

    @staticmethod
    def _validate_existing(target: Path, expected_digest: str) -> bytes:
        data = target.read_bytes()
        actual_digest = hashlib.sha256(data).hexdigest()
        if not hmac.compare_digest(actual_digest, expected_digest):
            raise IOError(
                f"content store corruption at {target}: expected {expected_digest}, "
                f"got {actual_digest}"
            )
        return data


def _lease_seconds(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("lease_s must be a number")
    lease_s = float(value)
    if not math.isfinite(lease_s) or lease_s <= 0:
        raise ValueError("lease_s must be positive and finite")
    return lease_s


class StageOwnershipError(RuntimeError):
    """Raised when a stage mutation is attempted without current ownership."""


class StageLeaseLostError(StageOwnershipError):
    """Raised when a heartbeat can no longer prove stage ownership."""


class StageLeaseHeartbeat:
    """Periodically renew one running stage lease on its owning worker.

    The background thread only records renewal failure. Callers must invoke
    :meth:`check` at interruption-safe boundaries and before committing work.
    """

    def __init__(
        self,
        store: "StageStateStore",
        stage_key: str,
        owner: str,
        *,
        lease_s: float,
        interval_s: float,
    ) -> None:
        self._store = store
        self.stage_key = stage_key
        self.owner = owner
        self.lease_s = _lease_seconds(lease_s)
        self.interval_s = _lease_seconds(interval_s)
        if self.interval_s >= self.lease_s:
            raise ValueError("heartbeat interval_s must be shorter than lease_s")
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._failure: BaseException | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> "StageLeaseHeartbeat":
        with self._lock:
            if self._thread is not None:
                raise RuntimeError("stage lease heartbeat is already started")
            thread = threading.Thread(
                target=self._run,
                name="paper2ale-stage-lease-heartbeat",
                daemon=True,
            )
            self._thread = thread
        thread.start()
        return self

    def _run(self) -> None:
        while not self._stop.wait(self.interval_s):
            try:
                self._store.renew(
                    self.stage_key,
                    self.owner,
                    lease_s=self.lease_s,
                )
            except BaseException as error:
                with self._lock:
                    self._failure = error
                self._stop.set()
                return

    def check(self) -> None:
        with self._lock:
            failure = self._failure
        if failure is not None:
            raise StageLeaseLostError(
                f"lost ownership of stage lease {self.stage_key}: "
                f"{type(failure).__name__}: {failure}"
            ) from failure

    def stop(self) -> None:
        """Stop renewal without hiding a recorded failure.

        ``stop`` is deliberately non-raising so cleanup cannot mask a build
        exception. Call :meth:`check` explicitly when failure must be surfaced.
        """

        self._stop.set()
        with self._lock:
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join()


class StageStateStore:
    """SQLite WAL store with expiring leases for independent workers."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS stages (
                    stage_key TEXT PRIMARY KEY,
                    stage_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    owner TEXT,
                    lease_until REAL,
                    outputs_json TEXT,
                    error TEXT,
                    updated_at REAL NOT NULL
                )
                """
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30.0, isolation_level=None)
        try:
            yield connection
        finally:
            connection.close()

    def claim(self, stage_key: str, stage_name: str, owner: str, *, lease_s: float = 300.0) -> bool:
        lease_s = _lease_seconds(lease_s)
        now = time.time()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status, owner, lease_until FROM stages WHERE stage_key = ?", (stage_key,)
            ).fetchone()
            if row and row[0] == "succeeded":
                connection.execute("COMMIT")
                return False
            if row and row[0] == "running" and row[2] is not None and row[2] > now and row[1] != owner:
                connection.execute("COMMIT")
                return False
            connection.execute(
                """
                INSERT INTO stages(stage_key, stage_name, status, owner, lease_until, outputs_json, error, updated_at)
                VALUES(?, ?, 'running', ?, ?, NULL, NULL, ?)
                ON CONFLICT(stage_key) DO UPDATE SET
                    stage_name=excluded.stage_name, status='running', owner=excluded.owner,
                    lease_until=excluded.lease_until, outputs_json=NULL, error=NULL, updated_at=excluded.updated_at
                """,
                (stage_key, stage_name, owner, now + lease_s, now),
            )
            connection.execute("COMMIT")
            return True

    def renew(self, stage_key: str, owner: str, *, lease_s: float = 300.0) -> float:
        lease_s = _lease_seconds(lease_s)
        now = time.time()
        lease_until = now + lease_s
        with self._connect() as connection:
            cursor = connection.execute(
                """UPDATE stages SET lease_until=?, updated_at=?
                   WHERE stage_key=? AND owner=? AND status='running'
                     AND lease_until IS NOT NULL AND lease_until>?""",
                (lease_until, now, stage_key, owner, now),
            )
            if cursor.rowcount != 1:
                raise StageOwnershipError(
                    f"cannot renew unowned or expired stage {stage_key}"
                )
        return lease_until

    def heartbeat(
        self,
        stage_key: str,
        owner: str,
        *,
        lease_s: float = 300.0,
        interval_s: float | None = None,
    ) -> StageLeaseHeartbeat:
        """Create an ownership-checked periodic renewal handle."""

        normalized_lease = _lease_seconds(lease_s)
        normalized_interval = (
            normalized_lease / 3.0
            if interval_s is None
            else _lease_seconds(interval_s)
        )
        return StageLeaseHeartbeat(
            self,
            stage_key,
            owner,
            lease_s=normalized_lease,
            interval_s=normalized_interval,
        )

    def finish(self, stage_key: str, owner: str, outputs: Mapping[str, Any]) -> None:
        encoded = json.dumps(
            outputs,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        with self._connect() as connection:
            cursor = connection.execute(
                """UPDATE stages SET status='succeeded', outputs_json=?, lease_until=NULL, updated_at=?
                   WHERE stage_key=? AND owner=? AND status='running'""",
                (encoded, time.time(), stage_key, owner),
            )
            if cursor.rowcount != 1:
                raise StageOwnershipError(f"cannot finish unowned stage {stage_key}")

    def fail(self, stage_key: str, owner: str, error: str) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                """UPDATE stages SET status='failed', error=?, lease_until=NULL, updated_at=?
                   WHERE stage_key=? AND owner=? AND status='running'""",
                (str(error)[-8000:], time.time(), stage_key, owner),
            )
            if cursor.rowcount != 1:
                raise StageOwnershipError(
                    f"cannot fail unowned or non-running stage {stage_key}"
                )

    def get(self, stage_key: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT stage_name,status,owner,lease_until,outputs_json,error,updated_at FROM stages WHERE stage_key=?",
                (stage_key,),
            ).fetchone()
        if row is None:
            return None
        return {
            "stage_name": row[0],
            "status": row[1],
            "owner": row[2],
            "lease_until": row[3],
            "outputs": None if row[4] is None else json.loads(row[4]),
            "error": row[5],
            "updated_at": row[6],
        }

    def invalidate(self, *, stage_key: str) -> None:
        """Forget a non-running record whose committed outputs are unavailable."""

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status FROM stages WHERE stage_key=?", (stage_key,)
            ).fetchone()
            if row is not None and row[0] == "running":
                connection.execute("ROLLBACK")
                raise RuntimeError(f"cannot invalidate running stage {stage_key}")
            connection.execute("DELETE FROM stages WHERE stage_key=?", (stage_key,))
            connection.execute("COMMIT")
