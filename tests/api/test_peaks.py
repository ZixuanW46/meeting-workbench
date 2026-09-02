"""波形峰值由后端算一次并缓存：确认页十几张卡不能各自把两小时音频解码一遍。"""

from __future__ import annotations

import io
import math
import struct
import wave
from pathlib import Path

from meeting_api.models import Meeting


def _sine_wav(seconds: float, rate: int = 16000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        frames = int(seconds * rate)
        # 前半段静音、后半段满幅正弦：峰值曲线应前低后高。
        samples = [
            0 if i < frames // 2 else int(32000 * math.sin(i / 10.0)) for i in range(frames)
        ]
        writer.writeframes(struct.pack(f"<{frames}h", *samples))
    return buffer.getvalue()


def _create_and_upload(client, payload: bytes, filename: str = "meeting.wav") -> str:
    meeting_id = client.post("/api/meetings", json={"title": "峰值测试"}).json()["id"]
    response = client.post(
        f"/api/meetings/{meeting_id}/upload",
        files={"file": (filename, payload, "audio/wav")},
    )
    assert response.status_code == 200
    return meeting_id


def _meeting_dir(client, meeting_id: str) -> Path:
    return client.app.state.settings.data_dir / "meetings" / meeting_id


def test_peaks_endpoint_returns_normalized_downsampled_peaks_and_duration(client):
    meeting_id = _create_and_upload(client, _sine_wav(4.0))

    response = client.get(f"/api/meetings/{meeting_id}/peaks")

    assert response.status_code == 200
    body = response.json()
    assert body.keys() == {"duration", "peaks"}
    assert abs(body["duration"] - 4.0) < 0.01
    peaks = body["peaks"]
    assert 100 <= len(peaks) <= 2000
    assert all(0.0 <= value <= 1.0 for value in peaks)
    half = len(peaks) // 2
    assert max(peaks[:half]) == 0.0
    assert max(peaks[half:]) > 0.9


def test_peaks_are_cached_on_disk_and_served_without_raw_audio(client):
    meeting_id = _create_and_upload(client, _sine_wav(2.0))
    first = client.get(f"/api/meetings/{meeting_id}/peaks").json()
    cache = _meeting_dir(client, meeting_id) / "peaks.json"
    assert cache.is_file()

    (_meeting_dir(client, meeting_id) / "raw" / "meeting.wav").unlink()

    second = client.get(f"/api/meetings/{meeting_id}/peaks")
    assert second.status_code == 200
    assert second.json() == first


def test_worker_precomputes_peaks_before_review(client):
    meeting_id = _create_and_upload(client, _sine_wav(2.0))

    assert client.app.state.worker.process_next() == meeting_id

    assert (_meeting_dir(client, meeting_id) / "peaks.json").is_file()
    assert client.get(f"/api/meetings/{meeting_id}").json()["state"] == "AWAITING_SPEAKER_REVIEW"


def test_peaks_unavailable_for_non_pcm_audio_and_missing_meeting(client):
    meeting_id = _create_and_upload(client, b"not really a wav", "meeting.wav")

    response = client.get(f"/api/meetings/{meeting_id}/peaks")

    assert response.status_code == 409
    assert "波形" in response.json()["detail"]
    assert client.get("/api/meetings/nope/peaks").status_code == 404
    # fake 后端不读音频：坏文件照样能走完转写，峰值失败不能拖垮会议。
    assert client.app.state.worker.process_next() == meeting_id
    with client.app.state.session_factory() as session:
        meeting = session.get(Meeting, meeting_id)
        assert meeting is not None
        assert meeting.state == "AWAITING_SPEAKER_REVIEW"
