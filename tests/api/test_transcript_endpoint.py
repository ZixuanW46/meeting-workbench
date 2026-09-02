from __future__ import annotations

from sqlalchemy import select

from meeting_api.models import (
    CleanedTranscriptBlock,
    Meeting,
    Person,
    SpeakerCluster,
    TranscriptSegment,
)
from meeting_api.transcript_cleaning import sha256_text
from meeting_domain import MeetingState


def _seed_meeting_with_transcript(client, *, state: str = MeetingState.READY.value) -> str:
    with client.app.state.session_factory() as session:
        meeting = Meeting(title="转写端点测试", state=state)
        person = Person(display_name="王芳")
        session.add_all([meeting, person])
        session.flush()
        session.add_all(
            [
                SpeakerCluster(
                    meeting_id=meeting.id,
                    cluster_id="S1",
                    total_seconds=20.0,
                    person_id=person.id,
                ),
                SpeakerCluster(
                    meeting_id=meeting.id,
                    cluster_id="S2",
                    total_seconds=10.0,
                ),
                TranscriptSegment(
                    meeting_id=meeting.id,
                    start_seconds=0.0,
                    end_seconds=5.0,
                    text="嗯第一段原文",
                    cluster_id="S1",
                ),
                TranscriptSegment(
                    meeting_id=meeting.id,
                    start_seconds=5.0,
                    end_seconds=9.0,
                    text="第二段原文",
                    cluster_id="S2",
                ),
            ]
        )
        session.commit()
        return meeting.id


def _add_cleaned_rows(client, meeting_id: str) -> None:
    with client.app.state.session_factory() as session:
        session.add_all(
            [
                CleanedTranscriptBlock(
                    meeting_id=meeting_id,
                    block_index=0,
                    raw_sha256=sha256_text("嗯第一段原文"),
                    cleaned_text="第一段清洗文本",
                ),
                CleanedTranscriptBlock(
                    meeting_id=meeting_id,
                    block_index=1,
                    raw_sha256=sha256_text("不匹配的旧原文"),
                    cleaned_text="第二段不应采用",
                ),
            ]
        )
        session.commit()


def test_transcript_endpoint_returns_raw_and_cleaned_versions(client):
    meeting_id = _seed_meeting_with_transcript(client)
    _add_cleaned_rows(client, meeting_id)

    response = client.get(f"/api/meetings/{meeting_id}/transcript")

    assert response.status_code == 200
    payload = response.json()
    assert payload["raw_markdown"].startswith("# 会议转写\n\n")
    assert "王芳 00:00-00:05\n嗯第一段原文" in payload["raw_markdown"]
    assert "说话人 2 00:05-00:09\n第二段原文" in payload["raw_markdown"]
    assert payload["cleaned_markdown"] is not None
    assert "王芳 00:00-00:05\n第一段清洗文本" in payload["cleaned_markdown"]
    assert "说话人 2 00:05-00:09\n第二段原文" in payload["cleaned_markdown"]
    assert "第二段不应采用" not in payload["cleaned_markdown"]


def test_transcript_endpoint_returns_structured_blocks(client):
    # 前端不该正则反解渲染好的 markdown；块级 JSON 才是接口契约。
    meeting_id = _seed_meeting_with_transcript(client)
    _add_cleaned_rows(client, meeting_id)

    payload = client.get(f"/api/meetings/{meeting_id}/transcript").json()

    assert payload["blocks"] == [
        {
            "start_seconds": 0.0,
            "end_seconds": 5.0,
            "label": "王芳",
            "text": "嗯第一段原文",
            "cleaned_text": "第一段清洗文本",
        },
        {
            "start_seconds": 5.0,
            "end_seconds": 9.0,
            "label": "说话人 2",
            "text": "第二段原文",
            "cleaned_text": None,
        },
    ]
    assert payload["cleaned_available"] is True

    bare = _seed_meeting_with_transcript(client)
    bare_payload = client.get(f"/api/meetings/{bare}/transcript").json()
    assert all(block["cleaned_text"] is None for block in bare_payload["blocks"])
    assert bare_payload["cleaned_available"] is False


def test_transcript_endpoint_uses_none_when_no_cleaned_rows_match(client):
    meeting_id = _seed_meeting_with_transcript(client)

    response = client.get(f"/api/meetings/{meeting_id}/transcript")

    assert response.status_code == 200
    payload = response.json()
    assert "嗯第一段原文" in payload["raw_markdown"]
    assert payload["cleaned_markdown"] is None


def test_transcript_export_variant_raw_and_cleaned(client):
    meeting_id = _seed_meeting_with_transcript(client)
    _add_cleaned_rows(client, meeting_id)

    raw = client.get(f"/api/meetings/{meeting_id}/export/transcript.md?variant=raw")
    cleaned = client.get(
        f"/api/meetings/{meeting_id}/export/transcript.md?variant=cleaned"
    )
    invalid = client.get(
        f"/api/meetings/{meeting_id}/export/transcript.md?variant=unknown"
    )

    assert raw.status_code == 200
    assert cleaned.status_code == 200
    assert invalid.status_code == 422
    assert "嗯第一段原文" in raw.text
    assert "第一段清洗文本" not in raw.text
    assert "第一段清洗文本" in cleaned.text
    assert "第二段原文" in cleaned.text


def test_transcript_endpoint_and_export_reject_unexportable_state(client):
    meeting_id = _seed_meeting_with_transcript(client, state=MeetingState.DRAFT.value)

    endpoint = client.get(f"/api/meetings/{meeting_id}/transcript")
    export = client.get(f"/api/meetings/{meeting_id}/export/transcript.md")

    assert endpoint.status_code == 409
    assert export.status_code == 409


def test_retranscribe_removes_cleaned_transcript_rows_and_file(client):
    meeting_id = _seed_meeting_with_transcript(
        client,
        state=MeetingState.PARTIAL_READY.value,
    )
    _add_cleaned_rows(client, meeting_id)
    target_dir = client.app.state.settings.data_dir / "meetings" / meeting_id
    target_dir.mkdir(parents=True)
    (target_dir / "transcript.cleaned.txt").write_text("旧清洗稿", encoding="utf-8")
    # 重转写要求音频文件仍在盘上。
    (target_dir / "raw").mkdir()
    (target_dir / "raw" / "meeting.wav").write_bytes(b"fake audio bytes")
    with client.app.state.session_factory() as session:
        meeting = session.get(Meeting, meeting_id)
        assert meeting is not None
        meeting.audio_filename = "meeting.wav"
        meeting.audio_size = 16
        meeting.audio_sha256 = "0" * 64
        session.commit()

    response = client.post(f"/api/meetings/{meeting_id}/retranscribe")

    assert response.status_code == 200
    assert response.json()["state"] == "QUEUED"
    assert not (target_dir / "transcript.cleaned.txt").exists()
    with client.app.state.session_factory() as session:
        rows = session.scalars(
            select(CleanedTranscriptBlock).where(
                CleanedTranscriptBlock.meeting_id == meeting_id
            )
        ).all()
    assert rows == []
