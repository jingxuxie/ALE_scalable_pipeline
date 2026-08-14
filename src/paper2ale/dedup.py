"""Deterministic exact and near-duplicate screening for task candidates."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
import unicodedata
from typing import Any, Mapping


_TOKEN = re.compile(r"[a-z0-9]+")


def normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return " ".join(_TOKEN.findall(normalized))


def protocol_fingerprint(candidate: Mapping[str, Any]) -> str:
    """Fingerprint the semantic protocol while ignoring display-only wording."""

    semantic = {
        "family": candidate.get("family"),
        "mode": candidate.get("mode"),
        "evidence_ids": sorted(candidate.get("evidence_ids", [])),
        "workflow_nodes": sorted(candidate.get("workflow_nodes", [])),
        "output_contract": candidate.get("output_contract", {}),
        "evaluation": candidate.get("evaluation", {}),
        "resource_budget": candidate.get("resource_budget", {}),
    }
    encoded = json.dumps(semantic, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def simhash64(text: str) -> int:
    tokens = normalize_text(text).split()
    if not tokens:
        return 0
    vector = [0] * 64
    for token in tokens:
        value = int.from_bytes(hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest(), "big")
        for bit in range(64):
            vector[bit] += 1 if value & (1 << bit) else -1
    result = 0
    for bit, weight in enumerate(vector):
        if weight >= 0:
            result |= 1 << bit
    return result


def hamming_distance(left: int, right: int) -> int:
    return (left ^ right).bit_count()


@dataclass(frozen=True)
class DuplicateMatch:
    candidate_id: str
    matched_id: str
    kind: str
    distance: int


class CandidateIndex:
    """Small in-memory index; replaceable by a persistent index at scale."""

    def __init__(self, *, near_distance: int = 6) -> None:
        if not 0 <= near_distance <= 64:
            raise ValueError("near_distance must be between 0 and 64")
        self.near_distance = near_distance
        self._exact: dict[str, str] = {}
        self._simhash: dict[str, int] = {}

    def add(self, candidate: Mapping[str, Any]) -> DuplicateMatch | None:
        candidate_id = str(candidate.get("id", ""))
        if not candidate_id:
            raise ValueError("candidate requires an id")
        fingerprint = protocol_fingerprint(candidate)
        exact = self._exact.get(fingerprint)
        if exact is not None:
            return DuplicateMatch(candidate_id, exact, "exact_protocol", 0)
        text_hash = simhash64(f"{candidate.get('title', '')} {candidate.get('summary', '')}")
        nearest: tuple[str, int] | None = None
        for other_id, other_hash in self._simhash.items():
            distance = hamming_distance(text_hash, other_hash)
            if nearest is None or distance < nearest[1]:
                nearest = (other_id, distance)
        if nearest is not None and nearest[1] <= self.near_distance:
            return DuplicateMatch(candidate_id, nearest[0], "near_text", nearest[1])
        self._exact[fingerprint] = candidate_id
        self._simhash[candidate_id] = text_hash
        return None


__all__ = [
    "CandidateIndex",
    "DuplicateMatch",
    "hamming_distance",
    "normalize_text",
    "protocol_fingerprint",
    "simhash64",
]
