"""Grounded, paper-blind Hamiltonian-dynamics task family.

The source manuscript and its official implementation disagree in a few useful
ways.  Those disagreements are retained as author-side provenance, while the
participant projection contains a complete standalone specification and no
paper identity.  Every stochastic choice is derived from ``master_seed`` and
the task/instance identity, so byte-for-byte builds are reproducible.
"""

from __future__ import annotations

import hashlib
import json
import textwrap
from typing import Any, Callable

import numpy as np

from paper2ale.packaging import BuildFile


AGENT = "agent"
EVALUATOR = "evaluator"
AUTHOR = "author"

SUPPORTED_TASKS = (
    "hnn-symplectic-gradient",
    "hnn-mass-spring",
    "hnn-two-body-audit",
)

PAPER_TITLE = "Hamiltonian Neural Networks"
ARXIV_URL = "https://arxiv.org/abs/1906.01563"
PAPER_PDF_URL = "https://arxiv.org/pdf/1906.01563"
PAPER_PDF_SHA256 = "bd83fe321874ddad9471f83a642ae94ab7412fd9eb0add8caae84a0ee20d168b"
OFFICIAL_REPO_URL = "https://github.com/greydanus/hamiltonian-nn"
OFFICIAL_REPO_REVISION = "bcc362235dc623ffe48f22ccc22417e02e9803b4"
ALE_REPO_URL = "https://github.com/rdi-berkeley/agents-last-exam"
ALE_REPO_REVISION = "75a3f866535946b67f9a57e4f158eb30ad50be8a"


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def _text_bytes(value: str) -> bytes:
    return (textwrap.dedent(value).strip() + "\n").encode("utf-8")


def _file(
    path: str,
    data: bytes | str,
    visibility: str,
    *,
    executable: bool = False,
) -> BuildFile:
    payload = data if isinstance(data, bytes) else _text_bytes(data)
    return BuildFile(path=path, data=payload, visibility=visibility, executable=executable)


def _derived_seed(master_seed: int, task_id: str, instance_index: int, purpose: str = "instance") -> int:
    material = f"hnn-v1\0{int(master_seed)}\0{task_id}\0{instance_index}\0{purpose}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big", signed=False)


def _instance_count(project: dict[str, Any], task: dict[str, Any], instances: int | None) -> int:
    value = instances
    if value is None:
        defaults = project.get("defaults", {})
        default_instances = defaults.get("instances", 3) if isinstance(defaults, dict) else 3
        value = task.get("instances", default_instances)
    count = int(value)
    if count < 1 or count > 64:
        raise ValueError("instances must be between 1 and 64")
    return count


def _task_card(
    task_id: str,
    title: str,
    task_type: str,
    count: int,
    summary: str,
    submission: dict[str, Any],
    *,
    timeout: int,
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
            "timeout_s": timeout,
        },
        "paper2ale": {
            "schemaVersion": 1,
            "familyTaskId": task_id,
            "taskType": task_type,
            "paperBlind": True,
            "instanceCount": count,
            "instancePattern": "input/instances/<NNN>/",
            "entrypoint": "main.py",
            "runtime": {
                "language": "python",
                "minimumVersion": "3.11",
                "dependencies": ["numpy"],
            },
            "submission": submission,
        },
    }


def _ale_main(
    task_id: str,
    count: int,
    input_name: str,
    output_name: str | None,
    task_description: str,
) -> str:
    """Return a current-style CUA-Bench/ALE task module.

    ``LinuxTaskConfig`` owns all variant paths.  The generated metadata carries
    those absolute paths through setup and evaluation, avoiding assumptions
    about the orchestrator's process working directory.
    """

    variants = tuple(f"{index:03d}" for index in range(count))
    description_literal = json.dumps(task_description, ensure_ascii=True)
    output_literal = repr(output_name)
    return f'''
    """ALE task definitions for {task_id}."""

    from __future__ import annotations

    from dataclasses import dataclass
    import json
    import shlex

    import cua_bench as cb
    from tasks.linux_runtime import LinuxTaskConfig


    VARIANTS = {variants!r}
    TASK_DESCRIPTION = {description_literal}
    INPUT_NAME = {input_name!r}
    OUTPUT_NAME = {output_literal}


    @dataclass
    class TaskConfig(LinuxTaskConfig):
        DOMAIN_NAME: str = "physical_sciences"
        TASK_NAME: str = "{task_id}"
        VARIANT_NAME: str = "000"

        @property
        def task_description(self) -> str:
            output_instruction = (
                "Complete the supplied software in " + str(self.software_dir) + "."
                if OUTPUT_NAME is None
                else "Write the final artifact to "
                + str(self.remote_output_dir).rstrip("/")
                + "/"
                + OUTPUT_NAME
                + "."
            )
            return (
                TASK_DESCRIPTION
                + "\\n\\nYour task workspace is "
                + str(self.task_dir)
                + ". Read the instance at "
                + str(self.input_dir).rstrip("/")
                + "/"
                + INPUT_NAME
                + ". "
                + output_instruction
            )


    def _metadata(cfg: TaskConfig, instance_id: str) -> dict:
        metadata = dict(cfg.to_metadata())
        metadata.update(
            {{
                "instance_id": instance_id,
                "task_dir": str(cfg.task_dir),
                "input_path": str(cfg.input_dir).rstrip("/") + "/{input_name}",
                "packaged_input_path": "input/instances/" + instance_id + "/{input_name}",
                "grader_path": str(cfg.reference_dir).rstrip("/") + "/grader.py",
                "remote_output_dir": str(cfg.remote_output_dir),
                "submission_path": (
                    str(cfg.task_dir)
                    if OUTPUT_NAME is None
                    else str(cfg.remote_output_dir).rstrip("/") + "/" + OUTPUT_NAME
                ),
            }}
        )
        return metadata


    @cb.tasks_config(split="train")
    def load():
        tasks = []
        for instance_id in VARIANTS:
            cfg = TaskConfig(VARIANT_NAME=instance_id)
            tasks.append(
                cb.Task(
                    description=cfg.task_description,
                    metadata=_metadata(cfg, instance_id),
                    computer={{
                        "provider": "computer",
                        "setup_config": {{"os_type": cfg.OS_TYPE}},
                    }},
                )
            )
        return tasks


    @cb.setup_task(split="train")
    async def start(task_cfg, session: cb.DesktopSession):
        metadata = task_cfg.metadata
        await session.run_command(
            "rm -rf "
            + shlex.quote(metadata["remote_output_dir"])
            + " "
            + shlex.quote(str(metadata["grader_path"]).rsplit("/", 1)[0])
            + " && mkdir -p "
            + shlex.quote(metadata["remote_output_dir"])
            + " && test -f "
            + shlex.quote(metadata["input_path"]),
            check=True,
        )


    @cb.evaluate_task(split="train")
    async def evaluate(task_cfg, session: cb.DesktopSession) -> list[float]:
        metadata = task_cfg.metadata
        try:
            await session.read_file(metadata["grader_path"])
        except Exception as exc:
            raise RuntimeError(
                "evaluator reference was not staged: " + metadata["grader_path"]
            ) from exc
        command = (
            "python3 "
            + shlex.quote(metadata["grader_path"])
            + " --submission "
            + shlex.quote(metadata["submission_path"])
            + " --instance "
            + shlex.quote(metadata["instance_id"])
        )
        completed = await session.run_command(command, check=False)
        stdout = completed.get("stdout", "") if isinstance(completed, dict) else getattr(completed, "stdout", "")
        try:
            begin, end = stdout.find("{{"), stdout.rfind("}}")
            result = json.loads(stdout[begin : end + 1]) if begin >= 0 and end >= begin else {{}}
        except (TypeError, ValueError, json.JSONDecodeError):
            result = {{}}
        return [1.0 if result.get("passed") else 0.0]


    if __name__ == "__main__":
        cb.interact(__file__)
    '''


def _source_record(project: dict[str, Any], task_id: str) -> dict[str, Any]:
    bundle = project.get("source_bundle", []) if isinstance(project, dict) else []
    sources = [source for source in bundle if isinstance(source, dict)]
    paper = next((source for source in sources if source.get("kind") == "paper"), {})
    code = next((source for source in sources if source.get("kind") == "code"), {})
    return {
        "task_id": task_id,
        "paper": {
            "source_id": paper.get("id", "src-hnn-paper-v3"),
            "title": PAPER_TITLE,
            "version": paper.get("version", "arXiv:1906.01563v3"),
            "abstract_url": ARXIV_URL,
            "pdf_url": paper.get("uri", PAPER_PDF_URL),
            "pdf_sha256": paper.get("sha256", PAPER_PDF_SHA256),
            "citation": paper.get("citation"),
            "license": paper.get("license"),
            "retrieved_at": paper.get("retrieved_at"),
        },
        "official_implementation": {
            "source_id": code.get("id", "src-hnn-code-master"),
            "url": code.get("uri", OFFICIAL_REPO_URL),
            "revision": code.get("version", OFFICIAL_REPO_REVISION),
            "citation": code.get("citation"),
            "license": code.get("license"),
            "retrieved_at": code.get("retrieved_at"),
        },
        "ale_runtime": {
            "url": ALE_REPO_URL,
            "revision": ALE_REPO_REVISION,
            "verified_contracts": [
                "tasks/linux_runtime.py:LinuxTaskConfig",
                "tasks/demo/hello/main.py",
                "tasks/demo/hello/task_card.json",
                "ale_run/environments/task_data/local_host.py",
            ],
            "retrieved_at": "2026-08-13",
        },
        "grounded_facts": [
            {
                "id": "canonical-equations",
                "fact": "For x=(q,p), the learned scalar induces dq/dt=dH/dp and dp/dt=-dH/dq.",
                "paper_location": "Equation 2",
            },
            {
                "id": "spring-scaling-conflict",
                "fact": "The manuscript prints H=0.5*q^2+0.5*p^2 for unit constants; official experiment code uses H=q^2+p^2.",
                "paper_location": "Equation 4 and Task 1",
                "code_location": "experiment-spring/data.py:hamiltonian_fn",
            },
            {
                "id": "spring-protocol-conflict",
                "fact": "The manuscript states uniform initial energies in [0.2,1]; official code samples radius uniformly in [0.1,1], making squared radius non-uniform in energy.",
                "paper_location": "Task 1 data paragraph",
                "code_location": "experiment-spring/data.py:get_trajectory",
            },
            {
                "id": "two-body-equation-conflict",
                "fact": "Printed Eq. 6 has a positive inverse-square potential; code uses negative inverse-distance potential and attractive inverse-square force.",
                "paper_location": "Equation 6",
                "code_location": "experiment-2body/data.py:potential_energy/get_accelerations",
            },
            {
                "id": "pixel-loss-sign-conflict",
                "fact": "Printed L_CC uses z_p^t-(z_q^t-z_q^(t+1)); code uses z_p^t-(z_q^(t+1)-z_q^t).",
                "paper_location": "Equation 7",
                "code_location": "experiment-pixels/train.py:pixelhnn_loss",
            },
        ],
    }


def _author_files(project: dict[str, Any], task_id: str, instance_seeds: list[int]) -> list[BuildFile]:
    provenance = _source_record(project, task_id)
    provenance["instance_seeds"] = instance_seeds
    evidence_graph = {
        "schema_version": 1,
        "nodes": [
            {"id": "paper-eq2", "kind": "source", "label": "canonical Hamilton equations"},
            {"id": "paper-eq4", "kind": "source", "label": "printed unit mass-spring Hamiltonian"},
            {"id": "code-spring", "kind": "source", "label": "official spring generator"},
            {"id": "paper-eq6", "kind": "source", "label": "printed two-body expression"},
            {"id": "code-two-body", "kind": "source", "label": "official two-body generator"},
            {"id": "paper-eq7", "kind": "source", "label": "printed canonical-coordinate loss"},
            {"id": "code-pixels", "kind": "source", "label": "official pixel loss"},
            {"id": "task", "kind": "artifact", "label": task_id},
        ],
        "edges": [
            {"from": "paper-eq2", "to": "task", "relation": "grounds"},
            {"from": "paper-eq4", "to": "code-spring", "relation": "conflicts-with"},
            {"from": "paper-eq6", "to": "code-two-body", "relation": "conflicts-with"},
            {"from": "paper-eq7", "to": "code-pixels", "relation": "conflicts-with"},
        ],
    }
    qa = f"""
    # Author QA notes: {task_id}

    - Participant files must not name the source paper, its authors, its identifier, or a source URL.
    - Evaluator targets remain under `reference/`; author evidence remains under `author/`.
    - All instance seeds are SHA-256-derived from the master seed and stable identifiers.
    - The mass-spring task deliberately chooses the official-code time scaling and says so only here.
    - The two-body audit deliberately preserves the printed/code disagreement instead of silently correcting it.
    - The pixel-loss sign disagreement is recorded even though it is not selected as one of the three tasks.
    - Generated graders evaluate submitted artifacts independently and ignore self-reported metrics.
    """
    return [
        _file("author/provenance.json", _json_bytes(provenance), AUTHOR),
        _file("author/evidence_graph.json", _json_bytes(evidence_graph), AUTHOR),
        _file("author/qa_notes.md", qa, AUTHOR),
    ]


def _symplectic_gradient(gradient: np.ndarray) -> np.ndarray:
    gradient = np.asarray(gradient, dtype=float)
    half = gradient.shape[-1] // 2
    return np.concatenate((gradient[..., half:], -gradient[..., :half]), axis=-1)


def _build_symplectic(
    project: dict[str, Any], task: dict[str, Any], master_seed: int, count: int
) -> list[BuildFile]:
    task_id = "hnn-symplectic-gradient"
    files: list[BuildFile] = []
    seeds: list[int] = []
    for index in range(count):
        instance_id = f"{index:03d}"
        seed = _derived_seed(master_seed, task_id, index)
        seeds.append(seed)
        rng = np.random.default_rng(seed)
        dof = int(rng.integers(1, 4))
        state_dim = 2 * dof
        public_gradients = rng.normal(size=(4, state_dim))
        public = {
            "schema_version": 1,
            "instance_id": instance_id,
            "state_dimension": state_dim,
            "degrees_of_freedom": dof,
            "coordinate_order": [f"q{i}" for i in range(dof)] + [f"p{i}" for i in range(dof)],
            "public_examples": [
                {"gradient": g.tolist(), "expected": _symplectic_gradient(g).tolist()}
                for g in public_gradients
            ],
            "requirements": {
                "accepted_shapes": ["(2*d,)", "(...,2*d)"],
                "preserve_leading_dimensions": True,
                "odd_last_dimension": "raise ValueError",
                "mutate_input": False,
            },
        }
        quadratics: list[dict[str, Any]] = []
        for case_index in range(3):
            raw = rng.normal(size=(state_dim, state_dim))
            matrix = raw.T @ raw / state_dim + (0.2 + 0.1 * case_index) * np.eye(state_dim)
            matrix = 0.5 * (matrix + matrix.T)
            linear = rng.normal(scale=0.3, size=state_dim)
            states = rng.uniform(-1.5, 1.5, size=(5 + case_index, state_dim))
            gradients = states @ matrix.T + linear
            quadratics.append(
                {
                    "matrix": matrix.tolist(),
                    "linear": linear.tolist(),
                    "states": states.tolist(),
                    "expected": _symplectic_gradient(gradients).tolist(),
                }
            )
        hidden = {
            "schema_version": 1,
            "instance_id": instance_id,
            "state_dimension": state_dim,
            "quadratic_tests": quadratics,
        }
        files.append(
            _file(f"input/instances/{instance_id}/instance.json", _json_bytes(public), AGENT)
        )
        files.append(
            _file(f"reference/instances/{instance_id}/tests.json", _json_bytes(hidden), EVALUATOR)
        )

    description = """
    # Complete a canonical vector-field transform

    Implement `symplectic_gradient` in `software/solution.py`. The input is the
    gradient of a scalar with coordinates ordered as all positions followed by
    all momenta:

    `[..., q0, q1, ..., p0, p1, ...]`.

    Return the corresponding canonical time derivative with the same leading
    dimensions. Public examples are supplied per instance. Evaluation also uses
    hidden gradients of quadratic scalar functions, batched inputs, a mutation
    check, and an odd-dimension error check.

    Run a public check with:

    `python software/public_check.py --instance 000 --output output/000`

    Submit the completed `software/solution.py`.
    """
    starter = '''
    """Participant implementation for the canonical transform."""

    from __future__ import annotations

    import numpy as np


    def symplectic_gradient(grad_h: np.ndarray) -> np.ndarray:
        """Map a scalar gradient ordered [q..., p...] to [dq/dt..., dp/dt...]."""
        values = np.asarray(grad_h)
        if values.ndim == 0 or values.shape[-1] <= 0 or values.shape[-1] % 2:
            raise ValueError("the last dimension must be positive and even")
        # TODO: replace the masked region with the canonical transform.
        raise NotImplementedError("complete symplectic_gradient")
    '''
    public_check_py = '''
    """Run participant code against the public examples for one instance."""

    from __future__ import annotations

    import argparse
    import json
    from pathlib import Path
    import sys

    import numpy as np

    TASK_ROOT = Path(__file__).resolve().parents[1]
    if str(TASK_ROOT) not in sys.path:
        sys.path.insert(0, str(TASK_ROOT))

    from software.solution import symplectic_gradient


    def main() -> int:
        parser = argparse.ArgumentParser()
        parser.add_argument("--instance", default="000")
        parser.add_argument("--output", type=Path, default=Path("output/000"))
        args = parser.parse_args()
        candidates = (
            TASK_ROOT / "input" / "instances" / args.instance / "instance.json",
            TASK_ROOT / "input" / "instance.json",
        )
        path = next((candidate for candidate in candidates if candidate.is_file()), candidates[0])
        instance = json.loads(path.read_text(encoding="utf-8"))
        checks = []
        for example in instance["public_examples"]:
            actual = np.asarray(symplectic_gradient(np.asarray(example["gradient"], dtype=float)))
            expected = np.asarray(example["expected"], dtype=float)
            checks.append(bool(np.allclose(actual, expected, atol=1e-12, rtol=1e-12)))
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "public_check.json").write_text(
            json.dumps({"passed": all(checks), "checks": checks}, indent=2) + "\\n",
            encoding="utf-8",
        )
        return 0 if all(checks) else 1


    if __name__ == "__main__":
        raise SystemExit(main())
    '''
    grader = '''
    """Evaluator-only hidden tests for the canonical transform."""

    from __future__ import annotations

    import argparse
    import importlib.util
    import json
    from pathlib import Path
    import sys

    import numpy as np


    def load_solution(path: Path):
        candidates = [path]
        if path.is_dir():
            candidates = [path / "software" / "solution.py", path / "solution.py"]
        source = next((candidate for candidate in candidates if candidate.is_file()), None)
        if source is None:
            raise FileNotFoundError("could not find software/solution.py")
        spec = importlib.util.spec_from_file_location("participant_solution", source)
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot import {source}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        function = getattr(module, "symplectic_gradient", None)
        if not callable(function):
            raise TypeError("symplectic_gradient is missing or not callable")
        return function


    def main() -> int:
        parser = argparse.ArgumentParser()
        parser.add_argument("--submission", type=Path, required=True)
        parser.add_argument("--instance", default="000")
        args = parser.parse_args()
        tests_path = Path(__file__).resolve().parent / "instances" / args.instance / "tests.json"
        tests = json.loads(tests_path.read_text(encoding="utf-8"))
        errors = []
        try:
            function = load_solution(args.submission)
            for case_index, case in enumerate(tests["quadratic_tests"]):
                matrix = np.asarray(case["matrix"], dtype=float)
                linear = np.asarray(case["linear"], dtype=float)
                states = np.asarray(case["states"], dtype=float)
                gradients = states @ matrix.T + linear
                before = gradients.copy()
                actual = np.asarray(function(gradients), dtype=float)
                expected = np.asarray(case["expected"], dtype=float)
                if actual.shape != expected.shape:
                    errors.append(f"case {case_index}: shape {actual.shape}, expected {expected.shape}")
                elif not np.all(np.isfinite(actual)):
                    errors.append(f"case {case_index}: non-finite output")
                elif not np.allclose(actual, expected, atol=1e-10, rtol=1e-10):
                    errors.append(f"case {case_index}: incorrect canonical transform")
                if not np.array_equal(gradients, before):
                    errors.append(f"case {case_index}: input was mutated")
                single = np.asarray(function(gradients[0]), dtype=float)
                if single.shape != expected[0].shape or not np.allclose(single, expected[0], atol=1e-10, rtol=1e-10):
                    errors.append(f"case {case_index}: single-vector behavior is incorrect")
            try:
                function(np.zeros(tests["state_dimension"] + 1))
                errors.append("odd last dimension did not raise ValueError")
            except ValueError:
                pass
            try:
                function(np.empty((2, 0)))
                errors.append("empty last dimension did not raise ValueError")
            except ValueError:
                pass
        except Exception as exc:
            errors.append(f"grader exception: {type(exc).__name__}: {exc}")
        result = {"passed": not errors, "errors": errors, "instance": args.instance}
        print(json.dumps(result, indent=2))
        return 0 if not errors else 1


    if __name__ == "__main__":
        sys.exit(main())
    '''
    reference_solution = '''
    """Evaluator reference for the masked transform."""

    import numpy as np


    def symplectic_gradient(grad_h):
        values = np.asarray(grad_h)
        if values.ndim == 0 or values.shape[-1] <= 0 or values.shape[-1] % 2:
            raise ValueError("the last dimension must be positive and even")
        half = values.shape[-1] // 2
        return np.concatenate((values[..., half:], -values[..., :half]), axis=-1)
    '''
    card = _task_card(
        task_id,
        "Complete a canonical gradient transform",
        "masked-code-completion",
        count,
        "Complete a NumPy canonical transform and pass hidden quadratic tests.",
        {"files": ["software/solution.py"], "evaluation": "hidden import-and-call tests"},
        timeout=1800,
    )
    files.extend(
        [
            _file("description.md", description, AGENT),
            _file("task_card.json", _json_bytes(card), AGENT),
            _file(
                "main.py",
                _ale_main(
                    task_id,
                    count,
                    "instance.json",
                    None,
                    "Complete software/solution.py using the public canonical-gradient examples. Preserve batched shapes, reject invalid last dimensions, and do not mutate inputs.",
                ),
                AGENT,
                executable=True,
            ),
            _file("software/public_check.py", public_check_py, AGENT, executable=True),
            _file("software/solution.py", starter, AGENT),
            _file("software/requirements.txt", "numpy>=1.26\n", AGENT),
            _file("reference/grader.py", grader, EVALUATOR, executable=True),
            _file("example/reference_solution.py", reference_solution, EVALUATOR),
        ]
    )
    files.extend(_author_files(project, task_id, seeds))
    return files


def _spring_field(states: np.ndarray) -> np.ndarray:
    states = np.asarray(states, dtype=float)
    return np.stack((2.0 * states[..., 1], -2.0 * states[..., 0]), axis=-1)


def _spring_rollouts(initials: np.ndarray, times: np.ndarray) -> np.ndarray:
    initials = np.asarray(initials, dtype=float)
    times = np.asarray(times, dtype=float)
    q0 = initials[:, 0, None]
    p0 = initials[:, 1, None]
    cosine = np.cos(2.0 * times)[None, :]
    sine = np.sin(2.0 * times)[None, :]
    q = q0 * cosine + p0 * sine
    p = p0 * cosine - q0 * sine
    return np.stack((q, p), axis=-1)


def _reference_tanh_model(seed: int) -> dict[str, Any]:
    """Fit a deterministic random-feature scalar model to H=q^2+p^2 and its gradient."""
    rng = np.random.default_rng(seed)
    width = 72
    weights = rng.normal(scale=0.85, size=(width, 2))
    biases = rng.uniform(-1.4, 1.4, size=width)
    states = rng.uniform(-1.6, 1.6, size=(1200, 2))
    pre = states @ weights.T + biases
    features = np.tanh(pre)
    sech2 = 1.0 - features * features
    scalar_design = np.concatenate((features, np.ones((states.shape[0], 1))), axis=1)
    scalar_target = np.sum(states * states, axis=1)
    rows = [0.35 * scalar_design]
    targets = [0.35 * scalar_target]
    for coordinate in range(2):
        derivative_design = np.concatenate(
            (sech2 * weights[:, coordinate][None, :], np.zeros((states.shape[0], 1))), axis=1
        )
        rows.append(derivative_design)
        targets.append(2.0 * states[:, coordinate])
    design = np.concatenate(rows, axis=0)
    target = np.concatenate(targets, axis=0)
    ridge = 1e-7 * np.eye(width + 1)
    ridge[-1, -1] = 0.0
    coefficients = np.linalg.solve(design.T @ design + ridge, design.T @ target)
    return {
        "format": "tanh-mlp-v1",
        "input_dim": 2,
        "output_dim": 1,
        "layers": [
            {"activation": "tanh", "weight": weights.tolist(), "bias": biases.tolist()},
            {
                "activation": "linear",
                "weight": [coefficients[:-1].tolist()],
                "bias": [float(coefficients[-1])],
            },
        ],
    }


def _build_mass_spring(
    project: dict[str, Any], task: dict[str, Any], master_seed: int, count: int
) -> list[BuildFile]:
    task_id = "hnn-mass-spring"
    files: list[BuildFile] = []
    seeds: list[int] = []
    for index in range(count):
        instance_id = f"{index:03d}"
        seed = _derived_seed(master_seed, task_id, index)
        seeds.append(seed)
        rng = np.random.default_rng(seed)
        train_states = rng.uniform(-1.25, 1.25, size=(96, 2))
        validation_states = rng.uniform(-1.25, 1.25, size=(32, 2))
        test_states = rng.uniform(-1.35, 1.35, size=(48, 2))
        label_noise = 0.018 + 0.004 * (index % 3)
        train_derivatives = _spring_field(train_states) + rng.normal(
            scale=label_noise, size=train_states.shape
        )
        validation_derivatives = _spring_field(validation_states) + rng.normal(
            scale=label_noise, size=validation_states.shape
        )
        phases = rng.uniform(0.0, 2.0 * np.pi, size=8)
        radii = rng.uniform(0.35, 1.2, size=8)
        initials = np.stack((radii * np.cos(phases), radii * np.sin(phases)), axis=-1)
        times = np.linspace(0.0, 6.0 + 0.25 * (index % 3), 126)
        public = {
            "schema_version": 1,
            "instance_id": instance_id,
            "coordinate_order": ["q", "p"],
            "train": {
                "states": train_states.tolist(),
                "derivatives": train_derivatives.tolist(),
            },
            "validation": {
                "states": validation_states.tolist(),
                "derivatives": validation_derivatives.tolist(),
            },
            "test": {"states": test_states.tolist()},
            "rollout": {
                "initial_states": initials.tolist(),
                "times": times.tolist(),
            },
            "export_contract": {
                "format": "tanh-mlp-v1",
                "input_dim": 2,
                "output_dim": 1,
                "maximum_hidden_layers": 3,
                "maximum_width": 256,
                "maximum_parameters": 100000,
            },
        }
        target = {
            "schema_version": 1,
            "instance_id": instance_id,
            "test_states": test_states.tolist(),
            "test_derivatives": _spring_field(test_states).tolist(),
            "rollout_initial_states": initials.tolist(),
            "rollout_times": times.tolist(),
            "true_rollouts": _spring_rollouts(initials, times).tolist(),
            "thresholds": {
                "test_derivative_mse_max": 0.08,
                "rollout_state_mse_max": 0.12,
                "mean_energy_drift_max": 0.04,
            },
        }
        reference_model = _reference_tanh_model(
            _derived_seed(master_seed, task_id, index, "reference-model")
        )
        files.extend(
            [
                _file(f"input/instances/{instance_id}/data.json", _json_bytes(public), AGENT),
                _file(
                    f"reference/instances/{instance_id}/targets.json",
                    _json_bytes(target),
                    EVALUATOR,
                ),
                _file(
                    f"example/instances/{instance_id}/reference_model.json",
                    _json_bytes(reference_model),
                    EVALUATOR,
                ),
            ]
        )

    description = """
    # Learn and export a scalar dynamics model

    Fit a scalar function of state to the supplied labeled train and validation
    examples. Its vector field is evaluated canonically: the momentum partial is
    the position derivative, and the negative position partial is the momentum
    derivative.

    Export the scalar as portable JSON using the `tanh-mlp-v1` contract in each
    instance. Test states are public but their derivative targets are not.
    The evaluator parses your JSON, differentiates the scalar network itself, and
    integrates that vector field from the public rollout initial states. It does
    not accept or score self-reported predictions.

    `python software/public_check.py --instance 000 --output output/000`

    must write `output/000/model.json`. Use the validation split for model
    selection; do not infer labels from evaluator files.
    """
    model_py = '''
    """Portable scalar tanh-MLP helpers. No pickles or executable model formats."""

    from __future__ import annotations

    import json
    from pathlib import Path

    import numpy as np


    def initial_model(rng: np.random.Generator, width: int = 32) -> dict:
        return {
            "format": "tanh-mlp-v1",
            "input_dim": 2,
            "output_dim": 1,
            "layers": [
                {
                    "activation": "tanh",
                    "weight": rng.normal(scale=0.15, size=(width, 2)).tolist(),
                    "bias": np.zeros(width).tolist(),
                },
                {
                    "activation": "linear",
                    "weight": rng.normal(scale=0.05, size=(1, width)).tolist(),
                    "bias": [0.0],
                },
            ],
        }


    def save_model(model: dict, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(model, indent=2, allow_nan=False) + "\\n", encoding="utf-8")
    '''
    train_py = '''
    """Training entry point to complete. Use only public train/validation labels."""

    from __future__ import annotations

    import numpy as np

    from .model import initial_model


    def train_and_export(instance: dict, seed: int) -> dict:
        rng = np.random.default_rng(seed)
        model = initial_model(rng)
        # TODO: optimize scalar-network weights so its input gradient induces
        # the labeled vector field. Return a JSON-serializable tanh-mlp-v1 model.
        return model
    '''
    public_check_py = '''
    """Train and export one portable scalar model."""

    from __future__ import annotations

    import argparse
    import hashlib
    import json
    from pathlib import Path
    import sys

    TASK_ROOT = Path(__file__).resolve().parents[1]
    if str(TASK_ROOT) not in sys.path:
        sys.path.insert(0, str(TASK_ROOT))

    from software.model import save_model
    from software.train import train_and_export


    def stable_seed(instance_id: str) -> int:
        return int.from_bytes(hashlib.sha256(instance_id.encode("utf-8")).digest()[:8], "big")


    def main() -> int:
        parser = argparse.ArgumentParser()
        parser.add_argument("--instance", default="000")
        parser.add_argument("--output", type=Path, default=Path("output/000"))
        args = parser.parse_args()
        candidates = (
            TASK_ROOT / "input" / "instances" / args.instance / "data.json",
            TASK_ROOT / "input" / "data.json",
        )
        path = next((candidate for candidate in candidates if candidate.is_file()), candidates[0])
        instance = json.loads(path.read_text(encoding="utf-8"))
        model = train_and_export(instance, stable_seed(args.instance))
        save_model(model, args.output / "model.json")
        return 0


    if __name__ == "__main__":
        raise SystemExit(main())
    '''
    grader = '''
    """Safely parse scalar tanh-MLP weights and independently evaluate dynamics."""

    from __future__ import annotations

    import argparse
    import json
    from pathlib import Path
    import sys

    import numpy as np


    def parse_model(path: Path):
        if path.stat().st_size > 8_000_000:
            raise ValueError("model JSON exceeds the 8 MB safety limit")
        model = json.loads(path.read_text(encoding="utf-8"))
        if model.get("format") != "tanh-mlp-v1" or model.get("input_dim") != 2 or model.get("output_dim") != 1:
            raise ValueError("model must use the tanh-mlp-v1 scalar contract")
        layers = model.get("layers")
        if not isinstance(layers, list) or not (2 <= len(layers) <= 4):
            raise ValueError("model must contain one to three hidden layers and one output layer")
        parsed = []
        expected_input = 2
        parameters = 0
        for index, layer in enumerate(layers):
            weight = np.asarray(layer.get("weight"), dtype=float)
            bias = np.asarray(layer.get("bias"), dtype=float)
            if weight.ndim != 2 or bias.ndim != 1 or weight.shape != (bias.size, expected_input):
                raise ValueError(f"invalid layer {index} dimensions")
            if not np.all(np.isfinite(weight)) or not np.all(np.isfinite(bias)):
                raise ValueError("weights must be finite")
            final = index == len(layers) - 1
            expected_activation = "linear" if final else "tanh"
            if layer.get("activation") != expected_activation:
                raise ValueError(f"layer {index} must use {expected_activation}")
            if not final and bias.size > 256:
                raise ValueError("hidden width exceeds 256")
            if final and bias.size != 1:
                raise ValueError("final layer must be scalar")
            parameters += weight.size + bias.size
            expected_input = bias.size
            parsed.append((weight, bias, expected_activation))
        if parameters > 100000:
            raise ValueError("model exceeds parameter budget")
        return parsed


    def hamiltonian_gradient(layers, states):
        values = np.asarray(states, dtype=float)
        activations = []
        current = values
        for weight, bias, activation in layers[:-1]:
            current = np.tanh(current @ weight.T + bias)
            activations.append(current)
        output_weight = layers[-1][0]
        gradient = np.broadcast_to(output_weight[0], current.shape).copy()
        for index in range(len(layers) - 2, -1, -1):
            weight = layers[index][0]
            gradient = (gradient * (1.0 - activations[index] ** 2)) @ weight
        return gradient


    def vector_field(layers, states):
        gradient = hamiltonian_gradient(layers, states)
        return np.stack((gradient[..., 1], -gradient[..., 0]), axis=-1)


    def rk4_rollout(layers, initial, times):
        trajectory = np.empty((len(times), 2), dtype=float)
        trajectory[0] = initial
        for index in range(1, len(times)):
            dt = float(times[index] - times[index - 1])
            state = trajectory[index - 1]
            k1 = vector_field(layers, state[None, :])[0]
            k2 = vector_field(layers, (state + 0.5 * dt * k1)[None, :])[0]
            k3 = vector_field(layers, (state + 0.5 * dt * k2)[None, :])[0]
            k4 = vector_field(layers, (state + dt * k3)[None, :])[0]
            trajectory[index] = state + (dt / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)
        return trajectory


    def locate_model(submission: Path, instance: str) -> Path:
        candidates = [
            submission,
            submission / "model.json",
            submission / "output" / instance / "model.json",
            submission / instance / "model.json",
        ]
        model = next((path for path in candidates if path.is_file()), None)
        if model is None:
            raise FileNotFoundError("could not find model.json")
        return model


    def main() -> int:
        parser = argparse.ArgumentParser()
        parser.add_argument("--submission", type=Path, required=True)
        parser.add_argument("--instance", default="000")
        args = parser.parse_args()
        target_path = Path(__file__).resolve().parent / "instances" / args.instance / "targets.json"
        target = json.loads(target_path.read_text(encoding="utf-8"))
        errors = []
        metrics = {}
        try:
            layers = parse_model(locate_model(args.submission, args.instance))
            test_states = np.asarray(target["test_states"], dtype=float)
            test_derivatives = np.asarray(target["test_derivatives"], dtype=float)
            predicted = vector_field(layers, test_states)
            if predicted.shape != test_derivatives.shape or not np.all(np.isfinite(predicted)):
                raise ValueError("model produced invalid hidden-test derivatives")
            derivative_mse = float(np.mean((predicted - test_derivatives) ** 2))
            times = np.asarray(target["rollout_times"], dtype=float)
            initials = np.asarray(target["rollout_initial_states"], dtype=float)
            true_rollouts = np.asarray(target["true_rollouts"], dtype=float)
            predicted_rollouts = np.stack([rk4_rollout(layers, state, times) for state in initials])
            if predicted_rollouts.shape != true_rollouts.shape or not np.all(np.isfinite(predicted_rollouts)):
                raise ValueError("model produced invalid rollout states")
            rollout_mse = float(np.mean((predicted_rollouts - true_rollouts) ** 2))
            energy = np.sum(predicted_rollouts * predicted_rollouts, axis=-1)
            energy_drift = float(np.mean(np.abs(energy - energy[:, :1])))
            if not all(np.isfinite(value) for value in (derivative_mse, rollout_mse, energy_drift)):
                raise ValueError("model metrics are non-finite")
            metrics = {
                "test_derivative_mse": derivative_mse,
                "rollout_state_mse": rollout_mse,
                "mean_energy_drift": energy_drift,
            }
            thresholds = target["thresholds"]
            if derivative_mse > thresholds["test_derivative_mse_max"]:
                errors.append("test derivative MSE exceeds threshold")
            if rollout_mse > thresholds["rollout_state_mse_max"]:
                errors.append("rollout state MSE exceeds threshold")
            if energy_drift > thresholds["mean_energy_drift_max"]:
                errors.append("mean rollout energy drift exceeds threshold")
        except Exception as exc:
            errors.append(f"grader exception: {type(exc).__name__}: {exc}")
        result = {"passed": not errors, "instance": args.instance, "metrics": metrics, "errors": errors}
        print(json.dumps(result, indent=2))
        return 0 if not errors else 1


    if __name__ == "__main__":
        sys.exit(main())
    '''
    reference_solver = '''
    """Reference procedure used to create evaluator-only example models.

    It fits a random-feature tanh scalar to scalar and gradient targets jointly.
    Participant solutions need not use this method.
    """

    # The generated reference_model.json files are the executable result of this
    # deterministic procedure; the authoritative scorer is reference/grader.py.
    '''
    card = _task_card(
        task_id,
        "Train and export a scalar spring model",
        "specification-preserving-training-export",
        count,
        "Train a scalar tanh MLP and export safe JSON weights for independent evaluation.",
        {
            "files": ["output/<NNN>/model.json"],
            "format": "tanh-mlp-v1",
            "predictions_scored": False,
        },
        timeout=1800,
    )
    files.extend(
        [
            _file("description.md", description, AGENT),
            _file("task_card.json", _json_bytes(card), AGENT),
            _file(
                "main.py",
                _ale_main(
                    task_id,
                    count,
                    "data.json",
                    "model.json",
                    "Train a scalar tanh MLP from the public train and validation derivative labels, then export portable model.json weights. Test derivatives are withheld.",
                ),
                AGENT,
                executable=True,
            ),
            _file("software/public_check.py", public_check_py, AGENT, executable=True),
            _file("software/model.py", model_py, AGENT),
            _file("software/train.py", train_py, AGENT),
            _file("software/__init__.py", '"""Participant training software."""\n', AGENT),
            _file("software/requirements.txt", "numpy>=1.26\n", AGENT),
            _file("reference/grader.py", grader, EVALUATOR, executable=True),
            _file("example/reference_solver.py", reference_solver, EVALUATOR),
        ]
    )
    files.extend(_author_files(project, task_id, seeds))
    return files


def _two_body_forces(
    gravitational_constant: float,
    mass_1: float,
    mass_2: float,
    position_1: np.ndarray,
    position_2: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    displacement = np.asarray(position_1, dtype=float) - np.asarray(position_2, dtype=float)
    radius = float(np.linalg.norm(displacement))
    coefficient = gravitational_constant * mass_1 * mass_2
    candidate = 2.0 * coefficient * displacement / radius**4
    implementation = -coefficient * displacement / radius**3
    return candidate, implementation


def _build_two_body_audit(
    project: dict[str, Any], task: dict[str, Any], master_seed: int, count: int
) -> list[BuildFile]:
    task_id = "hnn-two-body-audit"
    files: list[BuildFile] = []
    seeds: list[int] = []
    for index in range(count):
        instance_id = f"{index:03d}"
        seed = _derived_seed(master_seed, task_id, index)
        seeds.append(seed)
        rng = np.random.default_rng(seed)
        gravitational_constant = float(rng.uniform(0.65, 1.4))
        mass_1 = float(rng.uniform(0.7, 1.8))
        mass_2 = float(rng.uniform(0.7, 1.8))
        position_1 = rng.uniform(-1.2, 1.2, size=2)
        direction = rng.normal(size=2)
        direction /= np.linalg.norm(direction)
        position_2 = position_1 + direction * rng.uniform(0.55, 1.65)
        candidate_force, implementation_force = _two_body_forces(
            gravitational_constant, mass_1, mass_2, position_1, position_2
        )
        public = {
            "schema_version": 1,
            "instance_id": instance_id,
            "constants": {
                "gravitational_constant": gravitational_constant,
                "mass_1": mass_1,
                "mass_2": mass_2,
            },
            "positions": {"body_1": position_1.tolist(), "body_2": position_2.tolist()},
            "candidate_specification": {
                "potential_sign": 1,
                "potential_distance_power": -2,
                "expression": "+G*m1*m2/||q1-q2||^2",
            },
            "implementation_behavior": {
                "potential_sign": -1,
                "potential_distance_power": -1,
                "potential_expression": "-G*m1*m2/||q1-q2||",
                "acceleration_body_1": "G*m2*(q2-q1)/||q2-q1||^3",
            },
            "required_output": {
                "path": f"output/{instance_id}/audit.json",
                "schema": {
                    "verdict": "conflict or consistent",
                    "candidate": {
                        "direction": "repulsive or attractive",
                        "force_vector_distance_power": "integer",
                        "force_on_body_1": "two numbers",
                    },
                    "implementation": {
                        "direction": "repulsive or attractive",
                        "force_vector_distance_power": "integer",
                        "force_on_body_1": "two numbers",
                    },
                    "correction": {
                        "potential_sign": "integer",
                        "potential_distance_power": "integer",
                        "matches_implementation": "boolean",
                    },
                },
            },
        }
        target = {
            "schema_version": 1,
            "instance_id": instance_id,
            "expected": {
                "verdict": "conflict",
                "candidate": {
                    "direction": "repulsive",
                    "force_vector_distance_power": -4,
                    "force_on_body_1": candidate_force.tolist(),
                },
                "implementation": {
                    "direction": "attractive",
                    "force_vector_distance_power": -3,
                    "force_on_body_1": implementation_force.tolist(),
                },
                "correction": {
                    "potential_sign": -1,
                    "potential_distance_power": -1,
                    "matches_implementation": True,
                },
            },
            "tolerance": {"absolute": 1e-9, "relative": 1e-9},
        }
        files.extend(
            [
                _file(f"input/instances/{instance_id}/case.json", _json_bytes(public), AGENT),
                _file(
                    f"reference/instances/{instance_id}/expected.json",
                    _json_bytes(target),
                    EVALUATOR,
                ),
            ]
        )

    description = """
    # Reconcile a two-body specification with its implementation

    The supplied candidate potential and implementation behavior disagree or
    agree in sign, distance power, and force direction. Derive the force on body
    1 from each potential/behavior and write the structured JSON requested by
    the instance. Use `q1 - q2` as the displacement when reporting vector-force
    distance powers.

    The evaluator checks the structured verdict, exponents, directions,
    corrected potential, and numerical force vectors. A prose-only answer is
    not accepted.

    `python software/public_check.py --instance 000 --output output/000`
    """
    audit_py = '''
    """Complete the structured equation/implementation audit."""

    from __future__ import annotations


    def audit_case(case: dict) -> dict:
        # TODO: derive both forces and return the required structured object.
        raise NotImplementedError("complete audit_case")
    '''
    public_check_py = '''
    """Run one structured two-body audit."""

    from __future__ import annotations

    import argparse
    import json
    from pathlib import Path
    import sys

    TASK_ROOT = Path(__file__).resolve().parents[1]
    if str(TASK_ROOT) not in sys.path:
        sys.path.insert(0, str(TASK_ROOT))

    from software.audit import audit_case


    def main() -> int:
        parser = argparse.ArgumentParser()
        parser.add_argument("--instance", default="000")
        parser.add_argument("--output", type=Path, default=Path("output/000"))
        args = parser.parse_args()
        candidates = (
            TASK_ROOT / "input" / "instances" / args.instance / "case.json",
            TASK_ROOT / "input" / "case.json",
        )
        case_path = next((candidate for candidate in candidates if candidate.is_file()), candidates[0])
        case = json.loads(case_path.read_text(encoding="utf-8"))
        result = audit_case(case)
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "audit.json").write_text(
            json.dumps(result, indent=2, allow_nan=False) + "\\n", encoding="utf-8"
        )
        return 0


    if __name__ == "__main__":
        raise SystemExit(main())
    '''
    grader = '''
    """Grade a structured two-body equation reconciliation."""

    from __future__ import annotations

    import argparse
    import json
    from pathlib import Path
    import sys

    import numpy as np


    def locate(submission: Path, instance: str) -> Path:
        candidates = [
            submission,
            submission / "audit.json",
            submission / "output" / instance / "audit.json",
            submission / instance / "audit.json",
        ]
        answer = next((path for path in candidates if path.is_file()), None)
        if answer is None:
            raise FileNotFoundError("could not find audit.json")
        if answer.stat().st_size > 1_000_000:
            raise ValueError("audit JSON exceeds the 1 MB safety limit")
        return answer


    def main() -> int:
        parser = argparse.ArgumentParser()
        parser.add_argument("--submission", type=Path, required=True)
        parser.add_argument("--instance", default="000")
        args = parser.parse_args()
        expected_path = Path(__file__).resolve().parent / "instances" / args.instance / "expected.json"
        target = json.loads(expected_path.read_text(encoding="utf-8"))
        expected = target["expected"]
        errors = []
        try:
            actual = json.loads(locate(args.submission, args.instance).read_text(encoding="utf-8"))
            if actual.get("verdict") != expected["verdict"]:
                errors.append("incorrect conflict verdict")
            for section in ("candidate", "implementation"):
                value = actual.get(section, {})
                wanted = expected[section]
                if value.get("direction") != wanted["direction"]:
                    errors.append(f"{section}: incorrect direction")
                power = value.get("force_vector_distance_power")
                if type(power) is not int or power != wanted["force_vector_distance_power"]:
                    errors.append(f"{section}: incorrect vector distance power")
                vector = np.asarray(value.get("force_on_body_1"), dtype=float)
                expected_vector = np.asarray(wanted["force_on_body_1"], dtype=float)
                if vector.shape != (2,) or not np.all(np.isfinite(vector)):
                    errors.append(f"{section}: force must be a finite two-vector")
                elif not np.allclose(
                    vector,
                    expected_vector,
                    atol=target["tolerance"]["absolute"],
                    rtol=target["tolerance"]["relative"],
                ):
                    errors.append(f"{section}: incorrect numerical force")
            correction = actual.get("correction", {})
            for key, wanted in expected["correction"].items():
                value = correction.get(key)
                expected_type = bool if isinstance(wanted, bool) else int
                if type(value) is not expected_type or value != wanted:
                    errors.append(f"correction: incorrect {key}")
        except Exception as exc:
            errors.append(f"grader exception: {type(exc).__name__}: {exc}")
        result = {"passed": not errors, "instance": args.instance, "errors": errors}
        print(json.dumps(result, indent=2))
        return 0 if not errors else 1


    if __name__ == "__main__":
        sys.exit(main())
    '''
    reference_solver = '''
    """Evaluator reference solver for a structured two-body audit."""

    from __future__ import annotations

    import numpy as np


    def audit_case(case):
        constants = case["constants"]
        g = float(constants["gravitational_constant"])
        m1 = float(constants["mass_1"])
        m2 = float(constants["mass_2"])
        q1 = np.asarray(case["positions"]["body_1"], dtype=float)
        q2 = np.asarray(case["positions"]["body_2"], dtype=float)
        displacement = q1 - q2
        radius = float(np.linalg.norm(displacement))
        coefficient = g * m1 * m2
        return {
            "verdict": "conflict",
            "candidate": {
                "direction": "repulsive",
                "force_vector_distance_power": -4,
                "force_on_body_1": (2.0 * coefficient * displacement / radius**4).tolist(),
            },
            "implementation": {
                "direction": "attractive",
                "force_vector_distance_power": -3,
                "force_on_body_1": (-coefficient * displacement / radius**3).tolist(),
            },
            "correction": {
                "potential_sign": -1,
                "potential_distance_power": -1,
                "matches_implementation": True,
            },
        }
    '''
    card = _task_card(
        task_id,
        "Audit a two-body equation conflict",
        "specification-preserving-audit",
        count,
        "Reconcile two explicit two-body specifications and derive their forces.",
        {"files": ["output/<NNN>/audit.json"], "format": "structured-json-v1"},
        timeout=1800,
    )
    files.extend(
        [
            _file("description.md", description, AGENT),
            _file("task_card.json", _json_bytes(card), AGENT),
            _file(
                "main.py",
                _ale_main(
                    task_id,
                    count,
                    "case.json",
                    "audit.json",
                    "Reconcile the candidate and implemented two-body forces, then write the required structured audit.json with directions, distance powers, and numerical vectors.",
                ),
                AGENT,
                executable=True,
            ),
            _file("software/public_check.py", public_check_py, AGENT, executable=True),
            _file("software/audit.py", audit_py, AGENT),
            _file("software/__init__.py", '"""Participant audit software."""\n', AGENT),
            _file("software/requirements.txt", "numpy>=1.26\n", AGENT),
            _file("reference/grader.py", grader, EVALUATOR, executable=True),
            _file("example/reference_solver.py", reference_solver, EVALUATOR),
        ]
    )
    files.extend(_author_files(project, task_id, seeds))
    return files


_BUILDERS: dict[str, Callable[[dict[str, Any], dict[str, Any], int, int], list[BuildFile]]] = {
    "hnn-symplectic-gradient": _build_symplectic,
    "hnn-mass-spring": _build_mass_spring,
    "hnn-two-body-audit": _build_two_body_audit,
}


def build_task_files(
    project: dict,
    task: dict,
    *,
    master_seed: int,
    instances: int | None = None,
) -> list[BuildFile]:
    """Build one of the three grounded HNN task packages.

    Args:
        project: Author-side project configuration and source provenance.
        task: Task configuration. ``id`` must name one of ``SUPPORTED_TASKS``.
        master_seed: Root seed from which every instance seed is derived.
        instances: Optional deterministic override of the configured count.
    """
    if not isinstance(project, dict) or not isinstance(task, dict):
        raise TypeError("project and task must be dictionaries")
    task_id = task.get("id") or task.get("task_id")
    if task_id not in _BUILDERS:
        raise ValueError(f"unsupported HNN task {task_id!r}; expected one of {SUPPORTED_TASKS}")
    count = _instance_count(project, task, instances)
    files = _BUILDERS[task_id](project, task, int(master_seed), count)
    paths = [item.path for item in files]
    if len(paths) != len(set(paths)):
        raise RuntimeError(f"task builder produced duplicate paths for {task_id}")
    return sorted(files, key=lambda item: item.path)
