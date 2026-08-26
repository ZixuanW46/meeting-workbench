import threading
from pathlib import Path

import pytest

from meeting_api.pipeline.asr import FakeAsrBackend, get_asr_backend
from meeting_api.pipeline.diarization import FakeDiarizationBackend, get_diarization_backend
from meeting_api.pipeline.serial import ModelSlotBusy, SingleModelSlot

AUDIO = Path("/tmp/fake-meeting.wav")


def test_fake_asr_transcribes_with_hotwords():
    asr = FakeAsrBackend()
    asr.load()
    segments = asr.transcribe(AUDIO, hotwords=["声纹", "Qwen"])
    assert segments
    assert "声纹" in segments[0].text
    asr.unload()
    assert not asr.loaded


def test_asr_requires_load():
    with pytest.raises(RuntimeError):
        FakeAsrBackend().transcribe(AUDIO)


def test_fake_diarization_uses_expected_speakers_as_prior():
    diar = FakeDiarizationBackend()
    diar.load()
    clusters = {s.cluster_id for s in diar.diarize(AUDIO, expected_speakers=2)}
    assert clusters == {"S1", "S2"}


def test_real_backends_not_wired_yet():
    with pytest.raises(NotImplementedError):
        get_asr_backend("qwen3-asr-mlx")
    with pytest.raises(NotImplementedError):
        get_diarization_backend("sherpa-onnx")


def test_single_model_slot_blocks_other_thread_until_released():
    # M10 起 HTTP 线程也会占槽（提交决定时入库声纹）；
    # worker 正在转写时必须排队等待，而不是 500，也不允许两个模型同时驻留。
    slot = SingleModelSlot()
    asr = FakeAsrBackend()
    diar = FakeDiarizationBackend()
    asr_holding = threading.Event()
    release_asr = threading.Event()
    events: list[str] = []

    def worker_thread() -> None:
        with slot.use(asr):
            events.append("asr:enter")
            asr_holding.set()
            assert release_asr.wait(timeout=5)
            events.append("asr:exit")

    def http_thread() -> None:
        assert asr_holding.wait(timeout=5)
        with slot.use(diar):
            assert not asr.loaded
            events.append("diar:enter")

    first = threading.Thread(target=worker_thread)
    second = threading.Thread(target=http_thread)
    first.start()
    second.start()
    asr_holding.wait(timeout=5)
    release_asr.set()
    first.join(timeout=5)
    second.join(timeout=5)

    assert events == ["asr:enter", "asr:exit", "diar:enter"]
    assert not asr.loaded
    assert not diar.loaded


def test_single_model_slot_enforces_serial_loading():
    slot = SingleModelSlot()
    asr = FakeAsrBackend()
    diar = FakeDiarizationBackend()

    with slot.use(asr):
        assert asr.loaded
        # 16GB 硬约束：ASR 驻留期间不允许再加载切分模型
        with pytest.raises(ModelSlotBusy):
            with slot.use(diar):
                pass

    # 离开后 ASR 已卸载，槽空出来给 diarization
    assert not asr.loaded
    with slot.use(diar):
        assert diar.loaded
    assert not diar.loaded
