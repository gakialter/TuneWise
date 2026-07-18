from pathlib import Path

from .api import create_app


EXPECTED_PUBLIC_MANIFEST_HASH = (
    "1e42c9a0225911740d52e1975f0dac836fe3c476b30ce6d79926a5136c5a71b2"
)
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def create_production_app(repository_root: Path = REPOSITORY_ROOT):
    return create_app(
        public_asset_root=repository_root / "assets" / "public",
        expected_manifest_hash=EXPECTED_PUBLIC_MANIFEST_HASH,
        database_path=repository_root / "var" / "tunewise.db",
        static_root=repository_root / "src" / "tunewise" / "static",
    )


app = create_production_app()
