#!/usr/bin/env python3
"""Run all generated robustness probes through the real private evaluator."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
TASK_ROOT = ROOT.parents[1]
GRADER = TASK_ROOT / "private" / "grader" / "grade.py"
MANIFEST = ROOT / "manifest.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=60.0)
    arguments = parser.parse_args()

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    protected = [
        TASK_ROOT / "private" / "grader" / "guarded_runner.py",
        TASK_ROOT / "private" / "reference" / "suite.json",
    ]
    suite = json.loads(protected[1].read_text(encoding="utf-8"))
    if suite.get("cases"):
        relative_input = Path(suite["cases"][0]["input"])
        protected.append((TASK_ROOT / "private" / "reference" / relative_input / "manifest.json").resolve())
    before = {str(path): digest(path) for path in protected}

    results = []
    for probe in manifest["probes"]:
        submission = ROOT / probe["submission"]
        analyzer = submission / "output" / "analyze.py"
        if digest(analyzer) != probe["source_sha256"]:
            raise AssertionError(f"probe source digest drift: {probe['id']}")
        inventory = [path.relative_to(submission).as_posix() for path in submission.rglob("*") if path.is_file()]
        if inventory != manifest["submission_inventory"]:
            raise AssertionError(f"probe inventory drift: {probe['id']}: {inventory}")
        process = subprocess.run(
            [sys.executable, "-B", str(GRADER), "--submission", str(submission)],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=arguments.timeout,
            check=False,
        )
        if process.returncode != 0:
            stderr = process.stderr.decode("utf-8", errors="replace")[-2000:]
            raise AssertionError(f"grader crashed on probe {probe['id']}: {stderr}")
        result = json.loads(process.stdout.decode("utf-8"))
        failures = result.get("hard_gate_failures", [])
        combined = "\n".join(str(value) for value in failures)
        if result.get("passed") is not False or float(result.get("score", -1.0)) != 0.0 or not failures:
            raise AssertionError(f"probe did not fail closed: {probe['id']}: {result}")
        for fragment in probe["expected_failure_fragments"]:
            if fragment not in combined:
                raise AssertionError(
                    f"probe {probe['id']} failed for the wrong reason; missing {fragment!r}: {combined[-1200:]}"
                )
        results.append(
            {
                "id": probe["id"],
                "category": probe["category"],
                "passed": False,
                "score": 0.0,
                "failure": failures[0],
            }
        )

    after = {str(path): digest(path) for path in protected}
    if after != before:
        changed = sorted(path for path in before if before[path] != after[path])
        raise AssertionError(f"security probes mutated protected files: {changed}")

    report = {
        "schema_version": "spectral-scaling-probe-results/v1",
        "all_rejected_safely": True,
        "probe_count": len(results),
        "results": results,
    }
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
