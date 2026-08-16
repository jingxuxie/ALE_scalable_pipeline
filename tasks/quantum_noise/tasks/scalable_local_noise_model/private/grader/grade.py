#!/usr/bin/env python3
"""Private behavioral evaluator for the scalable local noise model task."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

import core


TASK_ROOT = Path(__file__).resolve().parents[2]
HIDDEN_ROOT = TASK_ROOT / "private" / "hidden_inputs"
TRUTH_ROOT = TASK_ROOT / "private" / "reference" / "truth"
SOURCE_LIMIT = 512_000
CASE_TIMEOUT_SECONDS = 45.0

# Private scientific calibration. Values are intentionally absent from TASK.md.
MODEL_EXCELLENT = 0.045
MODEL_MINIMUM = 0.160
QUERY_EXCELLENT = 0.055
QUERY_MINIMUM = 0.260
SIDECAR_ABSOLUTE = 3.0e-10
SIDECAR_RELATIVE = 3.0e-8
DIAGNOSTIC_ABSOLUTE = 5.0e-9
DIAGNOSTIC_RELATIVE = 2.0e-7
PER_CASE_MODEL_FLOOR = 0.40
PER_CASE_QUERY_FLOOR = 0.40
TOPOLOGY_MODEL_FLOOR = 0.50
TOPOLOGY_QUERY_FLOOR = 0.45


AUDIT_WRAPPER = r'''
import json, os, runpy, sys
import numpy as _trusted_numpy

sys.dont_write_bytecode = True

def install_policy(solution_arg, input_arg, output_arg):
    Str, Bytes, Int = str, bytes, int
    is_instance, any_value, length, as_bool, set_attribute = isinstance, any, len, bool, setattr
    PolicyDenied, TypeError_, ValueError_, OSError_ = PermissionError, TypeError, ValueError, OSError
    fspath = os.fspath
    filesystem_encoding = sys.getfilesystemencoding()
    path_module = os.path
    realpath, abspath = path_module.realpath, path_module.abspath
    commonpath, dirname, isabs = path_module.commonpath, path_module.dirname, path_module.isabs
    write_flag_mask = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
    os_policy_items = tuple(os.__dict__.items())
    path_policy_items = tuple(path_module.__dict__.items())

    def fsdecode(raw):
        value = fspath(raw)
        return value.decode(filesystem_encoding, "surrogateescape") if is_instance(value, Bytes) else value

    solution = realpath(abspath(fsdecode(solution_arg)))
    input_dir = realpath(abspath(fsdecode(input_arg)))
    output_dir = realpath(abspath(fsdecode(output_arg)))
    python_root = realpath(abspath(fsdecode(sys.base_prefix)))
    allowed_reads = (realpath(dirname(solution)), input_dir, output_dir, python_root)
    allowed_writes = (output_dir,)
    denied_prefixes = (
        "winreg.", "ctypes.", "_winapi.", "_posixsubprocess.",
        "socket.", "subprocess.", "fcntl.", "msvcrt.", "mmap.", "_thread.", "threading.",
    )
    denied_events = {
        "os.system", "os.posix_spawn", "os.spawn", "os.startfile", "os.fork", "os.forkpty",
        "os.exec", "os.kill", "os.killpg", "os.putenv", "os.unsetenv", "os.add_dll_directory",
        "sys.settrace", "sys.setprofile", "_thread.start_new_thread",
    }
    allowed_single_mutations = {"os.remove": 1, "os.unlink": 1, "os.rmdir": 1, "os.mkdir": 2, "os.truncate": None}
    denied_mutations = {
        "os.link", "os.symlink", "os.ftruncate", "os.chdir", "os.fchdir",
        "os.chmod", "os.chown", "os.lchown", "os.utime", "os.mknod", "os.mkfifo",
        "os.setxattr", "os.removexattr",
    }

    def restore_dependencies():
        for name, value in os_policy_items:
            set_attribute(os, name, value)
        for name, value in path_policy_items:
            set_attribute(path_module, name, value)

    def under(path, root):
        try:
            return commonpath((path, root)) == root
        except (ValueError_, OSError_):
            return False

    def classify_write(mode):
        if is_instance(mode, Str):
            return any_value(flag in mode for flag in "wax+")
        return as_bool(mode & write_flag_mask) if is_instance(mode, Int) else False

    def normalized_path(raw):
        if not is_instance(raw, (Str, Bytes)):
            return None
        try:
            return realpath(abspath(fsdecode(raw)))
        except (TypeError_, ValueError_, OSError_):
            return None

    def require_write_path(raw, event):
        path = normalized_path(raw)
        if path is None or not any_value(under(path, root) for root in allowed_writes):
            raise PolicyDenied("clean-room policy denied mutation " + event)

    def nondefault_dir_fd(args, index):
        return length(args) > index and args[index] not in {None, -1}

    def audit(event, args):
        restore_dependencies()
        if event.startswith(denied_prefixes) or event in denied_events:
            raise PolicyDenied("clean-room policy denied " + event)
        if event in {"object.__setattr__", "object.__delattr__"} and length(args) > 1 and args[1] in {
            "__code__", "__defaults__", "__kwdefaults__", "__globals__",
        }:
            raise PolicyDenied("clean-room policy denied policy-object mutation")
        if event == "open" and (not args or not is_instance(args[0], (Str, Bytes, Int))):
            raise PolicyDenied("clean-room policy denied unknown open target")
        if event == "open" and args and is_instance(args[0], Int):
            raise PolicyDenied("clean-room policy denied descriptor open")
        if event == "open" and args and is_instance(args[0], (Str, Bytes)):
            path = normalized_path(args[0])
            write_access = classify_write(args[1] if length(args) > 1 else "r")
            write_access = write_access or (length(args) > 2 and classify_write(args[2]))
            if length(args) > 1 and args[1] is None and not isabs(fsdecode(args[0])):
                raise PolicyDenied("clean-room policy denied relative os.open")
            roots = allowed_writes if write_access else allowed_reads
            if path is None or not any_value(under(path, root) for root in roots):
                raise PolicyDenied("clean-room policy denied file access")
        if event in {"os.listdir", "os.scandir"}:
            if not args or args[0] is None or is_instance(args[0], Int):
                raise PolicyDenied("clean-room policy denied descriptor/default directory access")
            if not is_instance(args[0], (Str, Bytes)):
                raise PolicyDenied("clean-room policy denied unknown directory target")
            if is_instance(args[0], (Str, Bytes)):
                path = normalized_path(args[0])
                if path is None or not any_value(under(path, root) for root in allowed_reads + allowed_writes):
                    raise PolicyDenied("clean-room policy denied directory access")
        if event in allowed_single_mutations:
            if not args:
                raise PolicyDenied("clean-room policy denied mutation " + event)
            dir_fd_index = allowed_single_mutations[event]
            if dir_fd_index is not None and nondefault_dir_fd(args, dir_fd_index):
                raise PolicyDenied("clean-room policy denied dir_fd mutation " + event)
            require_write_path(args[0], event)
        if event in {"os.rename", "os.replace"}:
            if length(args) < 2 or nondefault_dir_fd(args, 2) or nondefault_dir_fd(args, 3):
                raise PolicyDenied("clean-room policy denied rename/replace")
            require_write_path(args[0], event)
            require_write_path(args[1], event)
        if event in denied_mutations:
            raise PolicyDenied("clean-room policy denied mutation " + event)

    sys.addaudithook(audit)
    return solution, input_dir, output_dir

solution, input_dir, output_dir = install_policy(sys.argv[1], sys.argv[2], sys.argv[3])
del install_policy

class CapState:
    def __init__(self):
        self.remaining = 65536
    def consume(self, size):
        if size > self.remaining:
            raise RuntimeError("stdout/stderr limit exceeded")
        self.remaining -= size

class BinaryCapped:
    def __init__(self, wrapped, state):
        self.wrapped, self.state = wrapped, state
    def write(self, value):
        self.state.consume(len(value))
        return self.wrapped.write(value)
    def flush(self):
        return self.wrapped.flush()
    def __getattr__(self, name):
        return getattr(self.wrapped, name)

class Capped:
    def __init__(self, wrapped):
        self.wrapped, self.state = wrapped, CapState()
        self.buffer = BinaryCapped(wrapped.buffer, self.state)
    def write(self, value):
        self.state.consume(len(value.encode(self.wrapped.encoding or "utf-8", self.wrapped.errors or "strict")))
        return self.wrapped.write(value)
    def flush(self):
        return self.wrapped.flush()
    def __getattr__(self, name):
        return getattr(self.wrapped, name)
sys.stdout = sys.__stdout__ = Capped(sys.stdout)
sys.stderr = sys.__stderr__ = Capped(sys.stderr)
sys.argv = [solution, "--input", input_dir, "--output", output_dir]
runpy.run_path(solution, run_name="__main__")
'''


def failed_result(message: str) -> dict[str, Any]:
    return {
        "hard_gates": {"passed": False, "failures": [message]},
        "metrics": {},
        "case_results": [],
        "total_score": 0.0,
        "passed": False,
    }


def validate_source(submission_dir: Path) -> Path:
    try:
        info = submission_dir.lstat()
        reparse = bool(getattr(info, "st_file_attributes", 0) & 0x400)
        if stat.S_ISLNK(info.st_mode) or reparse or not stat.S_ISDIR(info.st_mode):
            raise core.SubmissionError("submission root must be a real directory")
        entries = list(submission_dir.iterdir())
    except core.SubmissionError:
        raise
    except OSError as exc:
        raise core.SubmissionError("submission directory is unreadable") from exc
    if {entry.name for entry in entries} != {"solution.py"}:
        raise core.SubmissionError("submission must contain exactly solution.py")
    source = submission_dir / "solution.py"
    try:
        source_info = source.lstat()
        reparse = bool(getattr(source_info, "st_file_attributes", 0) & 0x400)
        if (
            stat.S_ISLNK(source_info.st_mode)
            or reparse
            or not stat.S_ISREG(source_info.st_mode)
            or source_info.st_nlink > 1
            or source_info.st_size > SOURCE_LIMIT
        ):
            raise core.SubmissionError("solution.py must be one bounded regular non-linked file")
        source_text = source.read_text(encoding="utf-8")
        compile(source_text, "solution.py", "exec")
    except core.SubmissionError:
        raise
    except (OSError, UnicodeError, SyntaxError) as exc:
        raise core.SubmissionError(f"solution.py failed source validation: {type(exc).__name__}") from exc
    return source


def lexical_absolute(path: Path) -> Path:
    """Make a CLI path absolute without dereferencing its final link."""
    return Path(os.path.abspath(os.fspath(path)))


def clean_environment(hash_seed: str) -> dict[str, str]:
    keep = {"SYSTEMROOT", "WINDIR"}
    environment = {key: value for key, value in os.environ.items() if key.upper() in keep}
    environment.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTHONHASHSEED": hash_seed,
            "OPENBLAS_NUM_THREADS": "1",
            "OMP_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
        }
    )
    return environment


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def protected_tree_snapshot(root: Path, excluded: Path | None = None) -> tuple[tuple[Any, ...], ...]:
    root = lexical_absolute(root)
    excluded = lexical_absolute(excluded) if excluded is not None else None
    records: list[tuple[Any, ...]] = []
    try:
        paths = [root, *sorted(root.rglob("*"), key=lambda path: path.relative_to(root).as_posix())]
        for path in paths:
            if excluded is not None and (path == excluded or excluded in path.parents):
                continue
            info = path.lstat()
            relative = "." if path == root else path.relative_to(root).as_posix()
            reparse = bool(getattr(info, "st_file_attributes", 0) & 0x400)
            if stat.S_ISREG(info.st_mode):
                records.append((relative, "file", info.st_size, info.st_nlink, reparse, _file_digest(path)))
            elif stat.S_ISDIR(info.st_mode):
                records.append((relative, "directory", reparse))
            elif stat.S_ISLNK(info.st_mode):
                records.append((relative, "symlink", os.readlink(path)))
            else:
                records.append((relative, "other", info.st_mode, reparse))
    except OSError as exc:
        raise core.SubmissionError("protected filesystem state became unreadable") from exc
    return tuple(records)


def execute_case(source: Path, input_dir: Path, output_dir: Path, hash_seed: str) -> None:
    command = [sys.executable, "-P", "-B", "-s", "-c", AUDIT_WRAPPER, str(source), str(input_dir), str(output_dir)]
    source_before = protected_tree_snapshot(source.parent)
    input_before = protected_tree_snapshot(input_dir)
    case_before = protected_tree_snapshot(output_dir.parent, excluded=output_dir)

    def assert_protected_state() -> None:
        if (
            protected_tree_snapshot(source.parent) != source_before
            or protected_tree_snapshot(input_dir) != input_before
            or protected_tree_snapshot(output_dir.parent, excluded=output_dir) != case_before
        ):
            raise core.SubmissionError("solver modified protected source, input, or case-root state")

    try:
        completed = subprocess.run(
            command,
            cwd=output_dir.parent,
            env=clean_environment(hash_seed),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=CASE_TIMEOUT_SECONDS,
            check=False,
            shell=False,
            close_fds=True,
        )
    except subprocess.TimeoutExpired as exc:
        assert_protected_state()
        raise core.SubmissionError("solver exceeded the per-instance time limit") from exc
    assert_protected_state()
    if completed.returncode != 0:
        raise core.SubmissionError("solver process exited unsuccessfully")
    if len(completed.stdout.encode("utf-8")) > 65_536 or len(completed.stderr.encode("utf-8")) > 65_536:
        raise core.SubmissionError("solver stdout/stderr exceeded its cap")


def _prepare_truth(instance: dict[str, Any], truth_doc: dict[str, Any]) -> dict[str, Any]:
    model = truth_doc["true_model"]
    return core.validate_model(model, instance)


def _mean_hellinger(actual: dict[str, np.ndarray], expected: dict[str, np.ndarray]) -> float:
    errors = []
    for cid in sorted(expected):
        p = np.clip(actual[cid], 0.0, 1.0)
        q = np.clip(expected[cid], 0.0, 1.0)
        errors.append(math.sqrt(0.5 * float(np.sum((np.sqrt(p) - np.sqrt(q)) ** 2))))
    return float(np.mean(errors))


def _numeric_consistency(actual: list[float], expected: list[float], absolute: float, relative: float) -> tuple[float, float]:
    if not actual:
        return 1.0, 0.0
    error = core.normalized_error(
        np.asarray(actual, dtype=np.float64),
        np.asarray(expected, dtype=np.float64),
        absolute,
        relative,
    )
    return core.linear_score(error, excellent=1.0, minimum=25.0), error


def score_case(
    instance: dict[str, Any], outputs: dict[str, Any], truth_doc: dict[str, Any]
) -> dict[str, Any]:
    submitted_model = outputs["model"]
    truth_model = _prepare_truth(instance, truth_doc)
    submitted_marginals = core.clique_marginals(instance, submitted_model)
    truth_marginals = core.clique_marginals(instance, truth_model)
    model_error = _mean_hellinger(submitted_marginals, truth_marginals)
    model_score = core.linear_score(model_error, MODEL_EXCELLENT, MODEL_MINIMUM)

    submitted_private = []
    expected_private = []
    for query in truth_doc["private_queries"]:
        submitted_private.append(core.evidence_probability(instance, submitted_model, query["assignment"]))
        expected_private.append(core.evidence_probability(instance, truth_model, query["assignment"]))
    clipped_actual = np.clip(np.asarray(submitted_private), 1.0e-14, 1.0)
    clipped_expected = np.clip(np.asarray(expected_private), 1.0e-14, 1.0)
    query_error = float(np.sqrt(np.mean((np.log(clipped_actual) - np.log(clipped_expected)) ** 2)))
    query_score = core.linear_score(query_error, QUERY_EXCELLENT, QUERY_MINIMUM)

    recomputed_public = [
        core.evidence_probability(instance, submitted_model, row["assignment"])
        for row in instance["_queries"]
    ]
    sidecar_score, sidecar_error = _numeric_consistency(
        [row["probability"] for row in outputs["queries"]],
        recomputed_public,
        SIDECAR_ABSOLUTE,
        SIDECAR_RELATIVE,
    )

    expected_audit_rows, expected_flagged = core.audit_records(instance, submitted_model)
    actual_audit_rows = outputs["audit"]["interactions"]
    audit_values_actual: list[float] = []
    audit_values_expected: list[float] = []
    audit_discrete = outputs["audit"]["flagged_interaction_ids"] == expected_flagged
    for actual, expected in zip(actual_audit_rows, expected_audit_rows):
        audit_values_actual.extend(
            [float(actual["predicted_probability"]), float(actual["z_score"]), float(actual["absolute_z"])]
        )
        audit_values_expected.extend(
            [float(expected["predicted_probability"]), float(expected["z_score"]), float(expected["absolute_z"])]
        )
        audit_discrete = audit_discrete and actual["rank"] == expected["rank"]
    audit_numeric_score, audit_numeric_error = _numeric_consistency(
        audit_values_actual, audit_values_expected, 8.0e-9, 3.0e-7
    )
    audit_consistency_score = audit_numeric_score if audit_discrete else 0.0

    ranked_ids = [
        row["interaction_id"]
        for row in sorted(actual_audit_rows, key=lambda row: (int(row["rank"]), row["interaction_id"]))
    ]
    positives = set(truth_doc["anomaly_ids"])
    anomaly_ap = core.average_precision(ranked_ids, positives)
    top_ids = set(ranked_ids[: max(1, len(positives))])
    anomaly_recall = 1.0 if not positives else len(top_ids & positives) / len(positives)
    anomaly_score = 0.6 * anomaly_ap + 0.4 * anomaly_recall

    expected_diagnostics = core.compute_diagnostics(instance, submitted_model)
    diagnostic_keys = [
        "factor_max_normalization_error", "weighted_clique_tv_to_smoothed_counts",
        "max_raw_separator_tv", "max_model_separator_tv",
    ]
    diagnostics_score, diagnostics_error = _numeric_consistency(
        [float(outputs["diagnostics"][key]) for key in diagnostic_keys],
        [float(expected_diagnostics[key]) for key in diagnostic_keys],
        DIAGNOSTIC_ABSOLUTE,
        DIAGNOSTIC_RELATIVE,
    )

    return {
        "instance_id": instance["instance_id"],
        "category": truth_doc["category"],
        "topology": truth_doc["topology"],
        "model_recovery": {"score": model_score, "mean_hellinger": model_error},
        "heldout_queries": {"score": query_score, "log_rmse": query_error},
        "query_model_consistency": {"score": sidecar_score, "normalized_rmse": sidecar_error},
        "audit_consistency": {"score": audit_consistency_score, "normalized_rmse": audit_numeric_error},
        "anomaly_ranking": {"score": anomaly_score, "average_precision": anomaly_ap, "top_recall": anomaly_recall},
        "diagnostics_consistency": {"score": diagnostics_score, "normalized_rmse": diagnostics_error},
    }


def aggregate(case_results: list[dict[str, Any]]) -> dict[str, Any]:
    metric_names = [
        "model_recovery", "heldout_queries", "query_model_consistency",
        "audit_consistency", "anomaly_ranking", "diagnostics_consistency",
    ]
    macro_scores = {
        metric: float(np.mean([case[metric]["score"] for case in case_results]))
        for metric in metric_names
    }
    categories: dict[str, list[dict[str, Any]]] = {}
    for case in case_results:
        categories.setdefault(case["category"], []).append(case)
    category_scores = {
        category: {
            "model_recovery": float(np.mean([case["model_recovery"]["score"] for case in cases])),
            "heldout_queries": float(np.mean([case["heldout_queries"]["score"] for case in cases])),
        }
        for category, cases in sorted(categories.items())
    }
    topologies: dict[str, list[dict[str, Any]]] = {}
    for case in case_results:
        topologies.setdefault(case["topology"], []).append(case)
    topology_scores = {
        topology: {
            "model_recovery": float(np.mean([case["model_recovery"]["score"] for case in cases])),
            "heldout_queries": float(np.mean([case["heldout_queries"]["score"] for case in cases])),
        }
        for topology, cases in sorted(topologies.items())
    }
    weights = {
        "model_recovery": 0.35,
        "heldout_queries": 0.27,
        "query_model_consistency": 0.10,
        "audit_consistency": 0.08,
        "anomaly_ranking": 0.15,
        "diagnostics_consistency": 0.05,
    }
    total = float(sum(weights[name] * macro_scores[name] for name in weights))
    anomaly_categories = [name for name in categories if "anomaly" in name or "ood" in name]
    category_gate = all(
        category_scores[name]["model_recovery"] >= 0.50
        and category_scores[name]["heldout_queries"] >= 0.45
        for name in category_scores
    )
    topology_gate = all(
        topology_scores[name]["model_recovery"] >= TOPOLOGY_MODEL_FLOOR
        and topology_scores[name]["heldout_queries"] >= TOPOLOGY_QUERY_FLOOR
        for name in topology_scores
    )
    case_floor_failures = [
        {
            "instance_id": case["instance_id"],
            "topology": case["topology"],
            "model_recovery": case["model_recovery"]["score"],
            "heldout_queries": case["heldout_queries"]["score"],
        }
        for case in case_results
        if case["model_recovery"]["score"] < PER_CASE_MODEL_FLOOR
        or case["heldout_queries"]["score"] < PER_CASE_QUERY_FLOOR
    ]
    passed = bool(
        total >= 0.82
        and macro_scores["model_recovery"] >= 0.72
        and macro_scores["heldout_queries"] >= 0.68
        and macro_scores["query_model_consistency"] >= 0.98
        and macro_scores["audit_consistency"] >= 0.98
        and macro_scores["diagnostics_consistency"] >= 0.98
        and all(
            float(np.mean([case["anomaly_ranking"]["score"] for case in categories[name]])) >= 0.65
            for name in anomaly_categories
        )
        and category_gate
        and topology_gate
        and not case_floor_failures
    )
    return {
        "metrics": macro_scores,
        "category_scores": category_scores,
        "topology_scores": topology_scores,
        "case_floor_failures": case_floor_failures,
        "total_score": total,
        "passed": passed,
    }


def perturb_validation(input_dir: Path) -> None:
    """Change only binomial outcomes while preserving every public invariant."""
    manifest = core.load_json(input_dir / "manifest.json")
    validation_path = input_dir / manifest["validation_file"]
    rows = core.load_jsonl(validation_path)
    changed = False
    for row in rows:
        replacement = int(row["shots"]) - int(row["successes"])
        if replacement == row["successes"]:
            replacement = row["successes"] + 1 if row["successes"] < row["shots"] else row["successes"] - 1
        changed = changed or replacement != row["successes"]
        row["successes"] = replacement
    if rows and not changed:
        raise RuntimeError("validation perturbation did not change an outcome")
    core.dump_jsonl(validation_path, rows)


def enforce_validation_isolation(primary_dir: Path, paired_dir: Path) -> None:
    primary_model = core.load_json(primary_dir / "model.json")
    paired_model = core.load_json(paired_dir / "model.json")
    primary_queries = core.load_jsonl(primary_dir / "query_results.jsonl")
    paired_queries = core.load_jsonl(paired_dir / "query_results.jsonl")
    primary_diagnostics = core.load_json(primary_dir / "diagnostics.json")
    paired_diagnostics = core.load_json(paired_dir / "diagnostics.json")
    if primary_model != paired_model:
        raise core.SubmissionError("validation isolation failed for model.json")
    if primary_queries != paired_queries:
        raise core.SubmissionError("validation isolation failed for query_results.jsonl")
    if primary_diagnostics != paired_diagnostics:
        raise core.SubmissionError("validation isolation failed for non-audit diagnostics")
    if core.load_json(primary_dir / "audit.json") == core.load_json(paired_dir / "audit.json"):
        raise core.SubmissionError("audit did not respond to changed validation outcomes")


def artifact_signature(output_dir: Path) -> tuple[Any, ...]:
    return (
        core.load_json(output_dir / "model.json"),
        core.load_jsonl(output_dir / "query_results.jsonl"),
        core.load_json(output_dir / "audit.json"),
        core.load_json(output_dir / "diagnostics.json"),
    )


def enforce_same_input_determinism(primary_dir: Path, repeated_dir: Path) -> None:
    if artifact_signature(primary_dir) != artifact_signature(repeated_dir):
        raise core.SubmissionError("same-input determinism failed across hash seeds and working directories")


def grade(submission_dir: Path) -> dict[str, Any]:
    try:
        source = validate_source(submission_dir)
        suite = core.load_json(HIDDEN_ROOT / "suite_manifest.json")
        case_results = []
        with tempfile.TemporaryDirectory(prefix="local-noise-grade-") as temporary:
            temporary_root = Path(temporary)
            isolated_source_root = temporary_root / "submission"
            isolated_source_root.mkdir()
            isolated_source = isolated_source_root / "solution.py"
            shutil.copyfile(source, isolated_source)
            for index, case in enumerate(suite["cases"]):
                case_id = case["instance_id"]
                case_root = temporary_root / f"case-{index:02d}"
                input_copy = case_root / "input"
                output_dir = case_root / "output"
                shutil.copytree(HIDDEN_ROOT / "cases" / case_id, input_copy)
                output_dir.mkdir()
                execute_case(isolated_source, input_copy, output_dir, hash_seed=str(10_003 + index * 97))
                instance = core.load_instance(input_copy)
                outputs = core.load_submission_outputs(output_dir, instance)
                truth_doc = core.load_json(TRUTH_ROOT / f"{case_id}.json")
                case_results.append(score_case(instance, outputs, truth_doc))
                repeated_root = temporary_root / f"case-{index:02d}-determinism-repeat"
                repeated_output = repeated_root / "output"
                repeated_output.mkdir(parents=True)
                execute_case(isolated_source, input_copy, repeated_output, hash_seed=str(90_007 + index * 103))
                core.load_submission_outputs(repeated_output, instance)
                enforce_same_input_determinism(output_dir, repeated_output)
                paired_root = temporary_root / f"case-{index:02d}-validation-pair"
                paired_input = paired_root / "input"
                paired_output = paired_root / "output"
                shutil.copytree(input_copy, paired_input)
                perturb_validation(paired_input)
                paired_output.mkdir()
                execute_case(isolated_source, paired_input, paired_output, hash_seed=str(70_001 + index * 101))
                paired_instance = core.load_instance(paired_input)
                core.load_submission_outputs(paired_output, paired_instance)
                enforce_validation_isolation(output_dir, paired_output)
        aggregate_result = aggregate(case_results)
        return {
            "hard_gates": {"passed": True, "failures": []},
            "metrics": aggregate_result["metrics"],
            "category_scores": aggregate_result["category_scores"],
            "topology_scores": aggregate_result["topology_scores"],
            "case_floor_failures": aggregate_result["case_floor_failures"],
            "case_results": case_results,
            "total_score": aggregate_result["total_score"],
            "passed": aggregate_result["passed"],
        }
    except core.SubmissionError as exc:
        return failed_result(str(exc))
    except Exception as exc:
        return failed_result(f"evaluator failed safely: {type(exc).__name__}: {exc}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--submission", type=Path, required=True)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    result = grade(lexical_absolute(args.submission))
    payload = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.json_out:
        args.json_out.write_bytes(payload.encode("utf-8"))
    sys.stdout.write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
