from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from enum import StrEnum
from pathlib import Path
from typing import Any

from tunewise.shadow_analysis import (
    ShadowAnalysisContract,
    ShadowAnalysisError,
    ShadowAnalysisRunner,
)
from tunewise.shadow_data import ShadowDataAdapter, ShadowDataImportError


def _plain(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate an explicitly mapped TuneWise shadow-data CSV",
    )
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--analysis-contract", type=Path)
    args = parser.parse_args()
    try:
        csv_bytes = args.csv.read_bytes()
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        _fail("MAPPING_INVALID", f"无法读取 CSV 或 mapping manifest：{error}")
    try:
        dataset = ShadowDataAdapter().import_csv(csv_bytes, manifest)
    except ShadowDataImportError as error:
        _fail(
            error.code,
            error.message,
            quality_report=(
                None
                if error.quality_report is None
                else _plain(asdict(error.quality_report))
            ),
        )
    analysis_result = None
    if args.analysis_contract is not None:
        try:
            contract_payload = json.loads(
                args.analysis_contract.read_text(encoding="utf-8")
            )
            contract = ShadowAnalysisContract.from_payload(contract_payload)
            repository_root = Path(__file__).resolve().parents[1]
            analysis_result = ShadowAnalysisRunner(
                diagnostic_asset_root=(
                    repository_root / "assets" / "diagnostic" / "tw-diagnostic-v1"
                ),
                planning_asset_root=(
                    repository_root
                    / "assets"
                    / "planning"
                    / "tw-parameter-planning-v1"
                ),
            ).run(dataset, contract)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            _fail(
                "ANALYSIS_CONTRACT_INVALID",
                f"无法读取影子分析契约：{error}",
                quality_report=_plain(asdict(dataset.quality_report)),
            )
        except ShadowAnalysisError as error:
            _fail(
                error.code,
                error.message,
                quality_report=_plain(asdict(dataset.quality_report)),
            )
    reported_quality = (
        dataset.quality_report
        if analysis_result is None
        else analysis_result.quality_report
    )
    payload = {
        "status": dataset.quality_report.status.value,
        "source_type": dataset.source_type.value,
        "source_metadata": dict(dataset.source_metadata),
        "source_authenticity_status": dataset.source_authenticity_status,
        "mapping_version": dataset.mapping_version,
        "raw_file_sha256": dataset.raw_file_sha256,
        "canonical_observation_sha256": dataset.canonical_observation_sha256,
        "storage_partition": dataset.storage_partition,
        "eligible_for_training": dataset.eligible_for_training,
        "eligible_for_approved_case_library": (
            dataset.eligible_for_approved_case_library
        ),
        "quality_report": _plain(asdict(reported_quality)),
        "analysis_result": (
            None if analysis_result is None else _plain(asdict(analysis_result))
        ),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _fail(
    status: str,
    message: str,
    *,
    quality_report: Any = None,
) -> None:
    print(
        json.dumps(
            {
                "status": status,
                "message": message,
                "quality_report": quality_report,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    raise SystemExit(2) from None


if __name__ == "__main__":
    main()
