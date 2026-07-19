from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .simulator_core import FrozenMeasurement, simulate_observations


class SimulatorGatewayError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class SimulationRequest:
    scenario_ref: str
    scenario_ref_hash: str
    simulator_version: str
    replay_scenario_schema_version: str
    scenario_mapping_version: str
    sample_count: int
    seed: int
    disturbance_sequence_hash: str
    parameters: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class SimulationBinding:
    scenario_ref_hash: str
    hidden_scenario_content_hash: str
    disturbance_sequence_hash: str
    simulator_version: str
    replay_scenario_schema_version: str
    scenario_mapping_version: str
    sample_count: int
    seed_hash: str


@dataclass(frozen=True, slots=True)
class SimulationRun:
    measurements: tuple[FrozenMeasurement, ...]
    binding: SimulationBinding


@dataclass(frozen=True, slots=True)
class SimulatorAssetBinding:
    simulator_version: str
    replay_scenario_schema_version: str
    scenario_mapping_version: str
    fixed_seed: int
    scenario_ref_hash: str
    disturbance_sequence_hash: str
    simulator_policy_hash: str
    canonical_manifest_hash: str


def canonical_json_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_manifest_hash(payload: Mapping[str, Any]) -> str:
    canonical_payload = dict(payload)
    canonical_payload.pop("canonical_manifest_hash", None)
    return hashlib.sha256(canonical_json_bytes(canonical_payload)).hexdigest()


class LocalSimulatorGateway:
    def __init__(self, root: Path, expected_manifest_hash: str) -> None:
        self._root = root.resolve()
        self._expected_manifest_hash = expected_manifest_hash
        self.call_count = 0

    def _read(self, relative_path: str) -> bytes:
        pure = PurePosixPath(relative_path)
        if pure.is_absolute() or ".." in pure.parts:
            raise SimulatorGatewayError("SIMULATOR_ASSET_INVALID", "模拟器资产路径无效。")
        path = (self._root / Path(*pure.parts)).resolve()
        if not path.is_relative_to(self._root):
            raise SimulatorGatewayError("SIMULATOR_ASSET_INVALID", "模拟器资产路径无效。")
        try:
            return path.read_bytes()
        except FileNotFoundError as error:
            raise SimulatorGatewayError("SIMULATOR_ASSET_MISSING", "模拟器资产缺失。") from error

    @staticmethod
    def _json(content: bytes) -> dict[str, Any]:
        try:
            payload = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SimulatorGatewayError("SIMULATOR_ASSET_INVALID", "模拟器资产格式无效。") from error
        if not isinstance(payload, dict):
            raise SimulatorGatewayError("SIMULATOR_ASSET_INVALID", "模拟器资产格式无效。")
        return payload

    def _assets(self) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        manifest = self._json(self._read("manifest.json"))
        actual_manifest_hash = canonical_manifest_hash(manifest)
        if (
            actual_manifest_hash != self._expected_manifest_hash
            or manifest.get("canonical_manifest_hash") != actual_manifest_hash
        ):
            raise SimulatorGatewayError("SIMULATOR_ASSET_HASH_MISMATCH", "模拟器资产清单哈希不匹配。")
        files = manifest.get("files")
        if not isinstance(files, dict):
            raise SimulatorGatewayError("SIMULATOR_ASSET_INVALID", "模拟器资产清单格式无效。")
        loaded: dict[str, dict[str, Any]] = {}
        for relative_path, expected_hash in files.items():
            content = self._read(relative_path)
            if hashlib.sha256(content).hexdigest() != expected_hash:
                raise SimulatorGatewayError("SIMULATOR_ASSET_HASH_MISMATCH", "模拟器资产内容哈希不匹配。")
            loaded[relative_path] = self._json(content)
        mapping = loaded.get(str(manifest.get("scenario_mapping_file")))
        disturbance = loaded.get(str(manifest.get("disturbance_sequence_file")))
        if mapping is None or disturbance is None:
            raise SimulatorGatewayError("SIMULATOR_ASSET_INVALID", "模拟器映射或扰动资产缺失。")
        if disturbance.get("fixed_seed") != manifest.get("fixed_seed"):
            raise SimulatorGatewayError("SIMULATOR_ASSET_INVALID", "模拟器扰动 seed 绑定无效。")
        return manifest, mapping, disturbance

    def run(self, request: SimulationRequest) -> SimulationRun:
        manifest, mapping, disturbance = self._assets()
        if (
            not re.fullmatch(r"scn_[0-9a-f]{32}", request.scenario_ref)
            or hashlib.sha256(request.scenario_ref.encode("utf-8")).hexdigest()
            != request.scenario_ref_hash
            or request.scenario_ref_hash != manifest.get("scenario_ref_hash")
        ):
            raise SimulatorGatewayError("SCENARIO_REFERENCE_INVALID", "场景引用无法解析。")
        for field in (
            "simulator_version",
            "replay_scenario_schema_version",
            "scenario_mapping_version",
        ):
            if getattr(request, field) != manifest.get(field):
                raise SimulatorGatewayError("SIMULATOR_VERSION_MISMATCH", "模拟器版本绑定不匹配。")
        if (
            request.seed != manifest.get("fixed_seed")
            or request.disturbance_sequence_hash != manifest.get("disturbance_sequence_hash")
        ):
            raise SimulatorGatewayError("SIMULATOR_INPUT_MISMATCH", "模拟器固定输入绑定不匹配。")
        matches = [
            item
            for item in mapping.get("mappings", [])
            if item.get("scenario_ref") == request.scenario_ref
            and item.get("scenario_ref_hash") == request.scenario_ref_hash
        ]
        if len(matches) != 1:
            raise SimulatorGatewayError("SCENARIO_REFERENCE_INVALID", "场景引用无法解析。")
        scenario_file = matches[0].get("scenario_asset_file")
        if not isinstance(scenario_file, str) or scenario_file not in manifest["files"]:
            raise SimulatorGatewayError("SIMULATOR_ASSET_INVALID", "隐藏场景映射无效。")
        scenario = self._json(self._read(scenario_file))
        if hashlib.sha256(self._read(scenario_file)).hexdigest() != manifest.get(
            "hidden_scenario_content_hash"
        ):
            raise SimulatorGatewayError("SIMULATOR_ASSET_HASH_MISMATCH", "隐藏场景资产哈希不匹配。")
        if hashlib.sha256(self._read(manifest["disturbance_sequence_file"])).hexdigest() != manifest.get(
            "disturbance_sequence_hash"
        ):
            raise SimulatorGatewayError("SIMULATOR_ASSET_HASH_MISMATCH", "扰动序列哈希不匹配。")
        measurements = simulate_observations(
            scenario,
            disturbance,
            request.parameters,
            request.sample_count,
        )
        self.call_count += 1
        return SimulationRun(
            measurements=measurements,
            binding=SimulationBinding(
                scenario_ref_hash=request.scenario_ref_hash,
                hidden_scenario_content_hash=manifest["hidden_scenario_content_hash"],
                disturbance_sequence_hash=request.disturbance_sequence_hash,
                simulator_version=request.simulator_version,
                replay_scenario_schema_version=request.replay_scenario_schema_version,
                scenario_mapping_version=request.scenario_mapping_version,
                sample_count=request.sample_count,
                seed_hash=hashlib.sha256(str(request.seed).encode("ascii")).hexdigest(),
            ),
        )

    def asset_binding(self) -> SimulatorAssetBinding:
        manifest, _mapping, _disturbance = self._assets()
        try:
            return SimulatorAssetBinding(
                simulator_version=manifest["simulator_version"],
                replay_scenario_schema_version=manifest["replay_scenario_schema_version"],
                scenario_mapping_version=manifest["scenario_mapping_version"],
                fixed_seed=manifest["fixed_seed"],
                scenario_ref_hash=manifest["scenario_ref_hash"],
                disturbance_sequence_hash=manifest["disturbance_sequence_hash"],
                simulator_policy_hash=manifest["simulator_policy_hash"],
                canonical_manifest_hash=manifest["canonical_manifest_hash"],
            )
        except (KeyError, TypeError, ValueError) as error:
            raise SimulatorGatewayError("SIMULATOR_ASSET_INVALID", "模拟器资产绑定无效。") from error
