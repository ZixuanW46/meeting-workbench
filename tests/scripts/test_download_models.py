from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "download_models.sh"
SEGMENTATION_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"
)
EMBEDDING_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "speaker-recongition-models/"
    "3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx"
)


def _run(*, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    command_env = os.environ.copy()
    command_env.update(env)
    return subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=REPO_ROOT,
        env=command_env,
        check=False,
        capture_output=True,
        text=True,
        # macOS bash 3.2 的 printf %q 会把非 ASCII 仓库路径打成非法 UTF-8 字节，
        # 宽松解码保证断言仍在文本层进行，而不是在 decode 阶段炸掉。
        errors="backslashreplace",
    )


def _write_command_stub(bin_dir: Path, name: str, calls_file: Path) -> None:
    stub = bin_dir / name
    stub.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' '{name}' >> '{calls_file}'\n"
        "exit 97\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)


def test_download_models_script_is_executable_and_has_valid_bash_syntax():
    assert SCRIPT.is_file()
    assert SCRIPT.stat().st_mode & stat.S_IXUSR
    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)], check=False, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(
    sys.platform == "darwin", reason="断言的是非 macOS 的跳过分支，只能在 Linux 上验证"
)
def test_non_darwin_skips_without_creating_model_files(tmp_path):
    data_dir = tmp_path / "data"

    result = _run(env={"MW_DATA_DIR": str(data_dir)})

    assert result.returncode == 0, result.stderr
    assert "非 macOS，跳过模型下载" in result.stdout
    assert not list(tmp_path.rglob("*.onnx"))
    assert not list(tmp_path.rglob("*.safetensors"))


def test_dry_run_prints_all_downloads_without_network_or_writes(tmp_path):
    data_dir = tmp_path / "data"
    calls_file = tmp_path / "network-calls"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for command in ("curl", "hf"):
        _write_command_stub(bin_dir, command, calls_file)

    result = _run(
        env={
            "DRY_RUN": "1",
            "MW_DATA_DIR": str(data_dir),
            "MW_HF_CLI": str(bin_dir / "hf"),
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
        }
    )

    assert result.returncode == 0, result.stderr
    assert "hf download mlx-community/Qwen3-ASR-1.7B-8bit" in result.stdout
    assert SEGMENTATION_URL in result.stdout
    assert EMBEDDING_URL in result.stdout
    assert "segmentation.onnx" in result.stdout
    assert "embedding.onnx" in result.stdout
    assert "tar" in result.stdout
    # DRY RUN 与真实路径一致：find 定位归档子目录里的 model.onnx。
    assert "find" in result.stdout
    assert "sherpa-onnx-pyannote-segmentation-3-0/model.onnx" in result.stdout
    assert not calls_file.exists()
    assert not data_dir.exists()


def test_dry_run_prefers_configured_hf_cli_candidate_when_executable(tmp_path):
    data_dir = tmp_path / "data"
    calls_file = tmp_path / "network-calls"
    bin_dir = tmp_path / "bin"
    configured_bin_dir = tmp_path / "configured-bin"
    bin_dir.mkdir()
    configured_bin_dir.mkdir()
    _write_command_stub(bin_dir, "hf", calls_file)
    _write_command_stub(configured_bin_dir, "hf", calls_file)
    configured_hf = configured_bin_dir / "hf"

    result = _run(
        env={
            "DRY_RUN": "1",
            "MW_DATA_DIR": str(data_dir),
            "MW_HF_CLI": str(configured_hf),
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
        }
    )

    assert result.returncode == 0, result.stderr
    assert f"{configured_hf} download mlx-community/Qwen3-ASR-1.7B-8bit" in result.stdout
    assert not calls_file.exists()
    assert not data_dir.exists()


def test_dry_run_falls_back_to_bare_hf_when_configured_candidate_is_missing(tmp_path):
    data_dir = tmp_path / "data"
    calls_file = tmp_path / "network-calls"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_command_stub(bin_dir, "hf", calls_file)

    result = _run(
        env={
            "DRY_RUN": "1",
            "MW_DATA_DIR": str(data_dir),
            "MW_HF_CLI": str(tmp_path / "missing-hf"),
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
        }
    )

    assert result.returncode == 0, result.stderr
    assert "[DRY RUN] hf download mlx-community/Qwen3-ASR-1.7B-8bit" in result.stdout
    assert not calls_file.exists()
    assert not data_dir.exists()


def test_existing_models_do_not_invoke_download_commands(tmp_path):
    data_dir = tmp_path / "data"
    asr_dir = data_dir / "models" / "qwen3-asr-mlx"
    sherpa_dir = data_dir / "models" / "sherpa-onnx"
    asr_dir.mkdir(parents=True)
    sherpa_dir.mkdir(parents=True)
    (asr_dir / "config.json").write_text("{}", encoding="utf-8")
    (sherpa_dir / "segmentation.onnx").write_bytes(b"existing")
    (sherpa_dir / "embedding.onnx").write_bytes(b"existing")
    calls_file = tmp_path / "download-calls"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for command in ("curl", "hf"):
        _write_command_stub(bin_dir, command, calls_file)

    result = _run(
        env={
            # 仅供 Linux 测试覆盖 Darwin 下载分支，生产安装不应设置此变量。
            "MW_FORCE_DARWIN": "1",
            "MW_DATA_DIR": str(data_dir),
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
        }
    )

    assert result.returncode == 0, result.stderr
    assert not calls_file.exists()
    assert (asr_dir / "config.json").read_text(encoding="utf-8") == "{}"
    assert (sherpa_dir / "segmentation.onnx").read_bytes() == b"existing"
    assert (sherpa_dir / "embedding.onnx").read_bytes() == b"existing"
