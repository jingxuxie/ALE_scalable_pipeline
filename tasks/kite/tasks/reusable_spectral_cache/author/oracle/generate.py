#!/usr/bin/env python3
"""Deterministically generate public systems and privileged reference artifacts."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import tempfile
from pathlib import Path

import numpy as np


MOMENT_COUNT = 384
PROBE_COUNT = 4


def load_core(task_root: Path):
    path = task_root / "private" / "grader" / "core.py"
    spec = importlib.util.spec_from_file_location("spectral_private_core", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load trusted evaluator core")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def add_edge(edges: dict[tuple[int, int], complex], i: int, j: int, value: complex) -> None:
    if i == j:
        return
    if i > j:
        i, j = j, i
        value = value.conjugate()
    edges[(i, j)] = edges.get((i, j), 0.0j) + value


def system_ring(seed: int = 201_001):
    rng = np.random.default_rng(seed)
    n = 311
    x = np.arange(n, dtype=np.float64)
    onsite = 0.23 + 0.31 * np.sin(2.0 * math.pi * x / n) + rng.uniform(-0.34, 0.34, n)
    edges: dict[tuple[int, int], complex] = {}
    for i in range(n):
        phase = 0.17 + 0.06 * math.sin(2.0 * math.pi * i / n)
        add_edge(edges, i, (i + 1) % n, -1.00 * np.exp(1j * phase))
        add_edge(edges, i, (i + 2) % n, -0.21 * np.exp(-0.5j * phase))
    for _ in range(180):
        i = int(rng.integers(0, n))
        j = int(rng.integers(0, n))
        if i != j and min((i - j) % n, (j - i) % n) > 4:
            add_edge(edges, i, j, rng.uniform(-0.11, 0.11) + 1j * rng.uniform(-0.08, 0.08))
    return "sys_alpha", onsite, edges


def system_grid(seed: int = 202_003):
    rng = np.random.default_rng(seed)
    rows, columns = 23, 23
    n = rows * columns
    onsite = np.empty(n, dtype=np.float64)
    edges: dict[tuple[int, int], complex] = {}
    for row in range(rows):
        for column in range(columns):
            i = row * columns + column
            region = -0.44 if column < columns // 2 else 0.61
            onsite[i] = region + 0.18 * math.cos(0.37 * row) + rng.uniform(-0.27, 0.27)
            if column + 1 < columns:
                phase = 0.045 * row
                add_edge(edges, i, i + 1, -0.83 * np.exp(1j * phase))
            if row + 1 < rows:
                add_edge(edges, i, i + columns, -1.07 + 0.0j)
            if row + 1 < rows and column + 1 < columns and (row + column) % 3 == 0:
                add_edge(edges, i, i + columns + 1, 0.16j if column % 2 else -0.16j)
    return "sys_beta", onsite, edges


def system_layered(seed: int = 203_009):
    rng = np.random.default_rng(seed)
    n = 769
    onsite = np.empty(n, dtype=np.float64)
    edges: dict[tuple[int, int], complex] = {}
    for i in range(n):
        fraction = i / (n - 1)
        if fraction < 0.31:
            base = -0.72
        elif fraction < 0.68:
            base = 0.18
        else:
            base = 0.93
        onsite[i] = base + 0.17 * math.sin(0.11 * i) + rng.uniform(-0.22, 0.22)
        if i + 1 < n:
            add_edge(edges, i, i + 1, (-0.94 + 0.08 * math.sin(0.03 * i)) + 0.04j)
        if i + 3 < n:
            add_edge(edges, i, i + 3, -0.28 - 0.03j * ((i % 5) - 2))
        if i + 17 < n and i % 4 == 0:
            add_edge(edges, i, i + 17, 0.13 * np.exp(1j * (i % 13) / 13.0))
    for _ in range(260):
        i = int(rng.integers(0, n))
        j = int(rng.integers(0, n))
        if abs(i - j) > 20:
            add_edge(edges, i, j, rng.uniform(-0.07, 0.07) + 1j * rng.uniform(-0.05, 0.05))
    return "sys_gamma", onsite, edges


def make_probes(n: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    probes = np.empty((PROBE_COUNT, n), dtype=np.complex128)
    probes[0] = rng.choice(np.asarray([-1.0, 1.0]), size=n)
    probes[1] = rng.choice(np.asarray([-1.0, 1.0]), size=n)
    phases = np.asarray([1.0 + 0.0j, 0.0 + 1.0j, -1.0 + 0.0j, 0.0 - 1.0j])
    probes[2] = rng.choice(phases, size=n)
    probes[3] = rng.choice(phases, size=n)
    return probes


def spectral_bounds(onsite: np.ndarray, edges: dict[tuple[int, int], complex]) -> tuple[float, float]:
    radii = np.zeros(onsite.shape[0], dtype=np.float64)
    for (i, j), value in edges.items():
        radii[i] += abs(value)
        radii[j] += abs(value)
    raw_lower = float(np.min(onsite - radii))
    raw_upper = float(np.max(onsite + radii))
    width = raw_upper - raw_lower
    return raw_lower - 0.10 * width - 0.05, raw_upper + 0.10 * width + 0.05


def dense_matrix(onsite: np.ndarray, edges: dict[tuple[int, int], complex]) -> np.ndarray:
    hamiltonian = np.diag(onsite.astype(np.complex128))
    for (i, j), value in edges.items():
        hamiltonian[i, j] = value
        hamiltonian[j, i] = value.conjugate()
    return hamiltonian


def dense_recurrence_moments(
    hamiltonian: np.ndarray,
    probes: np.ndarray,
    lower: float,
    upper: float,
    moment_count: int = MOMENT_COUNT,
) -> np.ndarray:
    n = hamiltonian.shape[0]
    a = 0.5 * (upper - lower)
    b = 0.5 * (upper + lower)
    scaled = (hamiltonian - b * np.eye(n, dtype=np.complex128)) / a
    tau = np.empty((probes.shape[0], moment_count), dtype=np.complex128)
    for probe_index, probe in enumerate(probes):
        previous = probe.copy()
        tau[probe_index, 0] = np.vdot(probe, previous) / n
        if moment_count == 1:
            continue
        current = scaled @ probe
        tau[probe_index, 1] = np.vdot(probe, current) / n
        for order in range(2, moment_count):
            following = 2.0 * (scaled @ current) - previous
            tau[probe_index, order] = np.vdot(probe, following) / n
            previous, current = current, following
    return tau


def write_csv(path: Path, header: list[str], rows: list[list[object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        for row in rows:
            writer.writerow(row)


def format_number(value: float) -> str:
    return format(float(value), ".17g")


def query_rows(systems: list[dict], private: bool) -> list[dict]:
    queries: list[dict] = []
    for index, system in enumerate(systems):
        lower = float(system["spectral_lower"])
        upper = float(system["spectral_upper"])
        a = 0.5 * (upper - lower)
        b = 0.5 * (upper + lower)
        if private:
            specs = [
                (73, "GR", -0.61, 0.031),
                (157, "DOS", -0.12, 0.047),
                (251, "GA", 0.27, 0.083),
                (319, "GR", 0.69, 0.026),
                (383, "DOS", 0.04, 0.119),
                (211, "GA", -0.78, 0.055),
            ]
            prefix = "hidden"
        else:
            specs = [
                (64, "DOS", -0.43, 0.090),
                (192, "DOS", -0.43, 0.090),
                (384, "DOS", -0.43, 0.090),
                (96, "GR", -0.18, 0.067),
                (96, "GA", -0.18, 0.067),
                (224, "GR", 0.36, 0.045),
                (384, "GA", 0.57, 0.031),
            ]
            prefix = "public"
        for query_index, (moment_prefix, kind, relative_energy, relative_eta) in enumerate(specs):
            queries.append(
                {
                    "query_id": f"{prefix}_{index}_{query_index}",
                    "system_id": system["system_id"],
                    "prefix": moment_prefix,
                    "kind": kind,
                    "energy": b + relative_energy * a,
                    "eta": relative_eta * a,
                }
            )
    return queries


def write_queries(path: Path, queries: list[dict]) -> None:
    rows = []
    for query in queries:
        rows.append(
            [
                query["query_id"],
                query["system_id"],
                query["prefix"],
                query["kind"],
                format_number(query["energy"]),
                format_number(query["eta"]),
            ]
        )
    write_csv(path, ["query_id", "system_id", "prefix", "kind", "energy", "eta"], rows)


def generate(task_root: Path, output_root: Path) -> dict:
    core = load_core(task_root)
    input_root = output_root / "participant" / "input"
    system_root = input_root / "systems"
    hidden_root = output_root / "private" / "hidden_inputs"
    reference_root = output_root / "private" / "reference"
    systems_raw = [system_ring(), system_grid(), system_layered()]
    system_records: list[dict] = []
    tau_parts: list[np.ndarray] = []
    oracle_details: list[dict] = []

    for system_index, (system_id, onsite, edges) in enumerate(systems_raw):
        lower, upper = spectral_bounds(onsite, edges)
        probes = make_probes(onsite.shape[0], 310_000 + system_index * 997)
        relative_dir = Path("systems") / system_id
        onsite_path = system_root / system_id / "onsite.csv"
        edges_path = system_root / system_id / "edges.csv"
        probes_path = system_root / system_id / "probes.csv"
        write_csv(
            onsite_path,
            ["index", "value"],
            [[index, format_number(value)] for index, value in enumerate(onsite)],
        )
        write_csv(
            edges_path,
            ["i", "j", "value_real", "value_imag"],
            [
                [i, j, format_number(value.real), format_number(value.imag)]
                for (i, j), value in sorted(edges.items())
            ],
        )
        probe_rows = []
        for probe_index, probe in enumerate(probes):
            for site_index, value in enumerate(probe):
                probe_rows.append(
                    [probe_index, site_index, format_number(value.real), format_number(value.imag)]
                )
        write_csv(
            probes_path,
            ["probe_id", "index", "value_real", "value_imag"],
            probe_rows,
        )
        record = {
            "system_id": system_id,
            "dimension": int(onsite.shape[0]),
            "probe_count": PROBE_COUNT,
            "spectral_lower": float(lower),
            "spectral_upper": float(upper),
            "onsite_file": (relative_dir / "onsite.csv").as_posix(),
            "edges_file": (relative_dir / "edges.csv").as_posix(),
            "probes_file": (relative_dir / "probes.csv").as_posix(),
            "file_sha256": {
                "onsite": core.sha256_file(onsite_path),
                "edges": core.sha256_file(edges_path),
                "probes": core.sha256_file(probes_path),
            },
        }
        system_records.append(record)
        hamiltonian = dense_matrix(onsite, edges)
        tau_parts.append(dense_recurrence_moments(hamiltonian, probes, lower, upper))
        eigenvalues = np.linalg.eigvalsh(hamiltonian)
        oracle_details.append(
            {
                "system_id": system_id,
                "edge_count": len(edges),
                "actual_eigenvalue_min": float(eigenvalues[0]),
                "actual_eigenvalue_max": float(eigenvalues[-1]),
                "scaled_max_abs_eigenvalue": float(
                    np.max(np.abs((eigenvalues - 0.5 * (upper + lower)) / (0.5 * (upper - lower))))
                ),
            }
        )

    manifest = {
        "schema_version": "spectral-cache-input/v1",
        "moment_count": MOMENT_COUNT,
        "probe_count": PROBE_COUNT,
        "public_queries_file": "public_queries.csv",
        "units": "arbitrary but consistent energy units",
        "systems": system_records,
    }
    input_root.mkdir(parents=True, exist_ok=True)
    (input_root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    public_queries = query_rows(system_records, private=False)
    hidden_queries = query_rows(system_records, private=True)
    write_queries(input_root / "public_queries.csv", public_queries)
    write_queries(hidden_root / "queries.csv", hidden_queries)

    tau = np.stack(tau_parts, axis=0)
    oracle_submission = reference_root / "oracle_submission"
    core.write_moments(oracle_submission / "moments.npz", manifest, tau)
    core.write_response(
        oracle_submission / "public_response.csv",
        public_queries,
        core.response_values(tau, manifest, public_queries),
    )
    core.write_diagnostics(
        oracle_submission / "diagnostics.json",
        core.compute_diagnostics(input_root.parent, manifest, tau, len(public_queries)),
    )
    core.write_response(
        reference_root / "hidden_response.csv",
        hidden_queries,
        core.response_values(tau, manifest, hidden_queries),
    )
    summary = {
        "schema_version": "spectral-oracle-summary/v1",
        "generator": "author/oracle/generate.py",
        "moment_method": "dense Hermitian matrix-vector recurrence",
        "system_details": oracle_details,
        "max_abs_tau_imaginary": float(np.max(np.abs(tau.imag))),
        "max_abs_tau0_error": float(np.max(np.abs(tau[:, :, 0] - 1.0))),
        "public_query_count": len(public_queries),
        "hidden_query_count": len(hidden_queries),
    }
    (reference_root / "oracle_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def generated_paths(root: Path) -> list[Path]:
    paths: list[Path] = []
    for base in (root / "participant" / "input", root / "private" / "hidden_inputs", root / "private" / "reference"):
        if base.exists():
            paths.extend(path for path in base.rglob("*") if path.is_file())
    return sorted(paths)


def numerically_equivalent(left, right, *, atol: float = 1.0e-13, rtol: float = 1.0e-13) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return set(left) == set(right) and all(
            numerically_equivalent(left[key], right[key], atol=atol, rtol=rtol)
            for key in left
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(
            numerically_equivalent(a, b, atol=atol, rtol=rtol)
            for a, b in zip(left, right)
        )
    if isinstance(left, float):
        return math.isfinite(left) and math.isfinite(right) and math.isclose(
            left, right, abs_tol=atol, rel_tol=rtol
        )
    return left == right


def csv_equivalent(left: Path, right: Path) -> bool:
    with left.open(newline="", encoding="utf-8") as left_handle, right.open(
        newline="", encoding="utf-8"
    ) as right_handle:
        left_reader = csv.DictReader(left_handle)
        right_reader = csv.DictReader(right_handle)
        if left_reader.fieldnames != right_reader.fieldnames:
            return False
        left_rows, right_rows = list(left_reader), list(right_reader)
    if len(left_rows) != len(right_rows):
        return False
    for left_row, right_row in zip(left_rows, right_rows):
        for field in left_reader.fieldnames or []:
            a, b = left_row[field], right_row[field]
            try:
                a_float, b_float = float(a), float(b)
            except ValueError:
                if a != b:
                    return False
            else:
                if not (
                    math.isfinite(a_float)
                    and math.isfinite(b_float)
                    and math.isclose(a_float, b_float, abs_tol=1.0e-13, rel_tol=1.0e-13)
                ):
                    return False
    return True


def compare_generated(expected_root: Path, actual_root: Path) -> None:
    expected = {path.relative_to(expected_root).as_posix(): path for path in generated_paths(expected_root)}
    actual = {path.relative_to(actual_root).as_posix(): path for path in generated_paths(actual_root)}
    if set(expected) != set(actual):
        raise RuntimeError(
            f"generated inventory differs: missing={sorted(set(expected)-set(actual))}, "
            f"extra={sorted(set(actual)-set(expected))}"
        )
    for relative in sorted(expected):
        left, right = expected[relative], actual[relative]
        if left.suffix == ".npz":
            with np.load(left, allow_pickle=False) as left_npz, np.load(right, allow_pickle=False) as right_npz:
                if left_npz.files != right_npz.files:
                    raise RuntimeError(f"NPZ keys differ for {relative}")
                for key in left_npz.files:
                    left_array, right_array = left_npz[key], right_npz[key]
                    if left_array.dtype.kind in "fc":
                        equivalent = np.allclose(
                            left_array, right_array, atol=1.0e-13, rtol=1.0e-13
                        )
                    else:
                        equivalent = np.array_equal(left_array, right_array)
                    if not equivalent:
                        raise RuntimeError(f"NPZ array differs for {relative}:{key}")
        elif relative.startswith("private/reference/") and left.suffix == ".csv":
            if not csv_equivalent(left, right):
                raise RuntimeError(f"generated CSV differs for {relative}")
        elif relative.startswith("private/reference/") and left.suffix == ".json":
            left_json = json.loads(left.read_text(encoding="utf-8"))
            right_json = json.loads(right.read_text(encoding="utf-8"))
            if not numerically_equivalent(left_json, right_json):
                raise RuntimeError(f"generated JSON differs for {relative}")
        elif left.read_bytes() != right.read_bytes():
            raise RuntimeError(f"generated text differs for {relative}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--task-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    task_root = args.task_root.absolute()
    if args.check:
        with tempfile.TemporaryDirectory(prefix="spectral-oracle-check-") as temporary:
            generated_root = Path(temporary)
            summary = generate(task_root, generated_root)
            compare_generated(task_root, generated_root)
    else:
        target = args.output_root.absolute() if args.output_root else task_root
        summary = generate(task_root, target)
    print(json.dumps({"status": "pass", "summary": summary}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
