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
