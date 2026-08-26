from __future__ import annotations

import builtins
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from meeting_api.config import Settings
from meeting_api.main import create_app
from meeting_api.pipeline.asr import FakeAsrBackend, Qwen3AsrMlxBackend, get_asr_backend
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
from meeting_api.pipeline.serial import LoadableModel
from meeting_api.worker import Worker


def test_backend_settings_default_to_fake(monkeypatch):
    for name in ("MW_ASR_BACKEND", "MW_DIARIZATION_BACKEND", "MW_EMBEDDING_BACKEND"):
        monkeypatch.delenv(name, raising=False)

    settings = Settings()

    assert settings.asr_backend == "fake"
    assert settings.diarization_backend == "fake"
    assert settings.embedding_backend == "fake"


def test_backend_settings_read_environment(monkeypatch):
    monkeypatch.setenv("MW_ASR_BACKEND", "qwen3-asr-mlx")
    monkeypatch.setenv("MW_DIARIZATION_BACKEND", "sherpa-onnx")
    monkeypatch.setenv("MW_EMBEDDING_BACKEND", "sherpa-onnx")

    settings = Settings()

    assert settings.asr_backend == "qwen3-asr-mlx"
    assert settings.diarization_backend == "sherpa-onnx"
    assert settings.embedding_backend == "sherpa-onnx"


def test_create_app_defaults_to_fake_backends_without_importing_real_runtimes(
    monkeypatch, tmp_path
):
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "mlx" or name.startswith(("mlx.", "mlx_audio", "sherpa_onnx")):
            raise AssertionError(f"默认 fake 路径不应导入真实模型包: {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{tmp_path}/test.sqlite3",
        worker_disabled=True,
        minutes_backend="fake",
    )

    with TestClient(create_app(settings)) as client:
        worker = client.app.state.worker
        assert isinstance(worker.asr_backend, FakeAsrBackend)
        assert isinstance(worker.diarization_backend, FakeDiarizationBackend)
        assert isinstance(worker.embedding_backend, FakeEmbeddingBackend)


def test_worker_selects_backends_from_settings(monkeypatch, tmp_path):
    selected: list[tuple[str, str, Path]] = []

    def select(kind, backend):
        def factory(name, models_dir):
            selected.append((kind, name, models_dir))
            return backend

        return factory

    monkeypatch.setattr(
        "meeting_api.worker.get_asr_backend",
        select("asr", FakeAsrBackend()),
    )
    monkeypatch.setattr(
        "meeting_api.worker.get_diarization_backend",
        select("diarization", FakeDiarizationBackend()),
    )
    monkeypatch.setattr(
        "meeting_api.worker.get_embedding_backend",
        select("embedding", FakeEmbeddingBackend()),
    )
    settings = Settings(
        data_dir=tmp_path,
        asr_backend="qwen3-asr-mlx",
        diarization_backend="sherpa-onnx",
        embedding_backend="sherpa-onnx",
        minutes_backend="fake",
    )

    Worker(SimpleNamespace(), settings)

    assert selected == [
        ("asr", "qwen3-asr-mlx", tmp_path / "models"),
        ("diarization", "sherpa-onnx", tmp_path / "models"),
        ("embedding", "sherpa-onnx", tmp_path / "models"),
    ]


@pytest.mark.parametrize(
    ("factory", "name"),
    [
        (get_asr_backend, "qwen3-asr-mlx"),
        (get_diarization_backend, "sherpa-onnx"),
        (get_embedding_backend, "sherpa-onnx"),
    ],
)
def test_real_backends_have_clear_non_macos_error(monkeypatch, factory, name):
    monkeypatch.setattr(sys, "platform", "linux")

    with pytest.raises(RuntimeError, match="仅支持 macOS"):
        factory(name, Path("data/models"))


def _install_fake_mlx(monkeypatch, events):
    mlx = ModuleType("mlx")
    core = ModuleType("mlx.core")
    core.clear_cache = lambda: events.append("mlx:clear_cache")
    mlx.core = core

    mlx_audio = ModuleType("mlx_audio")
    stt = ModuleType("mlx_audio.stt")
    model = SimpleNamespace(generate=lambda *_args, **_kwargs: None)

    def load(path):
        events.append(("mlx:load", Path(path)))
        return model

    stt.load = load
    mlx_audio.stt = stt
    monkeypatch.setitem(sys.modules, "mlx", mlx)
    monkeypatch.setitem(sys.modules, "mlx.core", core)
    monkeypatch.setitem(sys.modules, "mlx_audio", mlx_audio)
    monkeypatch.setitem(sys.modules, "mlx_audio.stt", stt)


class _SherpaModel:
    def __init__(self, name, events):
        self.name = name
        self.events = events

    def close(self):
        self.events.append(f"{self.name}:close")


def _install_fake_sherpa(monkeypatch, events):
    sherpa = ModuleType("sherpa_onnx")

    def config(name):
        def build(**kwargs):
            events.append((name, kwargs))
            return SimpleNamespace(validate=lambda: True)

        return build

    sherpa.OfflineSpeakerSegmentationPyannoteModelConfig = config("segmentation-model")
    sherpa.OfflineSpeakerSegmentationModelConfig = config("segmentation")
    sherpa.SpeakerEmbeddingExtractorConfig = config("embedding-config")
    sherpa.FastClusteringConfig = config("clustering")
    sherpa.OfflineSpeakerDiarizationConfig = config("diarization-config")
    sherpa.OfflineSpeakerDiarization = lambda _config: _SherpaModel("diarization", events)
    sherpa.SpeakerEmbeddingExtractor = lambda _config: _SherpaModel("embedding", events)
    monkeypatch.setitem(sys.modules, "sherpa_onnx", sherpa)


def test_real_backends_load_and_unload_mocked_runtime(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "darwin")
    models_dir = tmp_path / "models"
    qwen_dir = models_dir / "qwen3-asr-mlx"
    qwen_dir.mkdir(parents=True)
    (qwen_dir / "config.json").write_text("{}", encoding="utf-8")
    sherpa_dir = models_dir / "sherpa-onnx"
    sherpa_dir.mkdir()
    (sherpa_dir / "segmentation.onnx").touch()
    (sherpa_dir / "embedding.onnx").touch()
    events = []
    _install_fake_mlx(monkeypatch, events)
    _install_fake_sherpa(monkeypatch, events)

    backends = [
        Qwen3AsrMlxBackend(models_dir),
        SherpaOnnxDiarizationBackend(models_dir),
        SherpaOnnxEmbeddingBackend(models_dir),
    ]
    for backend in backends:
        assert isinstance(backend, LoadableModel)
        backend.load()
        assert backend.loaded
        backend.unload()
        assert not backend.loaded

    assert ("mlx:load", qwen_dir) in events
    assert "mlx:clear_cache" in events
    assert "diarization:close" in events
    assert "embedding:close" in events


@pytest.mark.parametrize(
    "backend_type",
    [Qwen3AsrMlxBackend, SherpaOnnxDiarizationBackend, SherpaOnnxEmbeddingBackend],
)
def test_missing_model_files_give_actionable_path(monkeypatch, tmp_path, backend_type):
    monkeypatch.setattr(sys, "platform", "darwin")

    with pytest.raises(FileNotFoundError, match=r"把模型放到 data/models/"):
        backend_type(tmp_path / "data" / "models").load()


@pytest.mark.parametrize(
    ("factory", "name"),
    [
        (get_asr_backend, "unknown-asr"),
        (get_diarization_backend, "unknown-diarization"),
        (get_embedding_backend, "unknown-embedding"),
    ],
)
def test_unknown_backend_name_raises_value_error(factory, name):
    with pytest.raises(ValueError, match="未知"):
        factory(name, Path("data/models"))
