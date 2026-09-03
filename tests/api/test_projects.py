"""项目（会议归属）与项目热词，以及全局 + 项目 + 本场三层热词快照。"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from meeting_api.models import Meeting, ProjectHotword
from meeting_api.pipeline.asr import AsrSegment, FakeAsrBackend


def _create_project(client, name: str) -> str:
    response = client.post("/api/projects", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _create_meeting(
    client,
    *,
    hotwords: list[str] | None = None,
    project_id: str | None = None,
) -> str:
    payload: dict = {"title": "项目测试会议", "hotwords": hotwords or []}
    if project_id is not None:
        payload["project_id"] = project_id
    response = client.post("/api/meetings", json=payload)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _queue_meeting(client, **kwargs) -> str:
    meeting_id = _create_meeting(client, **kwargs)
    uploaded = client.post(
        f"/api/meetings/{meeting_id}/upload",
        files={"file": ("meeting.wav", b"fake audio bytes", "audio/wav")},
    )
    assert uploaded.status_code == 200
    return meeting_id


class HotwordProbeAsr(FakeAsrBackend):
    """记录 worker 实际交给 ASR 的热词快照。"""

    def __init__(self) -> None:
        super().__init__()
        self.received_hotwords: tuple[str, ...] | None = None

    def transcribe(
        self,
        audio_path: Path,
        hotwords: Sequence[str] = (),
        language: str = "zh",
    ) -> list[AsrSegment]:
        self.received_hotwords = tuple(hotwords)
        return super().transcribe(audio_path, hotwords, language)


# --- 项目 CRUD ---------------------------------------------------------------


def test_project_crud_lists_sorted_with_counts(client):
    beta = _create_project(client, "Beta 项目")
    alpha_response = client.post("/api/projects", json={"name": "  Alpha 项目  "})
    assert alpha_response.status_code == 201
    alpha = alpha_response.json()
    assert alpha["name"] == "Alpha 项目"
    assert alpha["meeting_count"] == 0
    assert alpha["hotword_count"] == 0

    assert client.post(
        f"/api/projects/{beta}/hotwords", json={"word": "项目词"}
    ).status_code == 201
    _create_meeting(client, project_id=beta)

    listed = client.get("/api/projects")
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert [item["name"] for item in items] == ["Alpha 项目", "Beta 项目"]
    assert items[1]["meeting_count"] == 1
    assert items[1]["hotword_count"] == 1
    assert set(items[0]) == {
        "id",
        "name",
        "created_at",
        "meeting_count",
        "hotword_count",
    }


def test_project_name_blank_is_422_and_duplicate_is_409(client):
    assert client.post("/api/projects", json={"name": "   "}).status_code == 422
    _create_project(client, "重名项目")
    duplicate = client.post("/api/projects", json={"name": "重名项目"})
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "项目已存在"


def test_project_rename_and_404_and_duplicate(client):
    first = _create_project(client, "旧名字")
    _create_project(client, "占位项目")

    renamed = client.patch(f"/api/projects/{first}", json={"name": "  新名字  "})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "新名字"

    duplicate = client.patch(f"/api/projects/{first}", json={"name": "占位项目"})
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "项目已存在"

    missing = client.patch("/api/projects/not-found", json={"name": "随便"})
    assert missing.status_code == 404
    assert missing.json()["detail"] == "项目不存在"


def test_delete_project_clears_meeting_project_id_and_keeps_meeting(client):
    project_id = _create_project(client, "待删项目")
    assert client.post(
        f"/api/projects/{project_id}/hotwords", json={"word": "项目词"}
    ).status_code == 201
    meeting_id = _create_meeting(client, project_id=project_id)

    assert client.delete(f"/api/projects/{project_id}").status_code == 204
    assert client.delete(f"/api/projects/{project_id}").status_code == 404

    detail = client.get(f"/api/meetings/{meeting_id}")
    assert detail.status_code == 200
    assert detail.json()["project_id"] is None
    assert detail.json()["project_name"] is None

    with client.app.state.session_factory() as session:
        assert session.query(ProjectHotword).count() == 0


# --- 项目热词 ----------------------------------------------------------------


def test_project_hotword_crud_is_sorted_validated_and_scoped(client):
    project_id = _create_project(client, "词库项目")
    other_id = _create_project(client, "另一个项目")

    created = client.post(
        f"/api/projects/{project_id}/hotwords",
        json={"word": "  术语乙  ", "note": "  乙的注解  "},
    )
    assert created.status_code == 201
    assert created.json()["word"] == "术语乙"
    assert created.json()["note"] == "乙的注解"
    first = client.post(f"/api/projects/{project_id}/hotwords", json={"word": "术语甲"})
    assert first.status_code == 201
    assert first.json()["note"] is None

    listed = client.get(f"/api/projects/{project_id}/hotwords")
    assert listed.status_code == 200
    assert [item["word"] for item in listed.json()["items"]] == ["术语乙", "术语甲"]
    assert set(listed.json()["items"][0]) == {"id", "word", "note"}

    # 同词在不同项目下互不冲突
    assert client.post(
        f"/api/projects/{other_id}/hotwords", json={"word": "术语甲"}
    ).status_code == 201
    duplicate = client.post(
        f"/api/projects/{project_id}/hotwords", json={"word": "术语甲"}
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "词语已存在"

    assert client.post(
        f"/api/projects/{project_id}/hotwords", json={"word": "   "}
    ).status_code == 422
    assert client.post(
        f"/api/projects/{project_id}/hotwords",
        json={"word": "超长注解", "note": "字" * 501},
    ).status_code == 422
    assert client.post(
        "/api/projects/not-found/hotwords", json={"word": "术语丙"}
    ).status_code == 404

    entry_id = first.json()["id"]
    updated = client.patch(
        f"/api/projects/{project_id}/hotwords/{entry_id}", json={"note": "  新注解  "}
    )
    assert updated.status_code == 200
    assert updated.json()["note"] == "新注解"
    cleared = client.patch(
        f"/api/projects/{project_id}/hotwords/{entry_id}", json={"note": "   "}
    )
    assert cleared.status_code == 200
    assert cleared.json()["note"] is None

    # 词条不属于该项目 → 404
    assert client.patch(
        f"/api/projects/{other_id}/hotwords/{entry_id}", json={"note": "越权"}
    ).status_code == 404
    assert client.delete(
        f"/api/projects/{other_id}/hotwords/{entry_id}"
    ).status_code == 404

    assert client.delete(
        f"/api/projects/{project_id}/hotwords/{entry_id}"
    ).status_code == 204
    assert [
        item["word"]
        for item in client.get(f"/api/projects/{project_id}/hotwords").json()["items"]
    ] == ["术语乙"]


# --- 会议挂项目 --------------------------------------------------------------


def test_create_meeting_with_project_returns_project_name(client):
    project_id = _create_project(client, "归属项目")
    created = client.post(
        "/api/meetings", json={"title": "带项目的会", "project_id": project_id}
    )
    assert created.status_code == 201
    assert created.json()["project_id"] == project_id
    assert created.json()["project_name"] == "归属项目"

    listed = client.get("/api/meetings").json()["items"]
    assert listed[0]["project_name"] == "归属项目"


def test_create_meeting_without_project_is_null(client):
    created = client.post("/api/meetings", json={"title": "无项目的会"})
    assert created.status_code == 201
    assert created.json()["project_id"] is None
    assert created.json()["project_name"] is None


def test_create_meeting_with_unknown_project_is_404(client):
    response = client.post(
        "/api/meetings", json={"title": "坏项目", "project_id": "not-found"}
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "项目不存在"


def test_patch_meeting_project_id_can_attach_move_and_detach(client):
    first = _create_project(client, "项目一")
    second = _create_project(client, "项目二")
    meeting_id = _create_meeting(client)

    attached = client.patch(
        f"/api/meetings/{meeting_id}", json={"project_id": first}
    )
    assert attached.status_code == 200
    assert attached.json()["project_id"] == first
    assert attached.json()["project_name"] == "项目一"

    moved = client.patch(f"/api/meetings/{meeting_id}", json={"project_id": second})
    assert moved.json()["project_name"] == "项目二"

    detached = client.patch(f"/api/meetings/{meeting_id}", json={"project_id": None})
    assert detached.status_code == 200
    assert detached.json()["project_id"] is None
    assert detached.json()["project_name"] is None


def test_patch_meeting_without_project_id_keeps_current_project(client):
    project_id = _create_project(client, "保持项目")
    meeting_id = _create_meeting(client, project_id=project_id)

    renamed = client.patch(f"/api/meetings/{meeting_id}", json={"title": "改个标题"})
    assert renamed.status_code == 200
    assert renamed.json()["project_id"] == project_id


def test_patch_meeting_with_unknown_project_is_404(client):
    meeting_id = _create_meeting(client)
    response = client.patch(
        f"/api/meetings/{meeting_id}", json={"project_id": "not-found"}
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "项目不存在"


def test_patch_meeting_project_id_alone_satisfies_at_least_one_field(client):
    meeting_id = _create_meeting(client)
    assert client.patch(f"/api/meetings/{meeting_id}", json={}).status_code == 422
    assert (
        client.patch(f"/api/meetings/{meeting_id}", json={"project_id": None}).status_code
        == 200
    )


def test_patch_meeting_project_in_ready_state_does_not_change_state(client):
    project_id = _create_project(client, "已完成项目")
    meeting_id = _queue_meeting(client)
    with client.app.state.session_factory() as session:
        session.get(Meeting, meeting_id).state = "READY"
        session.commit()

    response = client.patch(
        f"/api/meetings/{meeting_id}", json={"project_id": project_id}
    )
    assert response.status_code == 200
    assert response.json()["state"] == "READY"


# --- 三层热词快照 ------------------------------------------------------------


def test_worker_snapshot_merges_global_project_and_meeting_hotwords(client):
    assert client.post("/api/hotwords", json={"word": "全局词"}).status_code == 201
    project_id = _create_project(client, "热词项目")
    assert client.post(
        f"/api/projects/{project_id}/hotwords", json={"word": "项目词"}
    ).status_code == 201
    meeting_id = _queue_meeting(
        client, hotwords=["本场词"], project_id=project_id
    )
    probe = HotwordProbeAsr()
    client.app.state.worker.asr_backend = probe

    assert client.app.state.worker.process_next() == meeting_id

    expected = tuple(sorted({"全局词", "项目词", "本场词"}))
    with client.app.state.session_factory() as session:
        persisted = tuple(
            json.loads(session.get(Meeting, meeting_id).hotword_snapshot_json)
        )
    assert persisted == expected
    assert probe.received_hotwords == expected


def test_meeting_without_project_snapshot_has_no_project_words(client):
    assert client.post("/api/hotwords", json={"word": "全局词"}).status_code == 201
    project_id = _create_project(client, "别人的项目")
    assert client.post(
        f"/api/projects/{project_id}/hotwords", json={"word": "别人的项目词"}
    ).status_code == 201
    meeting_id = _queue_meeting(client, hotwords=["本场词"])

    assert client.app.state.worker.process_next() == meeting_id

    with client.app.state.session_factory() as session:
        persisted = json.loads(session.get(Meeting, meeting_id).hotword_snapshot_json)
    assert persisted == sorted(["全局词", "本场词"])


def test_reattaching_project_does_not_rewrite_frozen_snapshot(client):
    old_project = _create_project(client, "旧项目")
    new_project = _create_project(client, "新项目")
    assert client.post(
        f"/api/projects/{old_project}/hotwords", json={"word": "旧项目词"}
    ).status_code == 201
    assert client.post(
        f"/api/projects/{new_project}/hotwords", json={"word": "新项目词"}
    ).status_code == 201
    meeting_id = _queue_meeting(client, hotwords=["本场词"], project_id=old_project)
    assert client.app.state.worker.process_next() == meeting_id

    with client.app.state.session_factory() as session:
        frozen = session.get(Meeting, meeting_id).hotword_snapshot_json
    assert json.loads(frozen) == sorted(["旧项目词", "本场词"])

    assert client.patch(
        f"/api/meetings/{meeting_id}", json={"project_id": new_project}
    ).status_code == 200

    with client.app.state.session_factory() as session:
        assert session.get(Meeting, meeting_id).hotword_snapshot_json == frozen

    # 重转写才会用新项目的词重新冻结
    assert client.post(f"/api/meetings/{meeting_id}/retranscribe").status_code == 200
    with client.app.state.session_factory() as session:
        refrozen = json.loads(session.get(Meeting, meeting_id).hotword_snapshot_json)
    assert refrozen == sorted(["新项目词", "本场词"])


def test_minutes_glossary_includes_project_hotword_notes(client):
    project_id = _create_project(client, "术语项目")
    assert client.post(
        "/api/hotwords", json={"word": "全局词", "note": "全局注解"}
    ).status_code == 201
    assert client.post(
        f"/api/projects/{project_id}/hotwords",
        json={"word": "项目词", "note": "项目注解"},
    ).status_code == 201
    # 同词两层都有注解时以项目注解为准
    assert client.post(
        "/api/hotwords", json={"word": "共同词", "note": "全局的说法"}
    ).status_code == 201
    assert client.post(
        f"/api/projects/{project_id}/hotwords",
        json={"word": "共同词", "note": "项目的说法"},
    ).status_code == 201

    meeting_id = _queue_meeting(client, project_id=project_id)
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

    prompts: list[str] = []

    class RecordingAdapter:
        def generate(self, transcript: str) -> str:
            prompts.append(transcript)
            return "# 会议纪要\n\n- 已生成"

    client.app.state.worker.minutes_adapter = RecordingAdapter()
    assert client.app.state.worker.process_next() == meeting_id

    (prompt,) = prompts
    assert "- 项目词：项目注解" in prompt
    assert "- 全局词：全局注解" in prompt
    assert "- 共同词：项目的说法" in prompt
    assert "- 共同词：全局的说法" not in prompt
