"""
Versioned ComfyUI workflow templates.

Each workflow ships as `<name>_<version>.json` (API format) plus a
`<name>_<version>.manifest.json` describing its patchable inputs, so node IDs
live in exactly one place. Business code patches by input name, never node ID.
"""
import copy
import json
from pathlib import Path

WORKFLOWS_DIR = Path(__file__).resolve().parent / "workflows"


class WorkflowError(Exception):
    pass


def load_workflow(name: str, version: str = "v1"):
    """Returns (graph, manifest) for a workflow template."""
    graph_path = WORKFLOWS_DIR / f"{name}_{version}.json"
    manifest_path = WORKFLOWS_DIR / f"{name}_{version}.manifest.json"
    if not graph_path.exists():
        raise WorkflowError(f"Workflow template not found: {graph_path.name}")
    if not manifest_path.exists():
        raise WorkflowError(f"Workflow manifest not found: {manifest_path.name}")
    with graph_path.open(encoding="utf-8") as fh:
        graph = json.load(fh)
    with manifest_path.open(encoding="utf-8") as fh:
        manifest = json.load(fh)
    return graph, manifest


def patch_workflow(graph: dict, manifest: dict, **inputs) -> dict:
    """Return a deep-copied graph with the given named inputs applied.

    Manifest format: {"inputs": {"image": ["1", "image"],
                                  "seed": [["13", "noise_seed"], ["14", "noise_seed"]]}}
    A single [node, field] pair or a list of pairs (same value to many nodes).
    """
    patched = copy.deepcopy(graph)
    available = manifest.get("inputs", {})
    for key, value in inputs.items():
        if value is None:
            continue
        if key not in available:
            raise WorkflowError(
                f"Unknown workflow input '{key}'. Available: {sorted(available)}"
            )
        target = available[key]
        if not target:
            raise WorkflowError(f"Manifest input '{key}' has no target")
        targets = target if isinstance(target[0], list) else [target]
        for node_id, field in targets:
            if node_id not in patched:
                raise WorkflowError(f"Manifest points to missing node '{node_id}'")
            if field not in patched[node_id]["inputs"]:
                raise WorkflowError(
                    f"Manifest input '{key}' points to unknown field '{field}' "
                    f"on node {node_id} ({patched[node_id].get('class_type')})"
                )
            patched[node_id]["inputs"][field] = value
    return patched
