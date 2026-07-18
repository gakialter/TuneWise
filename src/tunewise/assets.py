from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .domain import Actor, PublicAssetSnapshot, VersionSnapshot


EXPECTED_ACTOR = Actor(
    actor_id="demo-aa-engineer",
    actor_role="AA_PROCESS_ENGINEER",
    display_name="AA工艺工程师",
)


class AssetIntegrityError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class ContentHasher:
    def sha256(self, content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()


class PublicAssetLoader:
    def __init__(
        self,
        root: Path,
        expected_manifest_hash: str,
        hasher: ContentHasher | None = None,
    ) -> None:
        self._root = root.resolve()
        self._expected_manifest_hash = expected_manifest_hash
        self._hasher = hasher or ContentHasher()

    def read_bytes(self, relative_path: str) -> bytes:
        pure_path = PurePosixPath(relative_path)
        if pure_path.is_absolute() or ".." in pure_path.parts:
            raise AssetIntegrityError(
                "PUBLIC_ASSET_PATH_FORBIDDEN",
                "运行时只允许读取公共版本资产目录。",
            )
        path = (self._root / Path(*pure_path.parts)).resolve()
        if not path.is_relative_to(self._root):
            raise AssetIntegrityError(
                "PUBLIC_ASSET_PATH_FORBIDDEN",
                "运行时只允许读取公共版本资产目录。",
            )
        try:
            return path.read_bytes()
        except FileNotFoundError as error:
            raise AssetIntegrityError(
                "PUBLIC_ASSET_MISSING",
                f"缺失公共版本资产：{relative_path}",
            ) from error

    def load(self) -> PublicAssetSnapshot:
        manifest_bytes = self.read_bytes("manifest.json")
        if self._hasher.sha256(manifest_bytes) != self._expected_manifest_hash:
            raise AssetIntegrityError(
                "PUBLIC_MANIFEST_HASH_MISMATCH",
                "公共版本资产清单已被篡改。",
            )
        manifest = self._parse_json(manifest_bytes, "manifest.json")
        if manifest.get("manifest_version") != "1":
            raise AssetIntegrityError(
                "PUBLIC_ASSET_VERSION_MISMATCH",
                "公共版本资产清单版本不受支持。",
            )
        expected_file_hash = manifest.get("files", {}).get("version.json")
        version_bytes = self.read_bytes("version.json")
        if not expected_file_hash or self._hasher.sha256(version_bytes) != expected_file_hash:
            raise AssetIntegrityError(
                "PUBLIC_ASSET_HASH_MISMATCH",
                "公共版本资产内容哈希不匹配。",
            )
        payload = self._parse_json(version_bytes, "version.json")
        if payload.get("public_asset_version") != manifest.get("public_asset_version"):
            raise AssetIntegrityError(
                "PUBLIC_ASSET_VERSION_MISMATCH",
                "公共版本资产版本与清单不一致。",
            )
        return PublicAssetSnapshot(
            actor=self._load_actor(payload),
            versions=self._load_versions(payload),
        )

    @staticmethod
    def _parse_json(content: bytes, filename: str) -> dict[str, Any]:
        try:
            payload = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise AssetIntegrityError(
                "PUBLIC_ASSET_INVALID",
                f"公共版本资产格式无效：{filename}",
            ) from error
        if not isinstance(payload, dict):
            raise AssetIntegrityError(
                "PUBLIC_ASSET_INVALID",
                f"公共版本资产格式无效：{filename}",
            )
        return payload

    @staticmethod
    def _load_actor(payload: dict[str, Any]) -> Actor:
        actor_payload = payload.get("actor")
        try:
            actor = Actor(
                actor_id=actor_payload["actor_id"],
                actor_role=actor_payload["actor_role"],
                display_name=actor_payload["display_name"],
            )
        except (KeyError, TypeError) as error:
            raise AssetIntegrityError(
                "PUBLIC_ASSET_INVALID",
                "公共版本资产缺少固定演示身份。",
            ) from error
        if actor != EXPECTED_ACTOR:
            raise AssetIntegrityError(
                "PUBLIC_ASSET_IDENTITY_MISMATCH",
                "公共版本资产中的固定演示身份不一致。",
            )
        return actor

    @staticmethod
    def _load_versions(payload: dict[str, Any]) -> VersionSnapshot:
        try:
            versions = VersionSnapshot(
                public_asset_version=payload["public_asset_version"],
                application_version=payload["application_version"],
                dataset_version=payload["dataset_version"],
                schema_version=payload["schema_version"],
                rule_set_version=payload["rule_set_version"],
                model_version=payload["model_version"],
                preprocessing_version=payload["preprocessing_version"],
                evaluation_rule_version=payload["evaluation_rule_version"],
                canonicalizer_version=payload["canonicalizer_version"],
            )
        except KeyError as error:
            raise AssetIntegrityError(
                "PUBLIC_ASSET_INVALID",
                f"公共版本资产缺少版本字段：{error.args[0]}",
            ) from error
        if not all(
            isinstance(value, str) and value
            for value in (
                versions.public_asset_version,
                versions.application_version,
                versions.dataset_version,
                versions.schema_version,
                versions.rule_set_version,
                versions.model_version,
                versions.preprocessing_version,
                versions.evaluation_rule_version,
                versions.canonicalizer_version,
            )
        ):
            raise AssetIntegrityError(
                "PUBLIC_ASSET_INVALID",
                "公共版本资产包含无效版本值。",
            )
        return versions
