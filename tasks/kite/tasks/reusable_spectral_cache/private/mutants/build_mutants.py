#!/usr/bin/env python3
"""Build deterministic, schema-valid scientific artifact mutants."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
from pathlib import Path

import numpy as np


MUTANTS = {
    "wrong_affine_halfwidth": "uses twice the disclosed affine half-width",
    "recurrence_missing_two": "uses A v[n-1] - v[n-2] instead of 2 A v[n-1] - v[n-2]",
    "extra_probe_normalization": "normalizes unit-modulus probes and still divides by N",
    "kernelized_cache": "stores Jackson-damped coefficients rather than raw moments",
    "shifted_order": "stores order n+1 at slot n",
    "truncated_zero_pad": "computes only 96 moments and pads the reusable suffix with zeros",
    "probe_collapse": "copies probe zero into all probe slots",
    "stale_system_swap": "binds valid cached arrays to the wrong public systems",
    "omit_response_jacobian": "omits the physical 1/a response factor",
    "eta_not_scaled": "uses physical eta directly as the scaled imaginary coordinate",
    "advanced_branch_swap": "swaps retarded and advanced response branches",
    "double_order_zero": "applies the higher-order factor two to order zero",
    "prefix_ignored": "contracts all 384 moments for every public prefix",
    "public_grid_hardcode": "ships exact visible responses with a dummy cache",
    "diagnostics_inconsistent": "fabricates deterministic diagnostic values",
}


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def recurrence_variant(participant: Path, manifest: dict, solver, halfwidth_factor: float, recurrence_factor: float):
    systems = manifest["systems"]
    probe_count = int(manifest["probe_count"])
    moment_count = int(manifest["moment_count"])
    tau = np.empty((len(systems), probe_count, moment_count), dtype=np.complex128)
    for system_index, system in enumerate(systems):
        onsite, edge_i, edge_j, edge_v, probes = solver.read_system(participant, system, probe_count)
        n = int(system["dimension"])
        a = halfwidth_factor * 0.5 * (
            float(system["spectral_upper"]) - float(system["spectral_lower"])
        )
        b = 0.5 * (float(system["spectral_upper"]) + float(system["spectral_lower"]))
        for probe_index, probe in enumerate(probes):
            previous = probe.copy()
            tau[system_index, probe_index, 0] = np.vdot(probe, previous) / n
            current = solver.scaled_matvec(probe, onsite, edge_i, edge_j, edge_v, a, b)
            tau[system_index, probe_index, 1] = np.vdot(probe, current) / n
            for order in range(2, moment_count):
                following = (
                    recurrence_factor
                    * solver.scaled_matvec(current, onsite, edge_i, edge_j, edge_v, a, b)
                    - previous
                )
                tau[system_index, probe_index, order] = np.vdot(probe, following) / n
                previous, current = current, following
    return tau


def write_complete(core, participant: Path, manifest: dict, queries: list[dict], output: Path, tau: np.ndarray):
    output.mkdir(parents=True, exist_ok=False)
    core.write_moments(output / "moments.npz", manifest, tau)
    core.write_response(output / "public_response.csv", queries, core.response_values(tau, manifest, queries))
    core.write_diagnostics(
        output / "diagnostics.json",
        core.compute_diagnostics(participant, manifest, tau, len(queries)),
    )


def altered_query_values(core, tau: np.ndarray, manifest: dict, queries: list[dict], mode: str):
    values = []
    system_index = {item["system_id"]: index for index, item in enumerate(manifest["systems"])}
    for query in queries:
        index = system_index[query["system_id"]]
        system = manifest["systems"][index]
        changed = dict(query)
        if mode == "eta_not_scaled":
            a = 0.5 * (float(system["spectral_upper"]) - float(system["spectral_lower"]))
            changed["eta"] = float(query["eta"]) * a
        elif mode == "advanced_branch_swap":
            if query["kind"] == "GR":
                changed["kind"] = "GA"
            elif query["kind"] == "GA":
                changed["kind"] = "GR"
            else:
                changed["kind"] = "GA"
        elif mode == "prefix_ignored":
            changed["prefix"] = int(manifest["moment_count"])
        base = core.contract_moments(
            np.mean(tau[index], axis=0),
            int(changed["prefix"]),
            changed["kind"],
            float(changed["energy"]),
            float(changed["eta"]),
            float(system["spectral_lower"]),
            float(system["spectral_upper"]),
        )
        if mode == "omit_response_jacobian":
            a = 0.5 * (float(system["spectral_upper"]) - float(system["spectral_lower"]))
            base *= a
        elif mode == "double_order_zero":
            a = 0.5 * (float(system["spectral_upper"]) - float(system["spectral_lower"]))
            b = 0.5 * (float(system["spectral_upper"]) + float(system["spectral_lower"]))
            sigma = -1.0 if query["kind"] == "GA" else 1.0
            z = complex((float(query["energy"]) - b) / a, sigma * float(query["eta"]) / a)
            root, _ = core._decaying_root(z)
            extra = np.mean(tau[index, :, 0]) / (a * root)
            if query["kind"] == "DOS":
                base = complex(base.real - extra.imag / math.pi, 0.0)
            else:
                base += extra
        elif mode == "advanced_branch_swap" and query["kind"] == "DOS":
            base = complex(base.real, 0.0)
        values.append(base)
    return np.asarray(values, dtype=np.complex128)


def build(task_root: Path, output_root: Path) -> None:
    if output_root.exists():
        raise FileExistsError(f"refusing to overwrite existing mutant root: {output_root}")
    core = load_module("mutant_core", task_root / "private" / "grader" / "core.py")
    solver = load_module("mutant_sparse_solver", task_root / "author" / "reference_solver" / "solve.py")
    participant = task_root / "participant"
    manifest = core.load_manifest(participant)
    queries = core.load_queries(participant / "input" / manifest["public_queries_file"])
    reference = core.load_moments(
        task_root / "private" / "reference" / "oracle_submission" / "moments.npz",
        manifest,
    )["tau"]
    output_root.mkdir(parents=True)

    scientific_tau: dict[str, np.ndarray] = {}
    scientific_tau["wrong_affine_halfwidth"] = recurrence_variant(
        participant, manifest, solver, halfwidth_factor=2.0, recurrence_factor=2.0
    )
    scientific_tau["recurrence_missing_two"] = recurrence_variant(
        participant, manifest, solver, halfwidth_factor=1.0, recurrence_factor=1.0
    )
    dimensions = np.asarray([item["dimension"] for item in manifest["systems"]], dtype=np.float64)
    scientific_tau["extra_probe_normalization"] = reference / dimensions[:, None, None]
    orders = np.arange(int(manifest["moment_count"]), dtype=np.float64)
    m = int(manifest["moment_count"])
    jackson = (
        (m - orders + 1.0) * np.cos(math.pi * orders / (m + 1.0))
        + np.sin(math.pi * orders / (m + 1.0)) / math.tan(math.pi / (m + 1.0))
    ) / (m + 1.0)
    scientific_tau["kernelized_cache"] = reference * jackson[None, None, :]
    shifted = np.zeros_like(reference)
    shifted[:, :, :-1] = reference[:, :, 1:]
    scientific_tau["shifted_order"] = shifted
    truncated = reference.copy()
    truncated[:, :, 96:] = 0.0
    scientific_tau["truncated_zero_pad"] = truncated
    collapsed = np.repeat(reference[:, :1, :], int(manifest["probe_count"]), axis=1)
    scientific_tau["probe_collapse"] = collapsed
    scientific_tau["stale_system_swap"] = reference[[1, 2, 0], :, :]
    for mutant_id, tau in scientific_tau.items():
        write_complete(core, participant, manifest, queries, output_root / mutant_id, tau)

    for mutant_id in (
        "omit_response_jacobian",
        "eta_not_scaled",
        "advanced_branch_swap",
        "double_order_zero",
        "prefix_ignored",
    ):
        output = output_root / mutant_id
        output.mkdir()
        core.write_moments(output / "moments.npz", manifest, reference)
        core.write_response(
            output / "public_response.csv",
            queries,
            altered_query_values(core, reference, manifest, queries, mutant_id),
        )
        core.write_diagnostics(
            output / "diagnostics.json",
            core.compute_diagnostics(participant, manifest, reference, len(queries)),
        )

    hardcode = output_root / "public_grid_hardcode"
    hardcode.mkdir()
    dummy = np.zeros_like(reference)
    dummy[:, :, 0] = 1.0
    core.write_moments(hardcode / "moments.npz", manifest, dummy)
    (hardcode / "public_response.csv").write_bytes(
        (task_root / "private" / "reference" / "oracle_submission" / "public_response.csv").read_bytes()
    )
    (hardcode / "diagnostics.json").write_bytes(
        (task_root / "private" / "reference" / "oracle_submission" / "diagnostics.json").read_bytes()
    )

    diagnostics_bad = output_root / "diagnostics_inconsistent"
    diagnostics_bad.mkdir()
    core.write_moments(diagnostics_bad / "moments.npz", manifest, reference)
    core.write_response(
        diagnostics_bad / "public_response.csv",
        queries,
        core.response_values(reference, manifest, queries),
    )
    diagnostics = core.compute_diagnostics(participant, manifest, reference, len(queries))
    for index, item in enumerate(diagnostics["systems"]):
        item["tau0_max_abs_error"] = 0.25 + index
        item["max_abs_moment"] = 9.0 + index
    core.write_diagnostics(diagnostics_bad / "diagnostics.json", diagnostics)

    manifest_payload = {
        "schema_version": "spectral-mutant-manifest/v1",
        "expected": "all cases fail",
        "mutants": [
            {"mutant_id": mutant_id, "description": MUTANTS[mutant_id]}
            for mutant_id in sorted(MUTANTS)
        ],
    }
    (output_root / "mutant_manifest.json").write_text(
        json.dumps(manifest_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args()
    task_root = args.task_root.absolute()
    output_root = (
        args.output_root.absolute()
        if args.output_root
        else task_root / "private" / "mutants" / "cases"
    )
    build(task_root, output_root)
    print(json.dumps({"status": "pass", "count": len(MUTANTS), "output": str(output_root)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
