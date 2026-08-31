from __future__ import annotations

from io import BytesIO

import pytest

from meeting_api.minutes.adapter import FakeMinutesAdapter, MinutesCliError


def _prepare_speaker_review(client, *, title: str = "导出测试会议") -> str:
    created = client.post(
        "/api/meetings",
        json={"title": title, "expected_speakers": 2},
    )
    assert created.status_code == 201
    meeting_id = created.json()["id"]

    uploaded = client.post(
        f"/api/meetings/{meeting_id}/upload",
        files={"file": ("meeting.wav", b"fake audio bytes", "audio/wav")},
    )
    assert uploaded.status_code == 200
    assert client.app.state.worker.process_next() == meeting_id
    state = client.get(f"/api/meetings/{meeting_id}").json()["state"]
    assert state == "AWAITING_SPEAKER_REVIEW"
    return meeting_id


def _submit_speaker_decisions(client, meeting_id: str) -> None:
    response = client.post(
        f"/api/meetings/{meeting_id}/review/decisions",
        json={
            "decisions": [
                {
                    "cluster_id": "S1",
                    "kind": "NEW_PERSON",
                    "display_name": "已知用户 1",
                },
                {"cluster_id": "S2", "kind": "KEEP_UNKNOWN"},
            ]
        },
    )
    assert response.status_code == 200
    assert response.json()["state"] == "GENERATING_MINUTES"


def _prepare_ready(client) -> str:
    meeting_id = _prepare_speaker_review(client)
    _submit_speaker_decisions(client, meeting_id)
    assert client.app.state.worker.process_next() == meeting_id
    assert client.get(f"/api/meetings/{meeting_id}").json()["state"] == "READY"
    return meeting_id


def _prepare_partial_ready(client) -> str:
    meeting_id = _prepare_speaker_review(client)
    _submit_speaker_decisions(client, meeting_id)
    client.app.state.worker.minutes_adapter = FakeMinutesAdapter(
        error=MinutesCliError("模拟纪要配额不足")
    )
    assert client.app.state.worker.process_next() == meeting_id
    state = client.get(f"/api/meetings/{meeting_id}").json()["state"]
    assert state == "PARTIAL_READY"
    return meeting_id


def _assert_attachment(response, suffix: str) -> None:
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert 'filename="meeting-' in disposition
    assert disposition.endswith(f'{suffix}"')


def test_transcript_export_is_time_ordered_and_uses_final_speaker_labels(client):
    meeting_id = _prepare_ready(client)

    response = client.get(f"/api/meetings/{meeting_id}/export/transcript.md")

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/markdown; charset=utf-8"
    _assert_attachment(response, "-transcript.md")
    assert response.text.index("假转写第一段") < response.text.index("假转写第二段")
    assert "已知用户 1" in response.text
    assert "说话人S2（未确认）" in response.text
    assert "未知说话人" not in response.text
    assert "[0.00" not in response.text
    assert "已知用户 1 00:00-00:05\n这是 meeting.wav 的假转写第一段" in response.text
    assert "说话人S2（未确认） 00:05-00:10\n这是假转写第二段" in response.text
    assert str(client.app.state.settings.data_dir) not in response.text
    assert str(client.app.state.settings.data_dir) not in str(response.headers)


def test_transcript_can_be_exported_while_awaiting_speaker_review(client):
    meeting_id = _prepare_speaker_review(client)

    response = client.get(f"/api/meetings/{meeting_id}/export/transcript.md")

    assert response.status_code == 200
    assert "说话人S1（未确认）" in response.text
    assert "说话人S2（未确认）" in response.text


def test_partial_ready_can_still_export_transcript(client):
    meeting_id = _prepare_partial_ready(client)

    response = client.get(f"/api/meetings/{meeting_id}/export/transcript.md")

    assert response.status_code == 200
    assert "假转写第一段" in response.text
    assert "说话人S2（未确认）" in response.text


def test_ready_minutes_markdown_export_matches_minutes_endpoint(client):
    meeting_id = _prepare_ready(client)
    minutes = client.get(f"/api/meetings/{meeting_id}/minutes")

    response = client.get(f"/api/meetings/{meeting_id}/export/minutes.md")

    assert minutes.status_code == 200
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/markdown; charset=utf-8"
    _assert_attachment(response, "-minutes.md")
    assert response.text == minutes.json()["markdown"]
    assert response.text.startswith("含未确认说话人")
    assert str(client.app.state.settings.data_dir) not in response.text
    assert str(client.app.state.settings.data_dir) not in str(response.headers)


def test_ready_minutes_docx_export_contains_minutes_body(client):
    meeting_id = _prepare_ready(client)
    markdown = client.get(f"/api/meetings/{meeting_id}/minutes").json()["markdown"]

    response = client.get(f"/api/meetings/{meeting_id}/export/minutes.docx")

    assert response.status_code == 200
    from docx import Document

    assert response.headers["content-type"] == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    _assert_attachment(response, "-minutes.docx")
    document = Document(BytesIO(response.content))
    assert "\n".join(paragraph.text for paragraph in document.paragraphs) == markdown
    assert str(client.app.state.settings.data_dir) not in str(response.headers)


@pytest.mark.parametrize("suffix", ["minutes.md", "minutes.docx"])
def test_partial_ready_without_minutes_file_cannot_export_minutes(client, suffix):
    meeting_id = _prepare_partial_ready(client)

    response = client.get(f"/api/meetings/{meeting_id}/export/{suffix}")

    assert response.status_code == 409


@pytest.mark.parametrize("suffix", ["transcript.md", "minutes.md", "minutes.docx"])
def test_draft_meeting_cannot_export(client, suffix):
    created = client.post("/api/meetings", json={"title": "尚未上传的草稿"})
    meeting_id = created.json()["id"]

    response = client.get(f"/api/meetings/{meeting_id}/export/{suffix}")

    assert response.status_code == 409


@pytest.mark.parametrize("suffix", ["transcript.md", "minutes.md", "minutes.docx"])
def test_missing_meeting_export_returns_404(client, suffix):
    response = client.get(f"/api/meetings/not-found/export/{suffix}")

    assert response.status_code == 404
