from __future__ import annotations

import sys

from meeting_api.config import Settings
from meeting_api.pipeline.asr import (
    FakeAsrBackend,
    Qwen3AsrMlxBackend,
    get_asr_backend,
)
from meeting_api.pipeline.diarization import (
    FakeDiarizationBackend,
    SherpaOnnxDiarizationBackend,
    get_diarization_backend,
)
from meeting_api.pipeline.embedding import (
    FakeEmbeddingBackend,
    SherpaOnnxEmbeddingBackend,
    get_embedding_backend,
)


def test_model_backend_settings_default_to_auto(monkeypatch):
    for name in ("MW_ASR_BACKEND", "MW_DIARIZATION_BACKEND", "MW_EMBEDDING_BACKEND"):
        monkeypatch.delenv(name, raising=False)

    settings = Settings()

    assert settings.asr_backend == "auto"
    assert settings.diarization_backend == "auto"
    assert settings.embedding_backend == "auto"


def test_auto_backends_use_fake_on_linux_even_when_model_files_exist(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(sys, "platform", "linux")
    _create_model_files(tmp_path)

    assert isinstance(get_asr_backend("auto", tmp_path), FakeAsrBackend)
    assert isinstance(get_diarization_backend("auto", tmp_path), FakeDiarizationBackend)
    assert isinstance(get_embedding_backend("auto", tmp_path), FakeEmbeddingBackend)


def test_auto_backends_use_real_implementations_on_darwin_with_models(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(sys, "platform", "darwin")
    _create_model_files(tmp_path)

    assert isinstance(get_asr_backend("auto", tmp_path), Qwen3AsrMlxBackend)
    assert isinstance(
        get_diarization_backend("auto", tmp_path), SherpaOnnxDiarizationBackend
    )
    assert isinstance(
        get_embedding_backend("auto", tmp_path), SherpaOnnxEmbeddingBackend
    )


def test_auto_backends_fall_back_independently_when_corresponding_model_is_missing(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(sys, "platform", "darwin")
    (tmp_path / "sherpa-onnx").mkdir()
    (tmp_path / "sherpa-onnx" / "embedding.onnx").touch()

    assert isinstance(get_asr_backend("auto", tmp_path), FakeAsrBackend)
    assert isinstance(get_diarization_backend("auto", tmp_path), FakeDiarizationBackend)
    assert isinstance(
        get_embedding_backend("auto", tmp_path), SherpaOnnxEmbeddingBackend
    )


def _create_model_files(models_dir):
    qwen_dir = models_dir / "qwen3-asr-mlx"
    qwen_dir.mkdir(parents=True)
    (qwen_dir / "config.json").touch()
    sherpa_dir = models_dir / "sherpa-onnx"
    sherpa_dir.mkdir()
    (sherpa_dir / "segmentation.onnx").touch()
    (sherpa_dir / "embedding.onnx").touch()
