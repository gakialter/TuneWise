from __future__ import annotations

import hashlib

import pytest

from tunewise.assets import AssetIntegrityError, PublicAssetLoader

from .asset_fixtures import VERSION_ASSET, write_public_assets


def test_valid_public_assets_load_fixed_identity_and_read_only_versions(tmp_path):
    expected_manifest_hash = write_public_assets(tmp_path)

    snapshot = PublicAssetLoader(
        root=tmp_path,
        expected_manifest_hash=expected_manifest_hash,
    ).load()

    assert snapshot.actor.actor_id == "demo-aa-engineer"
    assert snapshot.actor.actor_role == "AA_PROCESS_ENGINEER"
    assert snapshot.actor.display_name == "AA工艺工程师"
    assert snapshot.versions.public_asset_version == "tw-public-v1"
    with pytest.raises(AttributeError):
        snapshot.versions.application_version = "tampered"  # type: ignore[misc]


def test_missing_public_asset_is_rejected(tmp_path):
    expected_manifest_hash = write_public_assets(tmp_path)
    (tmp_path / "version.json").unlink()

    with pytest.raises(AssetIntegrityError) as error:
        PublicAssetLoader(tmp_path, expected_manifest_hash).load()

    assert error.value.code == "PUBLIC_ASSET_MISSING"


def test_tampered_public_asset_is_rejected(tmp_path):
    expected_manifest_hash = write_public_assets(tmp_path)
    (tmp_path / "version.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(AssetIntegrityError) as error:
        PublicAssetLoader(tmp_path, expected_manifest_hash).load()

    assert error.value.code == "PUBLIC_ASSET_HASH_MISMATCH"


def test_manifest_tampering_is_rejected_by_embedded_root_hash(tmp_path):
    expected_manifest_hash = write_public_assets(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        manifest_path.read_text(encoding="utf-8").replace("tw-public-v1", "forged"),
        encoding="utf-8",
    )

    with pytest.raises(AssetIntegrityError) as error:
        PublicAssetLoader(tmp_path, expected_manifest_hash).load()

    assert error.value.code == "PUBLIC_MANIFEST_HASH_MISMATCH"


def test_inconsistent_public_asset_version_is_rejected(tmp_path):
    version_asset = dict(VERSION_ASSET)
    version_asset["public_asset_version"] = "tw-public-v2"
    expected_manifest_hash = write_public_assets(
        tmp_path,
        version_asset=version_asset,
        manifest_public_version="tw-public-v1",
    )

    with pytest.raises(AssetIntegrityError) as error:
        PublicAssetLoader(tmp_path, expected_manifest_hash).load()

    assert error.value.code == "PUBLIC_ASSET_VERSION_MISMATCH"


def test_asset_reader_cannot_escape_public_root(tmp_path):
    public_root = tmp_path / "public"
    expected_manifest_hash = write_public_assets(public_root)
    isolated_file = tmp_path / "isolated" / "labels.json"
    isolated_file.parent.mkdir()
    isolated_file.write_text('{"sentinel": true}', encoding="utf-8")
    loader = PublicAssetLoader(public_root, expected_manifest_hash)

    with pytest.raises(AssetIntegrityError) as error:
        loader.read_bytes("../isolated/labels.json")

    assert error.value.code == "PUBLIC_ASSET_PATH_FORBIDDEN"
    assert hashlib.sha256(isolated_file.read_bytes()).hexdigest()
