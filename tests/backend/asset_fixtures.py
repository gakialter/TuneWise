from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


VERSION_ASSET: dict[str, Any] = {
    "public_asset_version": "tw-public-v1",
    "application_version": "0.1.0",
    "dataset_version": "tw-dataset-v1",
    "schema_version": "tw-schema-v1",
    "rule_set_version": "tw-rules-v1",
    "model_version": "tw-model-v1",
    "preprocessing_version": "tw-preprocessing-v1",
    "evaluation_rule_version": "tw-evaluation-v1",
    "canonicalizer_version": "tw-canonicalizer-v1",
    "actor": {
        "actor_id": "demo-aa-engineer",
        "actor_role": "AA_PROCESS_ENGINEER",
        "display_name": "AA工艺工程师",
    },
}


def write_public_assets(
    root: Path,
    *,
    version_asset: dict[str, Any] | None = None,
    manifest_public_version: str = "tw-public-v1",
) -> str:
    root.mkdir(parents=True, exist_ok=True)
    version_bytes = json.dumps(
        version_asset or VERSION_ASSET,
        ensure_ascii=False,
        indent=2,
    ).encode("utf-8") + b"\n"
    (root / "version.json").write_bytes(version_bytes)
    manifest = {
        "manifest_version": "1",
        "public_asset_version": manifest_public_version,
        "files": {
            "version.json": hashlib.sha256(version_bytes).hexdigest(),
        },
    }
    manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8") + b"\n"
    (root / "manifest.json").write_bytes(manifest_bytes)
    return hashlib.sha256(manifest_bytes).hexdigest()
