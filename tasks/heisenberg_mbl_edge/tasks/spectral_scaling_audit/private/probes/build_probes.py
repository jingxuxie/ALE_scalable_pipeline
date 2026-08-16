#!/usr/bin/env python3
"""Build deterministic, deliberately invalid submissions for robustness tests.

The generated programs are inert until the private evaluator runs them.  Each
submission contains exactly ``output/analyze.py`` so that all probes except the
explicit source-size case reach the intended evaluator or sandbox boundary.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import textwrap


ROOT = Path(__file__).resolve().parent
CASES = ROOT / "cases"
MANIFEST = ROOT / "manifest.json"

CSV_HEADERS = {
    "realization_stats.csv": "case_id,target,size,control,realization_id,n_ratios,mean_r\n",
    "packet_stats.csv": "case_id,target,size,control,n_realizations,n_ratios,mean_r,se_r\n",
    "transition.csv": "case_id,target,h_c,nu,h_c_lo,h_c_hi,nu_lo,nu_hi,fit_score,stable\n",
    "stability.csv": "case_id,target,min_size,halfwidth,h_c,nu,validation_rmse,n_groups,fit_ok\n",
    "predictions.csv": "query_id,mean_r,se_r\n",
}


def program(body: str) -> str:
    """Wrap a probe body in the public analyzer command-line contract."""

    return (
        "import argparse\n"
        "import json\n"
        "from pathlib import Path\n\n"
        "def main():\n"
        "    parser = argparse.ArgumentParser()\n"
        "    parser.add_argument('--input', required=True)\n"
        "    parser.add_argument('--output', required=True)\n"
        "    arguments = parser.parse_args()\n"
        "    input_dir = Path(arguments.input)\n"
        "    output_dir = Path(arguments.output)\n"
        + textwrap.indent(textwrap.dedent(body).strip() + "\n", "    ")
        + "\nif __name__ == '__main__':\n"
        "    main()\n"
    )


def blank_inventory(extra: str = "") -> str:
    """Return source statements that create the six required artifact names."""

    files = dict(CSV_HEADERS)
    files["claims.json"] = "{}\n"
    literals = repr(files)
    return f"""
output_dir.mkdir(parents=True, exist_ok=True)
files = {literals}
for name, content in files.items():
    (output_dir / name).write_text(content, encoding='utf-8')
{extra}
"""


def probe_definitions() -> list[dict[str, object]]:
    malformed_csv_files = dict(CSV_HEADERS)
    malformed_csv_files["realization_stats.csv"] = "wrong,header\nx,y\n"
    malformed_csv_files["claims.json"] = "{}\n"
    malformed_csv = program(
        f"""
output_dir.mkdir(parents=True, exist_ok=True)
files = {malformed_csv_files!r}
for name, content in files.items():
    (output_dir / name).write_text(content, encoding='utf-8')
"""
    )

    nonfinite_template = """
output_dir.mkdir(parents=True, exist_ok=True)
manifest = json.loads((input_dir / 'manifest.json').read_text(encoding='utf-8'))
files = {files!r}
files['realization_stats.csv'] += (
    f"{{manifest['case_id']}},0,1,0,probe-realization,1,{value}\\n"
)
for name, content in files.items():
    (output_dir / name).write_text(content, encoding='utf-8')
"""
    # Every CSV must be nonempty because the trusted parser performs its raw
    # file pass before validating individual numeric fields.  The realization
    # row is parsed first and therefore isolates the intended nonfinite gate.
    nonfinite_files = {
        "realization_stats.csv": CSV_HEADERS["realization_stats.csv"],
        "packet_stats.csv": CSV_HEADERS["packet_stats.csv"] + "placeholder,0,1,0,2,1,0.5,0.1\n",
        "transition.csv": CSV_HEADERS["transition.csv"] + "placeholder,0,1,1,0,2,0.5,2,0.5,0\n",
        "stability.csv": CSV_HEADERS["stability.csv"] + "placeholder,0,1,1,1,1,0.1,1,0\n",
        "predictions.csv": CSV_HEADERS["predictions.csv"] + "placeholder,0.5,0.1\n",
    }
    nonfinite_files["claims.json"] = "{}\n"

    oversized_output = program(
        f"""
output_dir.mkdir(parents=True, exist_ok=True)
manifest = json.loads((input_dir / 'manifest.json').read_text(encoding='utf-8'))
files = {dict(CSV_HEADERS)!r}
files['claims.json'] = ' ' * (int(manifest['resource_contract']['output_bytes']) + 1)
for name, content in files.items():
    (output_dir / name).write_text(content, encoding='utf-8')
"""
    )

    definitions: list[dict[str, object]] = [
        {
            "id": "malformed_source",
            "category": "malformed",
            "purpose": "Syntax errors fail closed before participant code can run.",
            "source": "def broken(:\n",
            "expected_failure_fragments": ["analyzer execution failed", "SyntaxError"],
        },
        {
            "id": "malformed_csv",
            "category": "malformed",
            "purpose": "A required CSV with the wrong header is rejected.",
            "source": malformed_csv,
            "expected_failure_fragments": ["realization_stats.csv header mismatch"],
        },
        {
            "id": "nan_statistic",
            "category": "nonfinite",
            "purpose": "NaN cannot cross a numeric artifact boundary.",
            "source": program(nonfinite_template.format(files=nonfinite_files, value="nan")),
            "expected_failure_fragments": ["mean_r is not finite"],
        },
        {
            "id": "infinite_statistic",
            "category": "nonfinite",
            "purpose": "Infinity cannot cross a numeric artifact boundary.",
            "source": program(nonfinite_template.format(files=nonfinite_files, value="inf")),
            "expected_failure_fragments": ["mean_r is not finite"],
        },
        {
            "id": "partial_artifacts",
            "category": "partial",
            "purpose": "Missing required artifacts are a hard failure.",
            "source": program(
                """
output_dir.mkdir(parents=True, exist_ok=True)
(output_dir / 'claims.json').write_text('{}\\n', encoding='utf-8')
"""
            ),
            "expected_failure_fragments": ["output inventory mismatch"],
        },
        {
            "id": "extra_artifact",
            "category": "inventory",
            "purpose": "Unexpected artifacts are rejected along with missing ones.",
            "source": program(blank_inventory("(output_dir / 'extra.txt').write_text('extra', encoding='utf-8')")),
            "expected_failure_fragments": ["output inventory mismatch"],
        },
        {
            "id": "oversized_source",
            "category": "oversize",
            "purpose": "The analyzer source-size gate rejects files larger than 250000 bytes.",
            "source": "# deliberately oversized analyzer\n#" + ("x" * 250100) + "\n",
            "expected_failure_fragments": ["analyzer is oversized"],
        },
        {
            "id": "oversized_output",
            "category": "oversize",
            "purpose": "The per-case output byte limit is enforced before parsing.",
            "source": oversized_output,
            "expected_failure_fragments": ["output byte limit exceeded"],
        },
        {
            "id": "private_path_read",
            "category": "security",
            "purpose": "Traversal from a mounted hidden input cannot read the private reference tree.",
            "source": program(
                """
private_reference = input_dir.parent.parent / 'reference' / 'suite.json'
private_reference.read_text(encoding='utf-8')
"""
            ),
            "expected_failure_fragments": ["audit denied filesystem access: open"],
        },
        {
            "id": "input_mutation",
            "category": "security",
            "purpose": "Mounted input data remain read-only to participant code.",
            "source": program(
                """
(input_dir / 'manifest.json').write_text('corrupted', encoding='utf-8')
"""
            ),
            "expected_failure_fragments": ["audit denied filesystem access: open"],
        },
        {
            "id": "output_parent_escape",
            "category": "security",
            "purpose": "Writes cannot escape the designated output directory.",
            "source": program(
                """
(output_dir.parent / 'escape.txt').write_text('escaped', encoding='utf-8')
"""
            ),
            "expected_failure_fragments": ["audit denied filesystem access: open"],
        },
        {
            "id": "network_import",
            "category": "security",
            "purpose": "Network-capable modules are outside the allowed import surface.",
            "source": "import socket\nsocket.socket()\n",
            "expected_failure_fragments": ["audit denied import: socket"],
        },
        {
            "id": "process_import",
            "category": "security",
            "purpose": "Process-spawning modules are outside the allowed import surface.",
            "source": "import subprocess\nsubprocess.run(['echo', 'forbidden'])\n",
            "expected_failure_fragments": ["audit denied import: subprocess"],
        },
        {
            "id": "dynamic_exec",
            "category": "security",
            "purpose": "Runtime compilation and dynamic execution are denied.",
            "source": program("exec('probe_value = 1')"),
            "expected_failure_fragments": ["audit denied capability: compile"],
        },
    ]
    return definitions


def main() -> int:
    definitions = probe_definitions()
    CASES.mkdir(parents=True, exist_ok=True)
    allowed_files: set[Path] = set()
    records = []
    for definition in definitions:
        probe_id = str(definition["id"])
        destination = CASES / probe_id / "output" / "analyze.py"
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.is_symlink():
            raise RuntimeError(f"refusing to replace linked probe: {destination}")
        source = str(definition["source"])
        destination.write_text(source, encoding="utf-8", newline="\n")
        allowed_files.add(destination.resolve())
        records.append(
            {
                "id": probe_id,
                "category": definition["category"],
                "purpose": definition["purpose"],
                "submission": f"cases/{probe_id}",
                "expected_passed": False,
                "expected_score": 0.0,
                "expected_failure_fragments": definition["expected_failure_fragments"],
                "source_bytes": destination.stat().st_size,
                "source_sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
            }
        )

    unexpected = [
        path.relative_to(ROOT).as_posix()
        for path in CASES.rglob("*")
        if path.is_file() and path.resolve() not in allowed_files
    ]
    if unexpected:
        raise RuntimeError(f"unexpected stale files under cases/: {sorted(unexpected)}")

    manifest = {
        "schema_version": "spectral-scaling-probes/v1",
        "description": "Deliberately invalid private robustness submissions; never participant-visible.",
        "submission_inventory": ["output/analyze.py"],
        "probe_count": len(records),
        "probes": records,
    }
    MANIFEST.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"built {len(records)} probes in {CASES}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
