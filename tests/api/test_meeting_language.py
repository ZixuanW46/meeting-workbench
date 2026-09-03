from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from meeting_api.minutes.prompt import build_minutes_prompt
from meeting_api.models import Meeting, TranscriptSegment
from meeting_api.transcript_cleaning import (
    CLEANING_INSTRUCTIONS,
    CLEANING_INSTRUCTIONS_EN,
    build_cleaning_prompt,
)
from meeting_api.transcript_format import TranscriptBlock
from meeting_api.worker import Worker

ENGLISH_NOTE = (
    "逐字稿为英文会议记录。纪要仍然用中文撰写；"
    "人名、公司名、产品名、专业术语保留英文原文，不要音译；"
    "直接引用的关键表态可保留英文原句。"
)


def _block(text: str, label: str = "Wang Fang") -> TranscriptBlock:
    return TranscriptBlock(start_seconds=0.0, end_seconds=1.0, label=label, text=text)


def _queue_meeting(client, language: str | None = None) -> str:
    payload: dict[str, object] = {"title": "语言测试会议", "expected_speakers": 2}
    if language is not None:
        payload["language"] = language
    created = client.post("/api/meetings", json=payload)
    assert created.status_code == 201
    meeting_id = created.json()["id"]
    uploaded = client.post(
        f"/api/meetings/{meeting_id}/upload",
        files={"file": ("meeting.wav", b"fake audio bytes", "audio/wav")},
    )
    assert uploaded.status_code == 200
    return meeting_id


def _transcript_text(client, meeting_id: str) -> str:
    with client.app.state.session_factory() as session:
        segments = session.scalars(
            select(TranscriptSegment)
            .where(TranscriptSegment.meeting_id == meeting_id)
            .order_by(TranscriptSegment.start_seconds)
        ).all()
        return "\n".join(segment.text for segment in segments)


def test_create_meeting_defaults_to_chinese(client):
    response = client.post("/api/meetings", json={"title": "默认语言会议"})

    assert response.status_code == 201
    assert response.json()["language"] == "zh"
    with client.app.state.session_factory() as session:
        meeting = session.get(Meeting, response.json()["id"])
        assert meeting is not None
        assert meeting.language == "zh"


def test_create_meeting_with_english_language_is_echoed_in_detail_and_list(client):
    response = client.post(
        "/api/meetings", json={"title": "English sync", "language": "en"}
    )

    assert response.status_code == 201
    meeting_id = response.json()["id"]
    assert response.json()["language"] == "en"
    assert client.get(f"/api/meetings/{meeting_id}").json()["language"] == "en"
    listed = client.get("/api/meetings").json()["items"]
    assert [item["language"] for item in listed if item["id"] == meeting_id] == ["en"]


def test_create_meeting_rejects_unknown_language(client):
    response = client.post("/api/meetings", json={"title": "火星语会议", "language": "xx"})

    assert response.status_code == 422


def test_patch_language_alone_takes_effect_without_touching_state_or_title(client):
    created = client.post("/api/meetings", json={"title": "复盘会"})
    meeting_id = created.json()["id"]

    patched = client.patch(f"/api/meetings/{meeting_id}", json={"language": "en"})

    assert patched.status_code == 200
    assert patched.json()["language"] == "en"
    assert patched.json()["title"] == "复盘会"
    assert patched.json()["state"] == created.json()["state"] == "DRAFT"

    assert client.patch(f"/api/meetings/{meeting_id}", json={}).status_code == 422
    assert (
        client.patch(f"/api/meetings/{meeting_id}", json={"language": "xx"}).status_code
        == 422
    )
    # 非法 PATCH 不应改动已保存的语言。
    assert client.get(f"/api/meetings/{meeting_id}").json()["language"] == "en"


def test_worker_passes_meeting_language_to_asr(client):
    english_id = _queue_meeting(client, language="en")
    chinese_id = _queue_meeting(client)
    worker = Worker(
        session_factory=client.app.state.session_factory,
        settings=client.app.state.settings,
    )

    assert worker.process_next() == english_id
    assert worker.process_next() == chinese_id

    assert "（语言: en）" in _transcript_text(client, english_id)
    assert "（语言: en）" not in _transcript_text(client, chinese_id)


def test_build_cleaning_prompt_switches_to_english_rules(client):
    chunk = [(0, _block("um we shipped the beta"))]

    english = build_cleaning_prompt(chunk, glossary=None, language="en")
    chinese = build_cleaning_prompt(chunk, glossary=None)

    assert CLEANING_INSTRUCTIONS_EN in english
    assert CLEANING_INSTRUCTIONS not in english
    assert "no translation" in english.lower()
    assert '{"i": 0, "speaker": "Wang Fang", "text": "um we shipped the beta"}' in english
    assert CLEANING_INSTRUCTIONS in chinese
    assert CLEANING_INSTRUCTIONS_EN not in chinese


def test_build_minutes_prompt_adds_chinese_note_for_english_meetings():
    transcript = "Wang Fang 00:00-00:05\nwe shipped the beta"

    english = build_minutes_prompt(transcript, language="en")
    chinese = build_minutes_prompt(transcript)

    assert ENGLISH_NOTE in english
    assert ENGLISH_NOTE not in chinese


def test_build_minutes_prompt_english_note_applies_to_custom_template():
    prompt = build_minutes_prompt(
        "Wang Fang 00:00-00:05\nwe shipped the beta",
        template="自定义纪要指令头",
        language="en",
    )

    assert "自定义纪要指令头" in prompt
    assert ENGLISH_NOTE in prompt
    assert prompt.index("自定义纪要指令头") < prompt.index(ENGLISH_NOTE)
    assert prompt.index(ENGLISH_NOTE) < prompt.index("\n会议逐字稿：\n")


def test_fake_asr_marks_language_only_for_english():
    from meeting_api.pipeline.asr import FakeAsrBackend

    backend = FakeAsrBackend()
    backend.load()

    english = backend.transcribe(Path("meeting.wav"), language="en")
    chinese = backend.transcribe(Path("meeting.wav"))

    assert "（语言: en）" in english[0].text
    assert "（语言: en）" not in "".join(segment.text for segment in chinese)
