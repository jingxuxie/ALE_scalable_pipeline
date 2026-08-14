"""Hard, paper-grounded Hamiltonian task families for ALE.

This module is deliberately separate from :mod:`paper2ale.task_families.hnn`.
The original family remains a fast smoke suite; these tasks add nonlinear,
multi-degree-of-freedom, compositional, and out-of-distribution challenges.
Participant artifacts are bounded JSON rather than executable model objects,
and evaluator graders independently reconstruct the governing dynamics.
"""

from __future__ import annotations

import hashlib
import json
import textwrap
from typing import Any, Callable

import numpy as np

from paper2ale.difficulty import make_consumption_manifest, resolve_task_difficulty
from paper2ale.packaging import BuildFile


AGENT = "agent"
EVALUATOR = "evaluator"
AUTHOR = "author"

SUPPORTED_TASKS = (
    "hnn-hard-coupled-identification",
    "hnn-hard-variable-nbody",
    "hnn-hard-canonical-recovery",
)

PAPER_TITLE = "Hamiltonian Neural Networks"
PAPER_URL = "https://arxiv.org/abs/1906.01563"
PAPER_PDF_SHA256 = "bd83fe321874ddad9471f83a642ae94ab7412fd9eb0add8caae84a0ee20d168b"
REPO_URL = "https://github.com/greydanus/hamiltonian-nn"
REPO_REVISION = "bcc362235dc623ffe48f22ccc22417e02e9803b4"


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def _text_bytes(value: str) -> bytes:
    return (textwrap.dedent(value).strip() + "\n").encode()


def _file(
    path: str,
    data: bytes | str,
    visibility: str,
    *,
    executable: bool = False,
) -> BuildFile:
    return BuildFile(
        path=path,
        data=data if isinstance(data, bytes) else _text_bytes(data),
        visibility=visibility,
        executable=executable,
    )


def _seed(master_seed: int, task_id: str, index: int, purpose: str = "instance") -> int:
    material = f"hnn-hard-v1\0{master_seed}\0{task_id}\0{index}\0{purpose}".encode()
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big")


def _count(project: dict[str, Any], task: dict[str, Any], instances: int | None) -> int:
    defaults = project.get("defaults", {})
    default = defaults.get("instances", 2) if isinstance(defaults, dict) else 2
    value = task.get("instances", default) if instances is None else instances
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 16:
        raise ValueError("hard-task instances must be an integer between 1 and 16")
    return value


def _task_card(
    task_id: str,
    title: str,
    summary: str,
    count: int,
    output_name: str,
    artifact_format: str,
    difficulty_level: str,
) -> dict[str, Any]:
    return {
        "taskId": f"physical_sciences/{task_id}",
        "title": title,
        "summary": summary,
        "category": "physical_sciences",
        "vm": {
            "snapshot": "cpu-free-ubuntu",
            "vcpus": 4,
            "memory_gb": 16,
            "disk_gb": 200,
            "timeout_s": 1800,
        },
        "paper2ale": {
            "schemaVersion": 1,
            "family": "hnn_hard",
            "familyTaskId": task_id,
            "difficulty": difficulty_level,
            "instanceCount": count,
            "instancePattern": "input/instances/<NNN>/",
            "entrypoint": "main.py",
            "submission": {
                "path": f"output/<NNN>/{output_name}",
                "format": artifact_format,
                "executable": False,
            },
        },
    }


def _ale_main(
    task_id: str,
    count: int,
    input_name: str,
    output_name: str,
    description: str,
) -> str:
    variants = tuple(f"{index:03d}" for index in range(count))
    return f'''
    """Current CUA-Bench task definitions for {task_id}."""

    from __future__ import annotations

    from dataclasses import dataclass
    import json
    import shlex

    import cua_bench as cb
    from tasks.linux_runtime import LinuxTaskConfig


    VARIANTS = {variants!r}
    TASK_DESCRIPTION = {json.dumps(description)}
    INPUT_NAME = {input_name!r}
    OUTPUT_NAME = {output_name!r}


    @dataclass
    class TaskConfig(LinuxTaskConfig):
        DOMAIN_NAME: str = "physical_sciences"
        TASK_NAME: str = "{task_id}"
        VARIANT_NAME: str = "000"

        @property
        def task_description(self) -> str:
            return (
                TASK_DESCRIPTION
                + " Input: " + str(self.input_dir).rstrip("/") + "/" + INPUT_NAME
                + ". Write: " + str(self.remote_output_dir).rstrip("/") + "/" + OUTPUT_NAME
            )


    def _metadata(cfg: TaskConfig, instance_id: str) -> dict:
        metadata = dict(cfg.to_metadata())
        metadata.update({{
            "instance_id": instance_id,
            "input_path": str(cfg.input_dir).rstrip("/") + "/" + INPUT_NAME,
            "grader_path": str(cfg.reference_dir).rstrip("/") + "/grader.py",
            "remote_output_dir": str(cfg.remote_output_dir),
            "submission_path": str(cfg.remote_output_dir).rstrip("/") + "/" + OUTPUT_NAME,
        }})
        return metadata


    @cb.tasks_config(split="train")
    def load():
        tasks = []
        for instance_id in VARIANTS:
            cfg = TaskConfig(VARIANT_NAME=instance_id)
            tasks.append(cb.Task(
                description=cfg.task_description,
                metadata=_metadata(cfg, instance_id),
                computer={{
                    "provider": "computer",
                    "setup_config": {{"os_type": cfg.OS_TYPE}},
                }},
            ))
        return tasks


    @cb.setup_task(split="train")
    async def start(task_cfg, session: cb.DesktopSession):
        await session.run_command(
            "mkdir -p " + shlex.quote(task_cfg.metadata["remote_output_dir"]),
            check=False,
        )


    @cb.evaluate_task(split="train")
    async def evaluate(task_cfg, session: cb.DesktopSession) -> list[float]:
        metadata = task_cfg.metadata
        command = (
            "python3 " + shlex.quote(metadata["grader_path"])
            + " --submission " + shlex.quote(metadata["submission_path"])
            + " --instance " + shlex.quote(metadata["instance_id"])
        )
        completed = await session.run_command(command, check=False)
        stdout = completed.get("stdout", "") if isinstance(completed, dict) else getattr(completed, "stdout", "")
        try:
            begin, end = stdout.find("{{"), stdout.rfind("}}")
            result = json.loads(stdout[begin:end + 1]) if begin >= 0 and end >= begin else {{}}
        except (TypeError, ValueError, json.JSONDecodeError):
            result = {{}}
        return [1.0 if result.get("passed") else 0.0]


    if __name__ == "__main__":
        cb.interact(__file__)
    '''


def _difficulty_settings(project: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    """Map the standard concrete controls to family-specific physical knobs."""

    resolved = resolve_task_difficulty(project, task)
    if resolved is None:
        raise ValueError("hard HNN tasks require an explicit task difficulty selection")
    generator = dict(resolved.generator)
    evaluator = dict(resolved.evaluator)
    input_scale = float(generator["input_complexity_scale"])
    masked_fraction = float(generator["masked_fraction"])
    adversarial_count = int(evaluator["adversarial_case_count"])
    hidden_case_count = int(evaluator["hidden_case_count"])
    required_fraction = float(evaluator["required_pass_fraction"])

    # Each derived value is normalized so the built-in hard profile is 1.0.
    # The mappings make medium/hard/frontier differ in data density, noise,
    # OOD range, horizon, cardinality, close encounters, and score tolerance.
    sample_scale = (input_scale / 1.5) * ((1.0 - 0.25 * masked_fraction) / 0.875)
    ood_scale = (input_scale / 1.5) ** 0.45 * (
        (1.0 + 0.05 * adversarial_count) / 1.2
    )
    threshold_scale = (
        float(evaluator["threshold_scale"]) / 0.75
    ) * (0.9 / required_fraction)
    return {
        "level": resolved.level,
        "profile_id": resolved.profile_id,
        "profile_version": resolved.profile_version,
        "resolution_id": resolved.resolution_id,
        "sample_scale": sample_scale,
        "ood_scale": ood_scale,
        "horizon_scale": float(evaluator["rollout_horizon_scale"]) / 1.5,
        "noise_scale": float(generator["noise_scale"]) / 1.25,
        "threshold_scale": threshold_scale,
        "hidden_case_count": hidden_case_count,
        "adversarial_case_count": adversarial_count,
        "required_pass_fraction": required_fraction,
        "constraint_count": int(generator["constraint_count"]),
        "masked_fraction": masked_fraction,
        "nbody_query_count": max(
            5, 4 + round(hidden_case_count / 8) + round(adversarial_count / 2)
        ),
        "nbody_max_bodies": min(10, 2 + int(generator["constraint_count"])),
        "close_encounter_scale": (1.5 / input_scale)
        * (1.2 / (1.0 + 0.05 * adversarial_count)),
        "generic_generator": generator,
        "generic_evaluator": evaluator,
    }


def _author_files(
    project: dict[str, Any],
    task: dict[str, Any],
    seeds: list[int],
    *,
    generator: dict[str, Any],
    grader: dict[str, Any],
    challenge_axes: list[str],
    mutant_id: str,
    settings: dict[str, Any],
) -> list[BuildFile]:
    task_id = str(task["id"])
    resolved = resolve_task_difficulty(project, task)
    if resolved is None:
        raise ValueError("hard HNN tasks require an explicit task difficulty selection")
    difficulty = make_consumption_manifest(
        resolved,
        resolved.generator,
        resolved.evaluator,
    )
    parameters = {
        "schema_version": "paper2ale.hnn-hard-difficulty-parameters/v1",
        "task_id": task_id,
        "resolution_id": resolved.resolution_id,
        "level": resolved.level,
        "derived_settings": {
            key: value
            for key, value in settings.items()
            if key not in {"generic_generator", "generic_evaluator"}
        },
        "instance_count": len(seeds),
        "instance_seeds": seeds,
        "challenge_axes": challenge_axes,
        "generator_parameters": generator,
        "grader_parameters": grader,
        "registered_mutants": [mutant_id],
    }
    provenance = {
        "schema_version": "paper2ale.provenance/v1",
        "task_id": task_id,
        "paper": {
            "title": PAPER_TITLE,
            "url": PAPER_URL,
            "pdf_sha256": PAPER_PDF_SHA256,
            "grounding": [
                "Equation 2 canonical scalar-gradient dynamics",
                "mass-spring experiment",
                "two-body gravitational experiment",
                "canonical-coordinate representation objective",
            ],
        },
        "official_implementation": {"url": REPO_URL, "revision": REPO_REVISION},
        "difficulty_manifest": "author/difficulty_manifest.json",
        "difficulty_parameters": "author/difficulty_parameters.json",
    }
    evidence = {
        "schema_version": "paper2ale.evidence-instance/v1",
        "task_id": task_id,
        "claims": [
            {
                "id": "canonical-field",
                "statement": "For canonical x=(q,p), f=(dH/dp,-dH/dq).",
                "source_location": "paper Equation 2",
            },
            {
                "id": "hard-extension",
                "statement": "The task composes the paper's structural principle with nonlinear, multi-DOF, or generalization requirements.",
                "source_location": "derived task design",
            },
        ],
    }
    qa = f'''
    # Author QA: {task_id}

    - Participant artifacts are bounded JSON and contain no executable objects.
    - The grader derives hidden truth from evaluator parameters or public query inputs.
    - Every generated instance has a golden artifact and the registered mutant `{mutant_id}`.
    - Paper identity and source URLs are confined to author files.
    - Difficulty settings and consumed generator/grader knobs are machine-readable.
    '''
    return [
        _file("author/difficulty_manifest.json", _json_bytes(difficulty), AUTHOR),
        _file("author/difficulty_parameters.json", _json_bytes(parameters), AUTHOR),
        _file("author/provenance.json", _json_bytes(provenance), AUTHOR),
        _file("author/evidence_graph.json", _json_bytes(evidence), AUTHOR),
        _file("author/qa_notes.md", qa, AUTHOR),
    ]


def _periodic_field(
    states: np.ndarray,
    inverse_mass: np.ndarray,
    onsite: np.ndarray,
    couplings: np.ndarray,
) -> np.ndarray:
    states = np.asarray(states, dtype=float)
    dof = onsite.size
    q, p = states[..., :dof], states[..., dof:]
    dq = p @ inverse_mass.T
    grad_q = onsite * np.sin(q)
    for left in range(dof):
        for right in range(left + 1, dof):
            value = couplings[left, right] * np.sin(q[..., left] - q[..., right])
            grad_q[..., left] += value
            grad_q[..., right] -= value
    return np.concatenate((dq, -grad_q), axis=-1)


def _rk4(
    field: Callable[[np.ndarray], np.ndarray], initial: np.ndarray, times: np.ndarray
) -> np.ndarray:
    trajectory = np.empty((len(times), initial.size), dtype=float)
    trajectory[0] = initial
    for index in range(1, len(times)):
        dt = float(times[index] - times[index - 1])
        state = trajectory[index - 1]
        k1 = field(state[None, :])[0]
        k2 = field((state + 0.5 * dt * k1)[None, :])[0]
        k3 = field((state + 0.5 * dt * k2)[None, :])[0]
        k4 = field((state + dt * k3)[None, :])[0]
        trajectory[index] = state + dt * (k1 + 2 * k2 + 2 * k3 + k4) / 6.0
    return trajectory


def _build_coupled(
    project: dict[str, Any], task: dict[str, Any], master_seed: int, count: int
) -> list[BuildFile]:
    task_id = "hnn-hard-coupled-identification"
    settings = _difficulty_settings(project, task)
    sample_scale = float(settings["sample_scale"])
    ood_scale = float(settings["ood_scale"])
    horizon_scale = float(settings["horizon_scale"])
    noise_scale = float(settings["noise_scale"])
    threshold_scale = float(settings["threshold_scale"])
    train_count = max(120, round(240 * sample_scale))
    validation_count = max(40, round(80 * sample_scale))
    hidden_count = max(
        48, round(4.5 * int(settings["hidden_case_count"]) * sample_scale)
    )
    rollout_count = max(
        4,
        round(
            2
            + int(settings["adversarial_case_count"])
            + 2 * float(settings["required_pass_fraction"])
        ),
    )
    rollout_steps = max(80, round(126 * horizon_scale))
    hidden_q_limit = 2.8 * ood_scale
    files: list[BuildFile] = []
    seeds: list[int] = []
    for index in range(count):
        instance_id = f"{index:03d}"
        seed = _seed(master_seed, task_id, index)
        seeds.append(seed)
        rng = np.random.default_rng(seed)
        dof = 3
        diagonal = rng.uniform(0.75, 1.35, size=dof)
        inverse_mass = np.diag(diagonal)
        inverse_mass[0, 1] = inverse_mass[1, 0] = rng.uniform(0.08, 0.16)
        inverse_mass[1, 2] = inverse_mass[2, 1] = rng.uniform(-0.13, -0.06)
        onsite = rng.uniform(0.8, 1.5, size=dof)
        couplings = np.zeros((dof, dof))
        for left, right in ((0, 1), (1, 2), (0, 2)):
            couplings[left, right] = couplings[right, left] = rng.uniform(0.35, 0.7)

        def sample(number: int, q_limit: float, p_limit: float) -> np.ndarray:
            return np.concatenate(
                (
                    rng.uniform(-q_limit, q_limit, size=(number, dof)),
                    rng.uniform(-p_limit, p_limit, size=(number, dof)),
                ),
                axis=-1,
            )

        train_states = sample(train_count, 0.9, 0.7)
        validation_states = sample(validation_count, 1.2, 0.9)
        noise = (0.004 + 0.001 * index) * noise_scale
        train_derivatives = _periodic_field(
            train_states, inverse_mass, onsite, couplings
        ) + rng.normal(scale=noise, size=train_states.shape)
        validation_derivatives = _periodic_field(
            validation_states, inverse_mass, onsite, couplings
        ) + rng.normal(scale=noise, size=validation_states.shape)
        hidden_states = sample(hidden_count, hidden_q_limit, 1.6 * ood_scale)
        rollout_initials = sample(rollout_count, 2.4 * ood_scale, 0.9 * ood_scale)
        rollout_times = np.linspace(0.0, 5.0 * horizon_scale, rollout_steps)
        public = {
            "schema_version": 1,
            "instance_id": instance_id,
            "coordinate_order": ["q0", "q1", "q2", "p0", "p1", "p2"],
            "model_basis": {
                "hamiltonian": "0.5*p^T*A*p + sum_i a_i*(1-cos(q_i)) + sum_{i<j} c_ij*(1-cos(q_i-q_j))",
                "unknowns": ["symmetric inverse_mass A", "onsite a", "symmetric couplings c with zero diagonal"],
            },
            "train": {
                "states": train_states.tolist(),
                "derivatives": train_derivatives.tolist(),
            },
            "validation": {
                "states": validation_states.tolist(),
                "derivatives": validation_derivatives.tolist(),
            },
            "artifact_contract": {
                "format": "coupled-periodic-hamiltonian-v1",
                "dof": dof,
                "output": f"output/{instance_id}/model.json",
            },
        }
        truth = {
            "schema_version": 1,
            "instance_id": instance_id,
            "parameters": {
                "inverse_mass": inverse_mass.tolist(),
                "onsite": onsite.tolist(),
                "couplings": couplings.tolist(),
            },
            "hidden_states": hidden_states.tolist(),
            "rollout_initial_states": rollout_initials.tolist(),
            "rollout_times": rollout_times.tolist(),
            "thresholds": {
                "field_mse_max": 0.006 * threshold_scale,
                "rollout_mse_max": 0.035 * threshold_scale,
            },
        }
        golden = {
            "format": "coupled-periodic-hamiltonian-v1",
            "dof": dof,
            "inverse_mass": inverse_mass.tolist(),
            "onsite": onsite.tolist(),
            "couplings": couplings.tolist(),
        }
        mutant = json.loads(json.dumps(golden))
        mutant["couplings"] = np.zeros_like(couplings).tolist()
        files.extend(
            [
                _file(f"input/instances/{instance_id}/data.json", _json_bytes(public), AGENT),
                _file(f"reference/instances/{instance_id}/truth.json", _json_bytes(truth), EVALUATOR),
                _file(f"example/instances/{instance_id}/golden.json", _json_bytes(golden), EVALUATOR),
                _file(f"example/instances/{instance_id}/mutant.json", _json_bytes(mutant), EVALUATOR),
            ]
        )

    description = '''
    # Identify a coupled nonlinear Hamiltonian

    Infer a three-degree-of-freedom scalar Hamiltonian from noisy derivative
    observations. The safe JSON model must use the supplied periodic basis.
    Evaluation differentiates your parameters analytically on much wider angle
    and momentum ranges, then integrates long nonlinear rollouts. Validation
    interpolation alone is insufficient: coupling and off-diagonal kinetic
    terms are essential for the hidden regime.

    Complete `software/fit_model.py`, then run it once per instance. Do not
    submit predictions or executable model objects; submit only bounded JSON.
    '''
    starter = '''
    """Starter for safe coupled-periodic parameter identification."""

    from __future__ import annotations

    import argparse
    import json
    from pathlib import Path


    def fit(instance: dict) -> dict:
        # TODO: use train and validation derivatives to estimate every basis coefficient.
        dof = int(instance["artifact_contract"]["dof"])
        return {
            "format": "coupled-periodic-hamiltonian-v1",
            "dof": dof,
            "inverse_mass": [[1.0 if i == j else 0.0 for j in range(dof)] for i in range(dof)],
            "onsite": [1.0] * dof,
            "couplings": [[0.0] * dof for _ in range(dof)],
        }


    def main() -> int:
        parser = argparse.ArgumentParser()
        parser.add_argument("--input", type=Path, required=True)
        parser.add_argument("--output", type=Path, required=True)
        args = parser.parse_args()
        model = fit(json.loads(args.input.read_text(encoding="utf-8")))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(model, indent=2, allow_nan=False) + "\\n", encoding="utf-8")
        return 0


    if __name__ == "__main__":
        raise SystemExit(main())
    '''
    grader = '''
    """Independently evaluate a safe coupled-periodic Hamiltonian artifact."""

    from __future__ import annotations

    import argparse
    import json
    from pathlib import Path
    import sys

    import numpy as np


    def locate(path: Path, instance: str) -> Path:
        candidates = [path, path / "model.json", path / "output" / instance / "model.json", path / instance / "model.json"]
        result = next((item for item in candidates if item.is_file()), None)
        if result is None:
            raise FileNotFoundError("model.json is missing")
        if result.stat().st_size > 1_000_000:
            raise ValueError("model JSON exceeds 1 MB")
        return result


    def parse(path: Path):
        model = json.loads(path.read_text(encoding="utf-8"))
        if set(model) != {"format", "dof", "inverse_mass", "onsite", "couplings"}:
            raise ValueError("model keys do not match the safe contract")
        if model["format"] != "coupled-periodic-hamiltonian-v1" or model["dof"] != 3:
            raise ValueError("wrong model format or degree count")
        inverse_mass = np.asarray(model["inverse_mass"], dtype=float)
        onsite = np.asarray(model["onsite"], dtype=float)
        couplings = np.asarray(model["couplings"], dtype=float)
        if inverse_mass.shape != (3, 3) or couplings.shape != (3, 3) or onsite.shape != (3,):
            raise ValueError("parameter shapes are invalid")
        if not all(np.all(np.isfinite(value)) for value in (inverse_mass, onsite, couplings)):
            raise ValueError("parameters must be finite")
        if not np.allclose(inverse_mass, inverse_mass.T, atol=1e-12) or np.min(np.linalg.eigvalsh(inverse_mass)) <= 0:
            raise ValueError("inverse_mass must be symmetric positive definite")
        if not np.allclose(couplings, couplings.T, atol=1e-12) or not np.allclose(np.diag(couplings), 0.0, atol=1e-12):
            raise ValueError("couplings must be symmetric with zero diagonal")
        if np.max(np.abs(inverse_mass)) > 10 or np.max(np.abs(onsite)) > 10 or np.max(np.abs(couplings)) > 10:
            raise ValueError("parameters exceed safety bounds")
        return inverse_mass, onsite, couplings


    def field(states, inverse_mass, onsite, couplings):
        states = np.asarray(states, dtype=float)
        q, p = states[..., :3], states[..., 3:]
        dq = p @ inverse_mass.T
        grad_q = onsite * np.sin(q)
        for left in range(3):
            for right in range(left + 1, 3):
                value = couplings[left, right] * np.sin(q[..., left] - q[..., right])
                grad_q[..., left] += value
                grad_q[..., right] -= value
        return np.concatenate((dq, -grad_q), axis=-1)


    def rollout(parameters, initial, times):
        trajectory = np.empty((len(times), 6), dtype=float)
        trajectory[0] = initial
        for index in range(1, len(times)):
            dt = float(times[index] - times[index - 1])
            state = trajectory[index - 1]
            k1 = field(state[None], *parameters)[0]
            k2 = field((state + 0.5 * dt * k1)[None], *parameters)[0]
            k3 = field((state + 0.5 * dt * k2)[None], *parameters)[0]
            k4 = field((state + dt * k3)[None], *parameters)[0]
            trajectory[index] = state + dt * (k1 + 2*k2 + 2*k3 + k4) / 6.0
        return trajectory


    def main() -> int:
        parser = argparse.ArgumentParser()
        parser.add_argument("--submission", type=Path, required=True)
        parser.add_argument("--instance", required=True)
        args = parser.parse_args()
        truth_path = Path(__file__).resolve().parent / "instances" / args.instance / "truth.json"
        truth = json.loads(truth_path.read_text(encoding="utf-8"))
        errors, metrics = [], {}
        try:
            predicted_parameters = parse(locate(args.submission, args.instance))
            values = truth["parameters"]
            true_parameters = tuple(np.asarray(values[name], dtype=float) for name in ("inverse_mass", "onsite", "couplings"))
            states = np.asarray(truth["hidden_states"], dtype=float)
            expected = field(states, *true_parameters)
            actual = field(states, *predicted_parameters)
            field_mse = float(np.mean((actual - expected) ** 2))
            times = np.asarray(truth["rollout_times"], dtype=float)
            initials = np.asarray(truth["rollout_initial_states"], dtype=float)
            true_rollouts = np.stack([rollout(true_parameters, value, times) for value in initials])
            predicted_rollouts = np.stack([rollout(predicted_parameters, value, times) for value in initials])
            rollout_mse = float(np.mean((predicted_rollouts - true_rollouts) ** 2))
            metrics = {"field_mse": field_mse, "rollout_mse": rollout_mse}
            if not all(np.isfinite(value) for value in metrics.values()):
                errors.append("metrics are non-finite")
            if field_mse > truth["thresholds"]["field_mse_max"]:
                errors.append("hidden nonlinear field MSE exceeds threshold")
            if rollout_mse > truth["thresholds"]["rollout_mse_max"]:
                errors.append("hidden rollout MSE exceeds threshold")
        except Exception as error:
            errors.append(f"{type(error).__name__}: {error}")
        print(json.dumps({"passed": not errors, "instance": args.instance, "metrics": metrics, "errors": errors}, indent=2))
        return 0 if not errors else 1


    if __name__ == "__main__":
        sys.exit(main())
    '''
    files.extend(
        [
            _file("description.md", description, AGENT),
            _file("task_card.json", _json_bytes(_task_card(task_id, "Identify a coupled nonlinear Hamiltonian", "Recover coupled periodic dynamics and generalize far outside the labeled state range.", count, "model.json", "coupled-periodic-hamiltonian-v1", str(settings["level"]))), AGENT),
            _file("main.py", _ale_main(task_id, count, "data.json", "model.json", "Identify the full coupled periodic Hamiltonian from noisy labeled derivatives; hidden evaluation uses wide-angle states and nonlinear rollouts."), AGENT, executable=True),
            _file("software/fit_model.py", starter, AGENT, executable=True),
            _file("software/requirements.txt", "numpy>=1.26\n", AGENT),
            _file("reference/grader.py", grader, EVALUATOR, executable=True),
        ]
    )
    files.extend(
        _author_files(
            project,
            task,
            seeds,
            generator={"dof": 3, "train_count": train_count, "validation_count": validation_count, "hidden_count": hidden_count, "rollout_count": rollout_count, "rollout_steps": rollout_steps, "train_q_limit": 0.9, "hidden_q_limit": hidden_q_limit, "rollout_horizon": 5.0 * horizon_scale, "label_noise_scale": noise_scale},
            grader={"field_mse_max": 0.006 * threshold_scale, "rollout_mse_max": 0.035 * threshold_scale, "json_byte_limit": 1_000_000},
            challenge_axes=["three degrees of freedom", "nonlinear periodic coupling", "off-diagonal kinetic coupling", "out-of-distribution angles", "long rollouts"],
            mutant_id="remove-all-pair-couplings",
            settings=settings,
        )
    )
    return files


def _nbody_energy_field(
    masses: np.ndarray,
    state: np.ndarray,
    gravitational_constant: float,
    softening: float,
) -> tuple[float, np.ndarray]:
    masses = np.asarray(masses, dtype=float)
    state = np.asarray(state, dtype=float)
    positions, momenta = state[:, :2], state[:, 2:]
    energy = float(np.sum(np.sum(momenta * momenta, axis=-1) / (2.0 * masses)))
    field = np.zeros_like(state)
    field[:, :2] = momenta / masses[:, None]
    for left in range(len(masses)):
        for right in range(left + 1, len(masses)):
            displacement = positions[left] - positions[right]
            squared = float(displacement @ displacement + softening * softening)
            radius = np.sqrt(squared)
            coefficient = gravitational_constant * masses[left] * masses[right]
            energy -= coefficient / radius
            force = -coefficient * displacement / squared**1.5
            field[left, 2:] += force
            field[right, 2:] -= force
    return energy, field


def _build_variable_nbody(
    project: dict[str, Any], task: dict[str, Any], master_seed: int, count: int
) -> list[BuildFile]:
    task_id = "hnn-hard-variable-nbody"
    settings = _difficulty_settings(project, task)
    query_count = int(settings["nbody_query_count"])
    max_bodies = int(settings["nbody_max_bodies"])
    close_scale = float(settings["close_encounter_scale"])
    tolerance = 1e-9 * float(settings["threshold_scale"])
    files: list[BuildFile] = []
    seeds: list[int] = []
    for index in range(count):
        instance_id = f"{index:03d}"
        seed = _seed(master_seed, task_id, index)
        seeds.append(seed)
        rng = np.random.default_rng(seed)
        gravitational_constant = float(rng.uniform(0.65, 1.35))
        softening = float(rng.uniform(0.025, 0.055))

        def make_problem(query_id: str, body_count: int, close: bool = False) -> dict[str, Any]:
            masses = rng.uniform(0.45, 2.2, size=body_count)
            positions = rng.uniform(-1.6, 1.6, size=(body_count, 2))
            if close and body_count >= 2:
                positions[1] = positions[0] + close_scale * np.array([0.035, -0.025])
            momenta = rng.uniform(-0.9, 0.9, size=(body_count, 2))
            momenta -= np.mean(momenta, axis=0, keepdims=True)
            state = np.concatenate((positions, momenta), axis=-1)
            return {
                "query_id": query_id,
                "masses": masses.tolist(),
                "state": state.tolist(),
            }

        examples = [make_problem(f"example-{number}", 2 + number) for number in range(2)]
        labeled_examples = []
        for problem in examples:
            energy, field = _nbody_energy_field(
                np.asarray(problem["masses"]),
                np.asarray(problem["state"]),
                gravitational_constant,
                softening,
            )
            labeled_examples.append(
                {
                    **problem,
                    "expected": {"hamiltonian": energy, "field": field.tolist()},
                }
            )
        queries = [
            make_problem(
                f"query-{number:02d}",
                3 + number % (max_bodies - 2),
                close=number % 4 == 1,
            )
            for number in range(query_count - 1)
        ]
        base = queries[-1]
        permutation = rng.permutation(len(base["masses"]))
        queries.append(
            {
                "query_id": f"query-{query_count - 1:02d}-permuted",
                "masses": np.asarray(base["masses"])[permutation].tolist(),
                "state": np.asarray(base["state"])[permutation].tolist(),
            }
        )
        public = {
            "schema_version": 1,
            "instance_id": instance_id,
            "constants": {
                "gravitational_constant": gravitational_constant,
                "softening": softening,
            },
            "state_layout": ["q_x", "q_y", "p_x", "p_y"],
            "conventions": {
                "hamiltonian": "sum_i ||p_i||^2/(2*m_i) - G*sum_{i<j} m_i*m_j/sqrt(||q_i-q_j||^2+epsilon^2)",
                "canonical_field": "(dq/dt,dp/dt)=(dH/dp,-dH/dq)",
                "required_generalization": "body count varies independently per query",
            },
            "labeled_examples": labeled_examples,
            "queries": queries,
            "artifact_contract": {
                "format": "nbody-query-results-v1",
                "output": f"output/{instance_id}/results.json",
                "one_result_per_query": True,
            },
        }
        results, mutant_results = [], []
        for query in queries:
            energy, field = _nbody_energy_field(
                np.asarray(query["masses"]),
                np.asarray(query["state"]),
                gravitational_constant,
                softening,
            )
            results.append(
                {"query_id": query["query_id"], "hamiltonian": energy, "field": field.tolist()}
            )
            wrong = field.copy()
            wrong[:, 2:] *= -1.0
            mutant_results.append(
                {"query_id": query["query_id"], "hamiltonian": energy, "field": wrong.tolist()}
            )
        golden = {
            "format": "nbody-query-results-v1",
            "instance_id": instance_id,
            "results": results,
        }
        mutant = {
            "format": "nbody-query-results-v1",
            "instance_id": instance_id,
            "results": mutant_results,
        }
        files.extend(
            [
                _file(f"input/instances/{instance_id}/problems.json", _json_bytes(public), AGENT),
                _file(f"reference/instances/{instance_id}/policy.json", _json_bytes({"absolute_tolerance": tolerance, "relative_tolerance": tolerance, "required_query_count": len(queries)}), EVALUATOR),
                _file(f"example/instances/{instance_id}/golden.json", _json_bytes(golden), EVALUATOR),
                _file(f"example/instances/{instance_id}/mutant.json", _json_bytes(mutant), EVALUATOR),
            ]
        )

    description = '''
    # Solve a variable-body Hamiltonian system

    Compute the scalar energy and full canonical vector field for every
    unlabeled query. Body counts vary across the range present in the input, softened close
    encounters are included, and one query is a hidden permutation-equivalence
    check. The evaluator recomputes every answer from the public states; no
    stored participant predictions or pickled objects are trusted.

    Complete `software/solve_queries.py` and emit the bounded results JSON.
    Preserve the requested query IDs and body ordering exactly.
    '''
    starter = '''
    """Starter for variable-N softened gravitational Hamiltonian queries."""

    from __future__ import annotations

    import argparse
    import json
    from pathlib import Path


    def solve_problem(problem: dict, constants: dict) -> dict:
        # TODO: compute scalar H and the [dq_x,dq_y,dp_x,dp_y] field for every body.
        body_count = len(problem["masses"])
        return {
            "query_id": problem["query_id"],
            "hamiltonian": 0.0,
            "field": [[0.0, 0.0, 0.0, 0.0] for _ in range(body_count)],
        }


    def main() -> int:
        parser = argparse.ArgumentParser()
        parser.add_argument("--input", type=Path, required=True)
        parser.add_argument("--output", type=Path, required=True)
        args = parser.parse_args()
        instance = json.loads(args.input.read_text(encoding="utf-8"))
        artifact = {
            "format": "nbody-query-results-v1",
            "instance_id": instance["instance_id"],
            "results": [solve_problem(query, instance["constants"]) for query in instance["queries"]],
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(artifact, indent=2, allow_nan=False) + "\\n", encoding="utf-8")
        return 0


    if __name__ == "__main__":
        raise SystemExit(main())
    '''
    grader = '''
    """Recompute variable-N Hamiltonian query truth from public inputs."""

    from __future__ import annotations

    import argparse
    import json
    from pathlib import Path
    import sys

    import numpy as np


    def locate(path: Path, instance: str) -> Path:
        candidates = [path, path / "results.json", path / "output" / instance / "results.json", path / instance / "results.json"]
        result = next((item for item in candidates if item.is_file()), None)
        if result is None:
            raise FileNotFoundError("results.json is missing")
        if result.stat().st_size > 4_000_000:
            raise ValueError("results JSON exceeds 4 MB")
        return result


    def truth(query, constants):
        masses = np.asarray(query["masses"], dtype=float)
        state = np.asarray(query["state"], dtype=float)
        if state.shape != (len(masses), 4) or len(masses) < 2:
            raise ValueError("invalid query state")
        g = float(constants["gravitational_constant"])
        epsilon = float(constants["softening"])
        positions, momenta = state[:, :2], state[:, 2:]
        energy = float(np.sum(np.sum(momenta * momenta, axis=-1) / (2.0 * masses)))
        field = np.zeros_like(state)
        field[:, :2] = momenta / masses[:, None]
        for left in range(len(masses)):
            for right in range(left + 1, len(masses)):
                displacement = positions[left] - positions[right]
                squared = float(displacement @ displacement + epsilon * epsilon)
                coefficient = g * masses[left] * masses[right]
                energy -= coefficient / np.sqrt(squared)
                force = -coefficient * displacement / squared**1.5
                field[left, 2:] += force
                field[right, 2:] -= force
        return energy, field


    def main() -> int:
        parser = argparse.ArgumentParser()
        parser.add_argument("--submission", type=Path, required=True)
        parser.add_argument("--instance", required=True)
        args = parser.parse_args()
        root = Path(__file__).resolve().parent.parent
        input_path = root / "input" / "instances" / args.instance / "problems.json"
        policy_path = Path(__file__).resolve().parent / "instances" / args.instance / "policy.json"
        instance = json.loads(input_path.read_text(encoding="utf-8"))
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        errors, metrics = [], {}
        try:
            artifact = json.loads(locate(args.submission, args.instance).read_text(encoding="utf-8"))
            if set(artifact) != {"format", "instance_id", "results"} or artifact.get("format") != "nbody-query-results-v1":
                raise ValueError("artifact does not match nbody-query-results-v1")
            if artifact.get("instance_id") != args.instance:
                raise ValueError("instance_id mismatch")
            submitted = artifact["results"]
            if not isinstance(submitted, list) or len(submitted) != policy["required_query_count"]:
                raise ValueError("wrong result count")
            by_id = {item.get("query_id"): item for item in submitted if isinstance(item, dict)}
            if len(by_id) != len(submitted):
                raise ValueError("query IDs must be unique")
            max_energy_error = 0.0
            max_field_error = 0.0
            for query in instance["queries"]:
                answer = by_id.get(query["query_id"])
                if answer is None or set(answer) != {"query_id", "hamiltonian", "field"}:
                    raise ValueError(f"missing or malformed result {query['query_id']}")
                expected_energy, expected_field = truth(query, instance["constants"])
                actual_energy = float(answer["hamiltonian"])
                actual_field = np.asarray(answer["field"], dtype=float)
                if actual_field.shape != expected_field.shape or not np.all(np.isfinite(actual_field)) or not np.isfinite(actual_energy):
                    raise ValueError(f"non-finite or wrong-shaped result {query['query_id']}")
                energy_error = abs(actual_energy - expected_energy)
                field_error = float(np.max(np.abs(actual_field - expected_field)))
                max_energy_error = max(max_energy_error, energy_error)
                max_field_error = max(max_field_error, field_error)
                if not np.isclose(actual_energy, expected_energy, atol=policy["absolute_tolerance"], rtol=policy["relative_tolerance"]):
                    errors.append(f"{query['query_id']}: incorrect Hamiltonian")
                if not np.allclose(actual_field, expected_field, atol=policy["absolute_tolerance"], rtol=policy["relative_tolerance"]):
                    errors.append(f"{query['query_id']}: incorrect canonical field")
            metrics = {"max_energy_absolute_error": max_energy_error, "max_field_absolute_error": max_field_error}
        except Exception as error:
            errors.append(f"{type(error).__name__}: {error}")
        print(json.dumps({"passed": not errors, "instance": args.instance, "metrics": metrics, "errors": errors}, indent=2))
        return 0 if not errors else 1


    if __name__ == "__main__":
        sys.exit(main())
    '''
    files.extend(
        [
            _file("description.md", description, AGENT),
            _file("task_card.json", _json_bytes(_task_card(task_id, "Solve variable-N gravitational dynamics", "Compute exact softened N-body energies and canonical fields across changing body counts and close encounters.", count, "results.json", "nbody-query-results-v1", str(settings["level"]))), AGENT),
            _file("main.py", _ale_main(task_id, count, "problems.json", "results.json", "Solve every variable-body softened gravitational Hamiltonian query exactly; preserve query and body ordering in safe JSON."), AGENT, executable=True),
            _file("software/solve_queries.py", starter, AGENT, executable=True),
            _file("software/requirements.txt", "numpy>=1.26\n", AGENT),
            _file("reference/grader.py", grader, EVALUATOR, executable=True),
        ]
    )
    files.extend(
        _author_files(
            project,
            task,
            seeds,
            generator={"query_count": query_count, "labeled_example_count": 2, "body_count_min": 3, "body_count_max": max_bodies, "close_encounter_offset": [0.035 * close_scale, -0.025 * close_scale], "mass_range": [0.45, 2.2], "position_range": [-1.6, 1.6], "momentum_range": [-0.9, 0.9], "permutation_pair": [queries[-2]["query_id"], queries[-1]["query_id"]]},
            grader={"absolute_tolerance": tolerance, "relative_tolerance": tolerance, "json_byte_limit": 4_000_000, "truth_source": "recomputed from agent-visible query"},
            challenge_axes=["variable body count", "pairwise composition", "softened close encounters", "permutation equivariance", "energy and full vector field"],
            mutant_id="reverse-all-pair-force-signs",
            settings=settings,
        )
    )
    return files


def _latent_field(
    observed: np.ndarray,
    canonical_from_observed: np.ndarray,
    kinetic: np.ndarray,
    stiffness: np.ndarray,
    quartic: np.ndarray,
) -> np.ndarray:
    observed = np.asarray(observed, dtype=float)
    transform = np.asarray(canonical_from_observed, dtype=float)
    canonical = observed @ transform.T
    q, p = canonical[..., :2], canonical[..., 2:]
    grad_q = q @ stiffness.T
    grad_q[..., 0] += quartic[0] * q[..., 0] ** 3 + quartic[2] * q[..., 0] * q[..., 1] ** 2
    grad_q[..., 1] += quartic[1] * q[..., 1] ** 3 + quartic[2] * q[..., 1] * q[..., 0] ** 2
    canonical_field = np.concatenate((p @ kinetic.T, -grad_q), axis=-1)
    observed_from_canonical = np.linalg.inv(transform)
    return canonical_field @ observed_from_canonical.T


def _build_canonical_recovery(
    project: dict[str, Any], task: dict[str, Any], master_seed: int, count: int
) -> list[BuildFile]:
    task_id = "hnn-hard-canonical-recovery"
    settings = _difficulty_settings(project, task)
    sample_scale = float(settings["sample_scale"])
    ood_scale = float(settings["ood_scale"])
    horizon_scale = float(settings["horizon_scale"])
    noise_scale = float(settings["noise_scale"])
    threshold_scale = float(settings["threshold_scale"])
    train_count = max(180, round(360 * sample_scale))
    validation_count = max(50, round(100 * sample_scale))
    hidden_count = max(
        60, round(5.5 * int(settings["hidden_case_count"]) * sample_scale)
    )
    rollout_count = max(
        4,
        round(
            3
            + int(settings["adversarial_case_count"])
            + 2 * float(settings["required_pass_fraction"])
        ),
    )
    rollout_steps = max(90, round(141 * horizon_scale))
    hidden_q_limit = 1.75 * ood_scale
    files: list[BuildFile] = []
    seeds: list[int] = []
    for index in range(count):
        instance_id = f"{index:03d}"
        seed = _seed(master_seed, task_id, index)
        seeds.append(seed)
        rng = np.random.default_rng(seed)
        raw = rng.normal(size=(4, 4))
        orthogonal, _ = np.linalg.qr(raw)
        scales = np.diag(rng.uniform(0.7, 1.4, size=4))
        shear = np.eye(4)
        shear[0, 2] = rng.uniform(0.18, 0.35)
        shear[1, 3] = rng.uniform(-0.3, -0.16)
        observed_from_canonical = orthogonal @ scales @ shear
        canonical_from_observed = np.linalg.inv(observed_from_canonical)
        kinetic = np.array(
            [
                [rng.uniform(0.75, 1.3), rng.uniform(-0.13, 0.13)],
                [0.0, rng.uniform(0.8, 1.35)],
            ]
        )
        kinetic[1, 0] = kinetic[0, 1]
        stiffness = np.array(
            [
                [rng.uniform(0.8, 1.5), rng.uniform(-0.22, 0.22)],
                [0.0, rng.uniform(0.9, 1.6)],
            ]
        )
        stiffness[1, 0] = stiffness[0, 1]
        quartic = rng.uniform(0.18, 0.55, size=3)

        def sample(number: int, q_limit: float, p_limit: float) -> np.ndarray:
            canonical = np.concatenate(
                (
                    rng.uniform(-q_limit, q_limit, size=(number, 2)),
                    rng.uniform(-p_limit, p_limit, size=(number, 2)),
                ),
                axis=-1,
            )
            return canonical @ observed_from_canonical.T

        train_states = sample(train_count, 0.8, 0.75)
        validation_states = sample(validation_count, 1.1, 0.95)
        noise = (0.0035 + 0.0005 * index) * noise_scale
        train_derivatives = _latent_field(
            train_states,
            canonical_from_observed,
            kinetic,
            stiffness,
            quartic,
        ) + rng.normal(scale=noise, size=train_states.shape)
        validation_derivatives = _latent_field(
            validation_states,
            canonical_from_observed,
            kinetic,
            stiffness,
            quartic,
        ) + rng.normal(scale=noise, size=validation_states.shape)
        hidden_states = sample(hidden_count, hidden_q_limit, 1.35 * ood_scale)
        rollout_initials = sample(rollout_count, 1.45 * ood_scale, 1.0 * ood_scale)
        times = np.linspace(0.0, 3.5 * horizon_scale, rollout_steps)
        public = {
            "schema_version": 1,
            "instance_id": instance_id,
            "observed_coordinate_names": ["x0", "x1", "x2", "x3"],
            "latent_contract": {
                "canonical_order": ["q0", "q1", "p0", "p1"],
                "canonical_from_observed": "unknown invertible 4x4 matrix B with z=B*x",
                "hamiltonian": "0.5*p^T*D*p + 0.5*q^T*K*q + a*q0^4/4 + b*q1^4/4 + c*q0^2*q1^2/2",
                "unknowns": ["B", "symmetric positive-definite D", "symmetric positive-definite K", "quartic [a,b,c]"],
            },
            "train": {
                "observed_states": train_states.tolist(),
                "observed_derivatives": train_derivatives.tolist(),
            },
            "validation": {
                "observed_states": validation_states.tolist(),
                "observed_derivatives": validation_derivatives.tolist(),
            },
            "artifact_contract": {
                "format": "latent-canonical-hamiltonian-v1",
                "output": f"output/{instance_id}/recovery.json",
                "equivalent_factorizations": "accepted by induced-field scoring",
            },
        }
        truth = {
            "schema_version": 1,
            "instance_id": instance_id,
            "parameters": {
                "canonical_from_observed": canonical_from_observed.tolist(),
                "kinetic": kinetic.tolist(),
                "stiffness": stiffness.tolist(),
                "quartic": quartic.tolist(),
            },
            "hidden_observed_states": hidden_states.tolist(),
            "rollout_initial_observed_states": rollout_initials.tolist(),
            "rollout_times": times.tolist(),
            "thresholds": {
                "field_mse_max": 0.008 * threshold_scale,
                "rollout_mse_max": 0.045 * threshold_scale,
            },
        }
        golden = {
            "format": "latent-canonical-hamiltonian-v1",
            "canonical_from_observed": canonical_from_observed.tolist(),
            "kinetic": kinetic.tolist(),
            "stiffness": stiffness.tolist(),
            "quartic": quartic.tolist(),
        }
        mutant = json.loads(json.dumps(golden))
        mutant["canonical_from_observed"] = np.eye(4).tolist()
        files.extend(
            [
                _file(f"input/instances/{instance_id}/observations.json", _json_bytes(public), AGENT),
                _file(f"reference/instances/{instance_id}/truth.json", _json_bytes(truth), EVALUATOR),
                _file(f"example/instances/{instance_id}/golden.json", _json_bytes(golden), EVALUATOR),
                _file(f"example/instances/{instance_id}/mutant.json", _json_bytes(mutant), EVALUATOR),
            ]
        )

    description = '''
    # Recover hidden canonical coordinates and nonlinear energy

    Observations are an unknown, well-conditioned linear mixture of two
    canonical coordinate pairs. Recover both a canonicalizing transform and a
    coupled quartic scalar Hamiltonian. The decomposition is not graded by raw
    coefficient equality: the evaluator forms your induced observed-space
    vector field, probes higher-energy states, and integrates hidden rollouts.

    This requires coordinate recovery and nonlinear system identification
    together. Submit only the bounded `latent-canonical-hamiltonian-v1` JSON.
    '''
    starter = '''
    """Starter for latent canonical-coordinate and Hamiltonian recovery."""

    from __future__ import annotations

    import argparse
    import json
    from pathlib import Path


    def recover(instance: dict) -> dict:
        # TODO: infer a canonicalizer and all quadratic/quartic coefficients.
        return {
            "format": "latent-canonical-hamiltonian-v1",
            "canonical_from_observed": [[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)],
            "kinetic": [[1.0, 0.0], [0.0, 1.0]],
            "stiffness": [[1.0, 0.0], [0.0, 1.0]],
            "quartic": [0.0, 0.0, 0.0],
        }


    def main() -> int:
        parser = argparse.ArgumentParser()
        parser.add_argument("--input", type=Path, required=True)
        parser.add_argument("--output", type=Path, required=True)
        args = parser.parse_args()
        artifact = recover(json.loads(args.input.read_text(encoding="utf-8")))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(artifact, indent=2, allow_nan=False) + "\\n", encoding="utf-8")
        return 0


    if __name__ == "__main__":
        raise SystemExit(main())
    '''
    grader = '''
    """Score the induced field of a safe latent-canonical Hamiltonian."""

    from __future__ import annotations

    import argparse
    import json
    from pathlib import Path
    import sys

    import numpy as np


    def locate(path: Path, instance: str) -> Path:
        candidates = [path, path / "recovery.json", path / "output" / instance / "recovery.json", path / instance / "recovery.json"]
        result = next((item for item in candidates if item.is_file()), None)
        if result is None:
            raise FileNotFoundError("recovery.json is missing")
        if result.stat().st_size > 1_000_000:
            raise ValueError("recovery JSON exceeds 1 MB")
        return result


    def parse(path):
        artifact = json.loads(path.read_text(encoding="utf-8"))
        expected = {"format", "canonical_from_observed", "kinetic", "stiffness", "quartic"}
        if set(artifact) != expected or artifact.get("format") != "latent-canonical-hamiltonian-v1":
            raise ValueError("artifact keys or format are invalid")
        transform = np.asarray(artifact["canonical_from_observed"], dtype=float)
        kinetic = np.asarray(artifact["kinetic"], dtype=float)
        stiffness = np.asarray(artifact["stiffness"], dtype=float)
        quartic = np.asarray(artifact["quartic"], dtype=float)
        if transform.shape != (4, 4) or kinetic.shape != (2, 2) or stiffness.shape != (2, 2) or quartic.shape != (3,):
            raise ValueError("artifact parameter shapes are invalid")
        if not all(np.all(np.isfinite(value)) for value in (transform, kinetic, stiffness, quartic)):
            raise ValueError("parameters must be finite")
        if np.linalg.cond(transform) > 100:
            raise ValueError("canonicalizer is singular or ill-conditioned")
        for name, matrix in (("kinetic", kinetic), ("stiffness", stiffness)):
            if not np.allclose(matrix, matrix.T, atol=1e-12) or np.min(np.linalg.eigvalsh(matrix)) <= 0:
                raise ValueError(f"{name} must be symmetric positive definite")
        if np.max(np.abs(transform)) > 20 or np.max(np.abs(kinetic)) > 20 or np.max(np.abs(stiffness)) > 20 or np.max(np.abs(quartic)) > 20:
            raise ValueError("parameter safety bound exceeded")
        return transform, kinetic, stiffness, quartic


    def field(observed, transform, kinetic, stiffness, quartic):
        observed = np.asarray(observed, dtype=float)
        canonical = observed @ transform.T
        q, p = canonical[..., :2], canonical[..., 2:]
        grad_q = q @ stiffness.T
        grad_q[..., 0] += quartic[0]*q[..., 0]**3 + quartic[2]*q[..., 0]*q[..., 1]**2
        grad_q[..., 1] += quartic[1]*q[..., 1]**3 + quartic[2]*q[..., 1]*q[..., 0]**2
        canonical_field = np.concatenate((p @ kinetic.T, -grad_q), axis=-1)
        return canonical_field @ np.linalg.inv(transform).T


    def rollout(parameters, initial, times):
        trajectory = np.empty((len(times), 4), dtype=float)
        trajectory[0] = initial
        for index in range(1, len(times)):
            dt = float(times[index] - times[index - 1])
            state = trajectory[index - 1]
            k1 = field(state[None], *parameters)[0]
            k2 = field((state + 0.5*dt*k1)[None], *parameters)[0]
            k3 = field((state + 0.5*dt*k2)[None], *parameters)[0]
            k4 = field((state + dt*k3)[None], *parameters)[0]
            trajectory[index] = state + dt*(k1 + 2*k2 + 2*k3 + k4)/6.0
        return trajectory


    def main() -> int:
        parser = argparse.ArgumentParser()
        parser.add_argument("--submission", type=Path, required=True)
        parser.add_argument("--instance", required=True)
        args = parser.parse_args()
        truth_path = Path(__file__).resolve().parent / "instances" / args.instance / "truth.json"
        truth = json.loads(truth_path.read_text(encoding="utf-8"))
        errors, metrics = [], {}
        try:
            predicted = parse(locate(args.submission, args.instance))
            values = truth["parameters"]
            actual = tuple(np.asarray(values[name], dtype=float) for name in ("canonical_from_observed", "kinetic", "stiffness", "quartic"))
            states = np.asarray(truth["hidden_observed_states"], dtype=float)
            expected_field = field(states, *actual)
            predicted_field = field(states, *predicted)
            field_mse = float(np.mean((predicted_field - expected_field) ** 2))
            initials = np.asarray(truth["rollout_initial_observed_states"], dtype=float)
            times = np.asarray(truth["rollout_times"], dtype=float)
            expected_rollouts = np.stack([rollout(actual, value, times) for value in initials])
            predicted_rollouts = np.stack([rollout(predicted, value, times) for value in initials])
            rollout_mse = float(np.mean((predicted_rollouts - expected_rollouts) ** 2))
            metrics = {"field_mse": field_mse, "rollout_mse": rollout_mse}
            if not all(np.isfinite(value) for value in metrics.values()):
                errors.append("metrics are non-finite")
            if field_mse > truth["thresholds"]["field_mse_max"]:
                errors.append("hidden transformed-field MSE exceeds threshold")
            if rollout_mse > truth["thresholds"]["rollout_mse_max"]:
                errors.append("hidden transformed rollout MSE exceeds threshold")
        except Exception as error:
            errors.append(f"{type(error).__name__}: {error}")
        print(json.dumps({"passed": not errors, "instance": args.instance, "metrics": metrics, "errors": errors}, indent=2))
        return 0 if not errors else 1


    if __name__ == "__main__":
        sys.exit(main())
    '''
    files.extend(
        [
            _file("description.md", description, AGENT),
            _file("task_card.json", _json_bytes(_task_card(task_id, "Recover hidden canonical coordinates", "Jointly identify a canonicalizing transform and nonlinear quartic energy from mixed-coordinate observations.", count, "recovery.json", "latent-canonical-hamiltonian-v1", str(settings["level"]))), AGENT),
            _file("main.py", _ale_main(task_id, count, "observations.json", "recovery.json", "Recover latent canonical coordinates and a nonlinear scalar Hamiltonian; grading uses the induced field, OOD states, and rollouts."), AGENT, executable=True),
            _file("software/recover.py", starter, AGENT, executable=True),
            _file("software/requirements.txt", "numpy>=1.26\n", AGENT),
            _file("reference/grader.py", grader, EVALUATOR, executable=True),
        ]
    )
    files.extend(
        _author_files(
            project,
            task,
            seeds,
            generator={"observed_dimension": 4, "latent_dof": 2, "train_count": train_count, "validation_count": validation_count, "hidden_count": hidden_count, "rollout_count": rollout_count, "rollout_steps": rollout_steps, "train_q_limit": 0.8, "hidden_q_limit": hidden_q_limit, "rollout_horizon": 3.5 * horizon_scale, "label_noise_scale": noise_scale, "mixing_condition_limit": 100},
            grader={"field_mse_max": 0.008 * threshold_scale, "rollout_mse_max": 0.045 * threshold_scale, "json_byte_limit": 1_000_000, "coefficient_scoring": "induced observed-space field, not raw factor equality"},
            challenge_axes=["hidden canonical coordinates", "nonsymplectic linear mixing", "quartic nonlinear energy", "factorization ambiguity", "out-of-distribution energy", "rollouts"],
            mutant_id="assume-observed-coordinates-are-canonical",
            settings=settings,
        )
    )
    return files


_BUILDERS: dict[str, Callable[[dict[str, Any], dict[str, Any], int, int], list[BuildFile]]] = {
    "hnn-hard-coupled-identification": _build_coupled,
    "hnn-hard-variable-nbody": _build_variable_nbody,
    "hnn-hard-canonical-recovery": _build_canonical_recovery,
}


def build_task_files(
    project: dict,
    task: dict,
    *,
    master_seed: int,
    instances: int | None = None,
) -> list[BuildFile]:
    """Build one registered hard HNN task without touching the smoke family."""

    if not isinstance(project, dict) or not isinstance(task, dict):
        raise TypeError("project and task must be dictionaries")
    task_id = task.get("id") or task.get("task_id")
    if task_id not in _BUILDERS:
        raise ValueError(f"unsupported hard HNN task {task_id!r}; expected one of {SUPPORTED_TASKS}")
    count = _count(project, task, instances)
    resolved = resolve_task_difficulty(project, task)
    if resolved is None:
        raise ValueError("hard HNN tasks require an explicit task difficulty selection")
    if instances is None and count != int(resolved.generator["instance_count"]):
        raise ValueError(
            "task instances must equal the resolved difficulty instance_count; "
            "use generator_overrides.instance_count to select an explicit count"
        )
    files = _BUILDERS[task_id](project, task, int(master_seed), count)
    paths = [item.path for item in files]
    if len(paths) != len(set(path.casefold() for path in paths)):
        raise RuntimeError(f"hard HNN builder produced duplicate paths for {task_id}")
    return sorted(files, key=lambda item: item.path)


__all__ = ["SUPPORTED_TASKS", "build_task_files"]
