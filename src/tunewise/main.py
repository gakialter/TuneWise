from pathlib import Path

from .api import create_app


EXPECTED_PUBLIC_MANIFEST_HASH = (
    "2de0019bb69bc9d73c97811bf0362c6c390e2186abc10874d18e8e96bf34697c"
)
EXPECTED_DATASET_MANIFEST_HASH = (
    "d66077f880e6d4c470772be30a771ca20d26520ab39c08fc4f4340fa4e31950c"
)
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def create_production_app(repository_root: Path = REPOSITORY_ROOT):
    return create_app(
        public_asset_root=repository_root / "assets" / "public",
        expected_manifest_hash=EXPECTED_PUBLIC_MANIFEST_HASH,
        database_path=repository_root / "var" / "tunewise.db",
        static_root=repository_root / "src" / "tunewise" / "static",
        demo_asset_root=repository_root / "assets" / "demo" / "tw-aa-demo-v1",
        expected_dataset_manifest_hash=EXPECTED_DATASET_MANIFEST_HASH,
    )


app = create_production_app()
