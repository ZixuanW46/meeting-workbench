from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from meeting_api import worker as worker_module
from meeting_api.minutes.adapter import MinutesCliError
from meeting_api.models import CleanedTranscriptBlock
from meeting_api.worker import Worker


def _prepare_generating_minutes(client) -> str:
    created = client.post(
        "/api/meetings",
        json={"title": "清洗测试会议", "expected_speakers": 2},
    )
    assert created.status_code == 201
    meeting_id = created.json()["id"]

    uploaded = client.post(
        f"/api/meetings/{meeting_id}/upload",
        files={"file": ("meeting.wav", b"fake audio bytes", "audio/wav")},
    )
    assert uploaded.status_code == 200
    assert client.app.state.worker.process_next() == meeting_id
    assert client.get(f"/api/meetings/{meeting_id}").json()["state"] == (
        "AWAITING_SPEAKER_REVIEW"
    )

    reviewed = client.post(
        f"/api/meetings/{meeting_id}/review/decisions",
        json={
            "decisions": [
                {
                    "cluster_id": "S1",
                    "kind": "NEW_PERSON",
                    "display_name": "王芳",
                },
                {
                    "cluster_id": "S2",
                    "kind": "NEW_PERSON",
                    "display_name": "李雷",
                },
            ]
        },
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["state"] == "GENERATING_MINUTES"
    return meeting_id


def _replace_worker(client, **overrides) -> Worker:
    options = {
        "session_factory": client.app.state.session_factory,
        "settings": client.app.state.settings,
        "event_store": client.app.state.events,
    }
    options.update(overrides)
    worker = Worker(**options)
    client.app.state.worker = worker
    return worker


class StaticCleaner:
    def __init__(self, output: str) -> None:
        self.output = output
        self.prompts: list[str] = []

    def generate(self, transcript: str) -> str:
        self.prompts.append(transcript)
        return self.output


class FailingCleaner:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.prompts: list[str] = []

    def generate(self, transcript: str) -> str:
        self.prompts.append(transcript)
        raise self.error


class RecordingMinutes:
    def __init__(self, markdown: str = "# 清洗纪要\n\n- 已生成") -> None:
        self.markdown = markdown
        self.prompts: list[str] = []

    def generate(self, transcript: str) -> str:
        self.prompts.append(transcript)
        return self.markdown


class FailingMinutes:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate(self, transcript: str) -> str:
        self.prompts.append(transcript)
        raise MinutesCliError("模拟纪要失败")


class MustNotCallCleaner:
    def generate(self, transcript: str) -> str:
        del transcript
        raise AssertionError("关闭清洗后不应调用 cleaner")


def _cleaned_rows(client, meeting_id: str) -> list[CleanedTranscriptBlock]:
    with client.app.state.session_factory() as session:
        return list(
            session.scalars(
                select(CleanedTranscriptBlock)
                .where(CleanedTranscriptBlock.meeting_id == meeting_id)
                .order_by(CleanedTranscriptBlock.block_index)
            )
        )


def test_worker_persists_cleaned_transcript_and_minutes_use_cleaned_text(client):
    meeting_id = _prepare_generating_minutes(client)
    cleaner = StaticCleaner('{"0": "这是清洗后的第一段", "1": "这是清洗后的第二段"}')
    minutes = RecordingMinutes()
    _replace_worker(client, cleaner_adapter=cleaner, minutes_adapter=minutes)

    assert client.app.state.worker.process_next() == meeting_id

    assert client.get(f"/api/meetings/{meeting_id}").json()["state"] == "READY"
    rows = _cleaned_rows(client, meeting_id)
    assert [row.block_index for row in rows] == [0, 1]
    assert [row.cleaned_text for row in rows] == [
        "这是清洗后的第一段",
        "这是清洗后的第二段",
    ]

    target_dir = Path(client.app.state.settings.data_dir) / "meetings" / meeting_id
    raw_text = (target_dir / "transcript.txt").read_text(encoding="utf-8")
    cleaned_text = (target_dir / "transcript.cleaned.txt").read_text(encoding="utf-8")
    assert "这是 meeting.wav 的假转写第一段" in raw_text
    assert "这是清洗后的第一段" not in raw_text
    assert "这是清洗后的第一段" in cleaned_text

    (prompt,) = minutes.prompts
    assert "这是清洗后的第一段" in prompt
    assert "这是 meeting.wav 的假转写第一段" not in prompt
    assert "会议逐字稿：" in prompt


def test_worker_falls_back_to_raw_when_cleaner_returns_garbage_or_cli_error(client):
    meeting_id = _prepare_generating_minutes(client)
    cleaner = StaticCleaner("不是 JSON")
    minutes = RecordingMinutes()
    _replace_worker(client, cleaner_adapter=cleaner, minutes_adapter=minutes)

    assert client.app.state.worker.process_next() == meeting_id

    assert client.get(f"/api/meetings/{meeting_id}").json()["state"] == "READY"
    assert _cleaned_rows(client, meeting_id) == []
    (prompt,) = minutes.prompts
    assert "这是 meeting.wav 的假转写第一段" in prompt

    other_id = _prepare_generating_minutes(client)
    failing_cleaner = FailingCleaner(MinutesCliError("模拟清洗失败"))
    other_minutes = RecordingMinutes()
    _replace_worker(client, cleaner_adapter=failing_cleaner, minutes_adapter=other_minutes)

    assert client.app.state.worker.process_next() == other_id

    assert client.get(f"/api/meetings/{other_id}").json()["state"] == "READY"
    assert _cleaned_rows(client, other_id) == []
    assert "这是 meeting.wav 的假转写第一段" in other_minutes.prompts[0]


def test_worker_skips_cleaning_when_setting_disabled(client):
    meeting_id = _prepare_generating_minutes(client)
    client.app.state.settings.transcript_cleaning_enabled = False
    minutes = RecordingMinutes()
    _replace_worker(
        client,
        cleaner_adapter=MustNotCallCleaner(),
        minutes_adapter=minutes,
    )

    assert client.app.state.worker.process_next() == meeting_id

    assert client.get(f"/api/meetings/{meeting_id}").json()["state"] == "READY"
    assert _cleaned_rows(client, meeting_id) == []
    assert "这是 meeting.wav 的假转写第一段" in minutes.prompts[0]


def test_cleaned_rows_survive_when_minutes_generation_fails(client):
    meeting_id = _prepare_generating_minutes(client)
    cleaner = StaticCleaner('{"0": "这是清洗后的第一段"}')
    minutes = FailingMinutes()
    _replace_worker(client, cleaner_adapter=cleaner, minutes_adapter=minutes)

    assert client.app.state.worker.process_next() == meeting_id

    assert client.get(f"/api/meetings/{meeting_id}").json()["state"] == "PARTIAL_READY"
    rows = _cleaned_rows(client, meeting_id)
    assert [row.block_index for row in rows] == [0]
    assert rows[0].cleaned_text == "这是清洗后的第一段"
    assert "这是清洗后的第一段" in minutes.prompts[0]


def test_retry_reuses_cleaned_blocks_by_hash_without_calling_cleaner_again(client):
    # 两小时会议清洗十几批、每批一次 CLI 冷启动；纪要重试或重开确认时
    # 原文没变，必须按 raw_sha256 复用，不能整场重清。
    meeting_id = _prepare_generating_minutes(client)
    cleaner = StaticCleaner('{"0": "这是清洗后的第一段", "1": "这是清洗后的第二段"}')
    _replace_worker(client, cleaner_adapter=cleaner, minutes_adapter=FailingMinutes())
    assert client.app.state.worker.process_next() == meeting_id
    assert client.get(f"/api/meetings/{meeting_id}").json()["state"] == "PARTIAL_READY"
    assert len(cleaner.prompts) == 1

    retried = client.post(f"/api/meetings/{meeting_id}/minutes/retry")
    assert retried.status_code == 200
    minutes = RecordingMinutes()
    _replace_worker(client, cleaner_adapter=MustNotCallCleaner(), minutes_adapter=minutes)

    assert client.app.state.worker.process_next() == meeting_id

    assert client.get(f"/api/meetings/{meeting_id}").json()["state"] == "READY"
    rows = _cleaned_rows(client, meeting_id)
    assert [row.cleaned_text for row in rows] == [
        "这是清洗后的第一段",
        "这是清洗后的第二段",
    ]
    assert "这是清洗后的第一段" in minutes.prompts[0]


def test_reopened_review_only_cleans_blocks_whose_text_changed(client):
    # 重开确认后只改了标签：块索引可能整体位移，但原文哈希不变的块照样命中缓存。
    meeting_id = _prepare_generating_minutes(client)
    cleaner = StaticCleaner('{"0": "这是清洗后的第一段", "1": "这是清洗后的第二段"}')
    _replace_worker(client, cleaner_adapter=cleaner, minutes_adapter=RecordingMinutes())
    assert client.app.state.worker.process_next() == meeting_id
    assert client.get(f"/api/meetings/{meeting_id}").json()["state"] == "READY"

    assert client.post(f"/api/meetings/{meeting_id}/review/reopen").status_code == 200
    reviewed = client.post(
        f"/api/meetings/{meeting_id}/review/decisions",
        json={
            "decisions": [
                {"cluster_id": "S1", "kind": "CONFIRM"},
                {"cluster_id": "S2", "kind": "KEEP_UNKNOWN"},
            ]
        },
    )
    assert reviewed.status_code == 200
    minutes = RecordingMinutes()
    _replace_worker(client, cleaner_adapter=MustNotCallCleaner(), minutes_adapter=minutes)

    assert client.app.state.worker.process_next() == meeting_id

    assert client.get(f"/api/meetings/{meeting_id}").json()["state"] == "READY"
    assert "这是清洗后的第一段" in minutes.prompts[0]
    assert "这是清洗后的第二段" in minutes.prompts[0]


def test_cleaning_publishes_batch_progress_detail(client, monkeypatch):
    # 长会议清洗十几批要跑好几分钟，进度事件得说清到第几批，否则像挂了。
    meeting_id = _prepare_generating_minutes(client)
    monkeypatch.setattr(
        worker_module,
        "chunk_indexed_blocks",
        lambda blocks: [[(index, block)] for index, block in enumerate(blocks)],
    )
    cleaner = StaticCleaner('{"0": "清洗一", "1": "清洗二"}')
    details: list[str | None] = []

    class SpyCleaner:
        def generate(self, transcript: str) -> str:
            details.append(client.get(f"/api/meetings/{meeting_id}/progress").json()["detail"])
            return cleaner.generate(transcript)

    _replace_worker(client, cleaner_adapter=SpyCleaner(), minutes_adapter=RecordingMinutes())

    assert client.app.state.worker.process_next() == meeting_id

    assert details == ["1/2", "2/2"]
    final = client.get(f"/api/meetings/{meeting_id}/progress").json()
    assert final["state"] == "READY"
    assert final["detail"] is None
