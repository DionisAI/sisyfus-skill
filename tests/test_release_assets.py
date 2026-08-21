from pathlib import Path
def test_release_assets():
 r=Path(__file__).resolve().parents[1];w=(r/".github/workflows/release.yml").read_text();b=(r/"scripts/build_release_assets.py").read_text();assert "release-manifest.json" in w and "archive_sha256" in b
def test_version_docs():
 r=Path(__file__).resolve().parents[1];assert 'version = "0.8.1"' in (r/"pyproject.toml").read_text();assert "sisyfus update --rollback" in (r/"README.md").read_text()
