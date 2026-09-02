"""会议日期：纪要日期锚点与标题模板必须用会议发生日，而不是记录创建时刻。"""

from __future__ import annotations

from datetime import UTC, datetime

from meeting_api.minutes import prompt as minutes_prompt
from meeting_api.models import Meeting


class RecordingAdapter:
    def __init__(self, markdown: str = "# 主题概括\n\n正文") -> None:
        self.markdown = markdown
        self.prompts: list[str] = []

    def generate(self, transcript: str) -> str:
        self.prompts.append(transcript)
        return self.markdown


def _today_local(client, meeting_id: str) -> str:
    with client.app.state.session_factory() as session:
        meeting = session.get(Meeting, meeting_id)
        assert meeting is not None
        return minutes_prompt.meeting_date_from_created_at(meeting.created_at).isoformat()


def _upload(client, meeting_id: str, filename: str) -> None:
    response = client.post(
        f"/api/meetings/{meeting_id}/upload",
        files={"file": (filename, b"fake audio bytes", "audio/wav")},
    )
    assert response.status_code == 200


def test_create_meeting_accepts_explicit_meeting_date(client):
    response = client.post(
        "/api/meetings", json={"title": "复盘会", "meeting_date": "2026-08-30"}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["meeting_date"] == "2026-08-30"
    assert body["meeting_date_source"] == "user"


def test_create_meeting_defaults_meeting_date_to_creation_day(client):
    response = client.post("/api/meetings", json={"title": "复盘会"})

    assert response.status_code == 201
    body = response.json()
    assert body["meeting_date"] == _today_local(client, body["id"])
    assert body["meeting_date_source"] == "created"


def test_upload_filename_date_becomes_meeting_date_when_user_did_not_set_one(client):
    meeting_id = client.post("/api/meetings", json={"title": "复盘会"}).json()["id"]

    _upload(client, meeting_id, "2026-08-31_merged.wav")

    body = client.get(f"/api/meetings/{meeting_id}").json()
    assert body["meeting_date"] == "2026-08-31"
    assert body["meeting_date_source"] == "filename"


def test_upload_filename_date_does_not_override_user_meeting_date(client):
    meeting_id = client.post(
        "/api/meetings", json={"title": "复盘会", "meeting_date": "2026-08-30"}
    ).json()["id"]

    _upload(client, meeting_id, "20260831-录音.m4a.wav")

    body = client.get(f"/api/meetings/{meeting_id}").json()
    assert body["meeting_date"] == "2026-08-30"
    assert body["meeting_date_source"] == "user"


def test_patch_meeting_date_and_reject_empty_patch(client):
    meeting_id = client.post("/api/meetings", json={"title": "复盘会"}).json()["id"]

    patched = client.patch(f"/api/meetings/{meeting_id}", json={"meeting_date": "2026-08-29"})
    assert patched.status_code == 200
    assert patched.json()["meeting_date"] == "2026-08-29"
    assert patched.json()["meeting_date_source"] == "user"
    # 只改日期不动标题，标题也不算被用户编辑。
    assert patched.json()["title"] == "复盘会"

    assert client.patch(f"/api/meetings/{meeting_id}", json={}).status_code == 422
    assert (
        client.patch(f"/api/meetings/{meeting_id}", json={"meeting_date": "昨天"}).status_code
        == 422
    )


def test_minutes_prompt_and_auto_title_use_meeting_date_not_created_at(client):
    meeting_id = client.post(
        "/api/meetings", json={"title": "复盘会", "meeting_date": "2026-08-30"}
    ).json()["id"]
    _upload(client, meeting_id, "meeting.wav")
    assert client.app.state.worker.process_next() == meeting_id
    reviewed = client.post(
        f"/api/meetings/{meeting_id}/review/decisions",
        json={
            "decisions": [
                {"cluster_id": "S1", "kind": "NEW_PERSON", "display_name": "王芳"},
                {"cluster_id": "S2", "kind": "KEEP_UNKNOWN"},
            ]
        },
    )
    assert reviewed.status_code == 200
    with client.app.state.session_factory() as session:
        meeting = session.get(Meeting, meeting_id)
        assert meeting is not None
        # 记录是另一天建的：锚点仍必须是会议日。
        meeting.created_at = datetime(2026, 9, 2, 3, 0, tzinfo=UTC)
        meeting.title_user_edited = False
        session.commit()
    adapter = RecordingAdapter("# 2026-08-30：Q3 复盘\n\n正文")
    client.app.state.worker.minutes_adapter = adapter

    assert client.app.state.worker.process_next() == meeting_id

    (prompt,) = adapter.prompts
    assert "会议日期：2026-08-30（周日）" in prompt
    assert client.get(f"/api/meetings/{meeting_id}").json()["title"] == "26-08-30：Q3 复盘"
