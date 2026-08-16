#!/usr/bin/env python3
"""Build an algorithmically distinct valid analyzer."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ALTERNATIVE_PROJECTION = '''def project_simplex(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=np.float64)
    lower = float(values.min() - 1.0)
    upper = float(values.max())
    for _ in range(100):
        midpoint = 0.5 * (lower + upper)
        if float(np.maximum(values - midpoint, 0.0).sum()) > 1.0:
            lower = midpoint
        else:
            upper = midpoint
    projected = np.maximum(values - 0.5 * (lower + upper), 0.0)
    return projected / projected.sum()


'''

ALTERNATIVE_FIT = '''def fit_decay(lengths: np.ndarray, observed: np.ndarray) -> tuple[float, float, float]:
    """Multi-start damped Gauss-Newton fit in amplitude/log-decay coordinates."""
    positive = observed > max(1e-8, 0.02 * float(np.max(np.abs(observed))))
    if int(np.sum(positive)) >= 2:
        design = np.column_stack([np.ones(int(np.sum(positive))), lengths[positive]])
        coefficients = np.linalg.lstsq(design, np.log(observed[positive]), rcond=None)[0]
        initial = (float(np.clip(math.exp(coefficients[0]), 0.01, 1.0)), float(np.clip(-coefficients[1], 0.0, 8.0)))
    else:
        initial = (0.8, 0.3)
    starts = [initial, (0.5, 0.1), (0.8, 0.4), (1.0, 0.8), (0.3, 1.5)]
    best_loss = math.inf
    best_amplitude = 0.0
    best_rate = 0.0
    for amplitude, rate in starts:
        damping = 1e-5
        for _ in range(45):
            basis = np.exp(-rate * lengths)
            prediction = amplitude * basis
            residual = prediction - observed
            jacobian = np.column_stack([basis, -amplitude * lengths * basis])
            normal = jacobian.T @ jacobian + damping * np.eye(2)
            step = np.linalg.solve(normal, jacobian.T @ residual)
            candidate_amplitude = float(np.clip(amplitude - step[0], 0.0, 1.0))
            candidate_rate = float(np.clip(rate - step[1], 0.0, 8.0))
            candidate = candidate_amplitude * np.exp(-candidate_rate * lengths) - observed
            if float(candidate @ candidate) <= float(residual @ residual):
                amplitude, rate = candidate_amplitude, candidate_rate
                damping = max(1e-10, damping * 0.3)
            else:
                damping = min(1e6, damping * 10.0)
        delta = amplitude * np.exp(-rate * lengths) - observed
        loss = float(delta @ delta)
        if loss < best_loss:
            best_loss, best_amplitude, best_rate = loss, amplitude, rate
    eigenvalue = math.exp(-best_rate)
    return best_amplitude, eigenvalue, math.sqrt(best_loss / lengths.size)


'''


def replace_function(source: str, name: str, replacement: str, next_name: str) -> str:
    start = source.index(f"def {name}(")
    end = source.index(f"def {next_name}(", start)
    return source[:start] + replacement + source[end:]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--participant", required=True, type=Path)
    parser.add_argument("--submission", required=True, type=Path)
    arguments = parser.parse_args()
    participant = arguments.participant.resolve()
    manifest = json.loads((participant / "input" / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "spectral-correlation-audit-input/v1":
        raise ValueError("unexpected public input schema")
    base = Path(__file__).resolve().parents[1] / "reference_solver" / "analyze.py"
    source = base.read_text(encoding="utf-8")
    source = replace_function(source, "project_simplex", ALTERNATIVE_PROJECTION, "fit_decay")
    source = replace_function(source, "fit_decay", ALTERNATIVE_FIT, "subset_index")
    submission = arguments.submission.resolve()
    submission.mkdir(parents=True, exist_ok=False)
    (submission / "analyze.py").write_text(source, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
