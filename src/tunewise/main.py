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
    "5cc047c8b71cab297b8fca614976e9ce98e6b0bfd7a5c29876780410d74c4dc7"
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
        diagnostic_asset_root=repository_root / "assets" / "diagnostic" / "tw-diagnostic-v1",
        expected_diagnostic_manifest_hash=EXPECTED_DIAGNOSTIC_MANIFEST_HASH,
        case_asset_root=repository_root / "assets" / "cases" / "tw-approved-case-index-v1",
        expected_case_manifest_hash=EXPECTED_CASE_MANIFEST_HASH,
    )


app = create_production_app()
