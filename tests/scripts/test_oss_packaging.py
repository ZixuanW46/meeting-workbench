from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_license_is_mit_and_names_copyright_holder():
    license_text = (REPO_ROOT / "LICENSE").read_text(encoding="utf-8")

    assert "MIT License" in license_text
    assert "Copyright (c) 2026 Will" in license_text
    assert "Permission is hereby granted, free of charge" in license_text


def test_readme_uses_mac_installer_as_primary_quickstart():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    clone = readme.index("git clone <repo> && cd meeting-workbench")
    install = readme.index("./scripts/mac_install.sh")
    assert clone < install
    assert "claude /login" in readme
    assert "codex login" in readme
    assert "Ant Design" not in readme
    assert "起两个终端" not in readme
    assert "make migrate" not in readme[:install]


def test_readme_documents_runtime_privacy_and_development_requirements():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    for expected in (
        "macOS",
        "Apple Silicon",
        "Homebrew",
        "ffmpeg",
        "公开模型无需 Hugging Face token",
        "127.0.0.1:8000",
        "音频不出本机",
        "本机 CLI",
        "禁止 `--bare`",
        "make setup",
        "make test",
        "make dev-api",
        "make dev-web",
        "./scripts/test.sh",
        "Linear",
    ):
        assert expected in readme


def test_gitignore_excludes_local_secrets_logs_and_backups():
    ignored = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

    for pattern in (".env", ".env.local", "*.log", "backups/"):
        assert pattern in ignored


def test_github_actions_runs_fake_tests_and_lint_without_model_downloads():
    workflow_dir = REPO_ROOT / ".github" / "workflows"
    workflows = sorted((*workflow_dir.glob("*.yml"), *workflow_dir.glob("*.yaml")))
    assert workflows

    workflow = "\n".join(path.read_text(encoding="utf-8") for path in workflows)
    assert "ubuntu-latest" in workflow
    assert "python-version: \"3.12\"" in workflow
    assert "node-version: \"22\"" in workflow
    assert 'pip install -e ".[dev]"' in workflow
    assert ".[mac]" not in workflow
    assert "make test" in workflow
    assert "make lint" in workflow
    for backend in (
        "MW_ASR_BACKEND: fake",
        "MW_DIARIZATION_BACKEND: fake",
        "MW_EMBEDDING_BACKEND: fake",
        "MW_MINUTES_BACKEND: fake",
    ):
        assert backend in workflow
    assert "wget" not in workflow
    assert "huggingface-cli" not in workflow
    assert "huggingface.co" not in workflow
