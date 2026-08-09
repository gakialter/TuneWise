import os
from pathlib import Path

from .api import create_app


EXPECTED_PUBLIC_MANIFEST_HASH = (
    "2de0019bb69bc9d73c97811bf0362c6c390e2186abc10874d18e8e96bf34697c"
)
EXPECTED_DATASET_MANIFEST_HASH = (
    "d66077f880e6d4c470772be30a771ca20d26520ab39c08fc4f4340fa4e31950c"
)
EXPECTED_DIAGNOSTIC_MANIFEST_HASH = (
    "d2d287fcd830771c3b8c6e91f41152d950ea2a02820107c1ca802fb268b5ed4b"
)
EXPECTED_CASE_MANIFEST_HASH = (
    "3259575b170a617a9314a7c6883d829b64df9a022be7a90529bf7e50db7acb81"
)
EXPECTED_PLANNING_MANIFEST_HASH = (
    "fc73d61a29bcfbe89ab3b8f34cd0cf7436ff10c0716c59be8882b21be2881f4b"
)
EXPECTED_REPLAY_MANIFEST_HASH = (
    "8d4b3582e9509bf0a1b1b1aa44a0d43fbbd5972f8ab0fe497dcd5712a4ee8824"
)
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def create_production_app(repository_root: Path = REPOSITORY_ROOT):
    database_override = os.environ.get("TUNEWISE_DATABASE_PATH")
    database_path = (
        Path(database_override).resolve()
        if database_override
        else repository_root / "var" / "tunewise.db"
    )
    return create_app(
        public_asset_root=repository_root / "assets" / "public",
        expected_manifest_hash=EXPECTED_PUBLIC_MANIFEST_HASH,
        database_path=database_path,
        static_root=repository_root / "src" / "tunewise" / "static",
        demo_asset_root=repository_root / "assets" / "demo" / "tw-aa-demo-v1",
        expected_dataset_manifest_hash=EXPECTED_DATASET_MANIFEST_HASH,
        diagnostic_asset_root=repository_root / "assets" / "diagnostic" / "tw-diagnostic-v1",
        expected_diagnostic_manifest_hash=EXPECTED_DIAGNOSTIC_MANIFEST_HASH,
        case_asset_root=repository_root / "assets" / "cases" / "tw-approved-case-index-v1",
        expected_case_manifest_hash=EXPECTED_CASE_MANIFEST_HASH,
        planning_asset_root=repository_root / "assets" / "planning" / "tw-parameter-planning-v1",
        expected_planning_manifest_hash=EXPECTED_PLANNING_MANIFEST_HASH,
        replay_asset_root=repository_root / "assets" / "simulator-private" / "tw-replay-simulator-v1",
        expected_replay_manifest_hash=EXPECTED_REPLAY_MANIFEST_HASH,
    )


app = create_production_app()
