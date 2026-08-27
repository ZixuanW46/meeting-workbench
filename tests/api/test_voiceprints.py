from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from sqlalchemy import text

from meeting_api.pipeline.embedding import FakeEmbeddingBackend, embedding_to_bytes


def _prepare_review(client, *, title: str = "声纹测试") -> str:
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
    assert client.get(f"/api/meetings/{meeting_id}").json()["state"] == (
        "AWAITING_SPEAKER_REVIEW"
    )
    return meeting_id


def _submit_new_person_and_unknown(
    client,
    meeting_id: str,
    *,
    display_name: str = "王芳",
):
    response = client.post(
        f"/api/meetings/{meeting_id}/review/decisions",
        json={
            "decisions": [
                {
                    "cluster_id": "S1",
                    "kind": "NEW_PERSON",
                    "display_name": display_name,
                },
                {"cluster_id": "S2", "kind": "KEEP_UNKNOWN"},
            ]
        },
    )
    assert response.status_code == 200
    assert client.app.state.worker.process_next() == meeting_id
    return response


def _voiceprint_rows(client):
    with client.app.state.session_factory() as session:
        return session.execute(
            text(
                "SELECT v.id, v.person_id, v.embedding, p.display_name "
                "FROM voiceprints AS v JOIN persons AS p ON p.id = v.person_id "
                "ORDER BY p.display_name"
            )
        ).all()


def _walk(value: object):
    yield value
    if isinstance(value, Mapping):
        for key, child in value.items():
            yield key
            yield from _walk(child)
    elif isinstance(value, Sequence) and not isinstance(value, str | bytes):
        for child in value:
            yield from _walk(child)


def test_submitting_decisions_enrolls_qualified_clusters_with_correct_people(client):
    meeting_id = _prepare_review(client, title="两个合格声纹")

    response = client.post(
        f"/api/meetings/{meeting_id}/review/decisions",
        json={
            "decisions": [
                {"cluster_id": "S1", "kind": "NEW_PERSON", "display_name": "王芳"},
                {"cluster_id": "S2", "kind": "NEW_PERSON", "display_name": "李雷"},
            ]
        },
    )

    assert response.status_code == 200
    rows = _voiceprint_rows(client)
    assert [(row.person_id, row.display_name) for row in rows] == sorted(
        [(row.person_id, row.display_name) for row in rows], key=lambda item: item[1]
    )
    assert {row.display_name for row in rows} == {"王芳", "李雷"}
    assert all(row.person_id for row in rows)
    assert all(isinstance(row.embedding, bytes) and row.embedding for row in rows)


def test_keep_unknown_cluster_is_never_enrolled(client):
    meeting_id = _prepare_review(client, title="未知簇不入库")

    _submit_new_person_and_unknown(client, meeting_id)

    rows = _voiceprint_rows(client)
    assert len(rows) == 1
    assert rows[0].display_name == "王芳"


def test_confirmed_cluster_below_fake_quality_threshold_is_not_enrolled(client):
    meeting_id = _prepare_review(client, title="低质量不入库")
    with client.app.state.session_factory() as session:
        session.execute(
            text(
                "UPDATE speaker_clusters SET quality_score = 0.1 "
                "WHERE meeting_id = :meeting_id AND cluster_id = 'S1'"
            ),
            {"meeting_id": meeting_id},
        )
        session.commit()

    _submit_new_person_and_unknown(client, meeting_id)

    assert _voiceprint_rows(client) == []


def test_list_voiceprints_exposes_only_identity_metadata(client):
    meeting_id = _prepare_review(client, title="声纹列表")
    _submit_new_person_and_unknown(client, meeting_id)

    response = client.get("/api/voiceprints")

    assert response.status_code == 200
    body = response.json()
    # items 是模板；people 是全部参会人（与确认页同一份人员口径）。
    assert set(body) == {"items", "people"}
    assert [set(person) for person in body["people"]] == [{"id", "display_name"}]
    assert body["people"][0]["display_name"] == "王芳"
    items = body["items"]
    assert len(items) == 1
    assert set(items[0]) == {
        "id",
        "person_id",
        "display_name",
        "created_at",
        "source_meeting_title",
        "snippet_text",
        "has_clip",
    }
    assert items[0]["display_name"] == "王芳"

    flattened = list(_walk(body))
    forbidden_keys = {"embedding", "vector", "path", "file_path", "audio_path"}
    assert not ({value.lower() for value in flattened if isinstance(value, str)} & forbidden_keys)
    data_dir = str(client.app.state.settings.data_dir)
    assert not any(
        isinstance(value, str) and (data_dir in value or value.startswith("/workspace/"))
        for value in flattened
    )
    assert not any(isinstance(value, bytes) for value in flattened)


def test_delete_voiceprint_removes_it_and_future_worker_no_longer_suggests_person(client):
    enrolled_meeting_id = _prepare_review(client, title="先入库")
    _submit_new_person_and_unknown(client, enrolled_meeting_id)
    listed = client.get("/api/voiceprints")
    assert listed.status_code == 200
    voiceprint = listed.json()["items"][0]

    matched_meeting_id = _prepare_review(client, title="删除前应能匹配")
    cards_before = client.get(f"/api/meetings/{matched_meeting_id}/review").json()["cards"]
    s1_before = next(card for card in cards_before if card["cluster_id"] == "S1")
    assert s1_before["suggested_person_id"] == voiceprint["person_id"]

    deleted = client.delete(f"/api/voiceprints/{voiceprint['id']}")

    assert deleted.status_code == 204
    assert deleted.content == b""
    emptied = client.get("/api/voiceprints").json()
    assert emptied["items"] == []
    # 模板删光后人还在：确认页的建议/下拉仍会引用她，声纹库页必须
    # 同口径展示「有人、暂无模板」，不能显示成什么都没有。
    assert [person["display_name"] for person in emptied["people"]] == ["王芳"]

    unmatched_meeting_id = _prepare_review(client, title="删除后不再匹配")
    cards_after = client.get(f"/api/meetings/{unmatched_meeting_id}/review").json()["cards"]
    s1_after = next(card for card in cards_after if card["cluster_id"] == "S1")
    assert s1_after["suggested_person_id"] is None


def test_delete_missing_voiceprint_returns_404(client):
    response = client.delete("/api/voiceprints/does-not-exist")

    assert response.status_code == 404
    assert response.json()["detail"] == "声纹不存在"


def _s1_sample_windows(client, meeting_id: str) -> list[tuple[float, float]]:
    with client.app.state.session_factory() as session:
        clips_json = session.execute(
            text(
                "SELECT sample_clips_json FROM speaker_clusters "
                "WHERE meeting_id = :meeting_id AND cluster_id = 'S1'"
            ),
            {"meeting_id": meeting_id},
        ).scalar_one()
    return [
        (clip["start_seconds"], clip["end_seconds"]) for clip in json.loads(clips_json)
    ]


def test_enrolled_embedding_uses_the_clusters_sample_windows(client):
    # 入库口径必须与匹配口径一致：都对该簇的试听时间窗提取声纹。
    meeting_id = _prepare_review(client, title="入库口径")
    windows = _s1_sample_windows(client, meeting_id)
    assert windows  # 前置：确认包必然带试听片段

    _submit_new_person_and_unknown(client, meeting_id)

    backend = FakeEmbeddingBackend()
    backend.load()
    expected = embedding_to_bytes(backend.embed(Path("unused.wav"), windows))
    rows = _voiceprint_rows(client)
    assert len(rows) == 1
    assert rows[0].embedding == expected


def test_review_card_suggestion_carries_only_two_qualitative_tiers(client):
    enrolled_meeting_id = _prepare_review(client, title="先入库")
    _submit_new_person_and_unknown(client, enrolled_meeting_id)

    matched_meeting_id = _prepare_review(client, title="再匹配")
    cards = {
        card["cluster_id"]: card
        for card in client.get(f"/api/meetings/{matched_meeting_id}/review").json()[
            "cards"
        ]
    }

    # fake 口径下同簇窗口向量余弦≈1 → 「较高」；库里没人像 S2 → 无建议无档位。
    assert cards["S1"]["suggested_person_id"] is not None
    assert cards["S1"]["suggested_tier"] == "high"
    assert cards["S2"]["suggested_person_id"] is None
    assert cards["S2"]["suggested_tier"] is None


def test_list_carries_template_provenance_for_manual_audit(client):
    # 声纹库页人工核对需要：来源会议标题（不是路径）、该窗转写摘录、
    # 是否有试听切片、入库时间。
    meeting_id = _prepare_review(client, title="出处核对")
    _submit_new_person_and_unknown(client, meeting_id)

    items = client.get("/api/voiceprints").json()["items"]

    assert len(items) == 1
    assert items[0]["source_meeting_title"] == "出处核对"
    assert "假转写第一段" in items[0]["snippet_text"]
    assert items[0]["created_at"] is not None
    # fake 字节音频切不出片：如实报 False，端点返回 409。
    assert items[0]["has_clip"] is False
    audio = client.get(f"/api/voiceprints/{items[0]['id']}/audio")
    assert audio.status_code == 409


def test_template_audio_endpoint_streams_clip_and_404s_unknown(client):
    import io
    import wave as wave_module

    created = client.post(
        "/api/meetings", json={"title": "切片试听", "expected_speakers": 2}
    )
    meeting_id = created.json()["id"]
    buffer = io.BytesIO()
    with wave_module.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16000)
        writer.writeframes(b"\x00\x00" * int(16000 * 20))
    client.post(
        f"/api/meetings/{meeting_id}/upload",
        files={"file": ("meeting.wav", buffer.getvalue(), "audio/wav")},
    )
    assert client.app.state.worker.process_next() == meeting_id
    _submit_new_person_and_unknown(client, meeting_id)

    items = client.get("/api/voiceprints").json()["items"]
    assert items[0]["has_clip"] is True

    audio = client.get(f"/api/voiceprints/{items[0]['id']}/audio")
    assert audio.status_code == 200
    assert audio.headers["content-type"].startswith("audio/")
    assert len(audio.content) > 44

    assert client.get("/api/voiceprints/deadbeef/audio").status_code == 404


def test_delete_voiceprint_also_removes_clip_file(client):
    import io
    import wave as wave_module

    created = client.post(
        "/api/meetings", json={"title": "删除清片", "expected_speakers": 2}
    )
    meeting_id = created.json()["id"]
    buffer = io.BytesIO()
    with wave_module.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16000)
        writer.writeframes(b"\x00\x00" * int(16000 * 20))
    client.post(
        f"/api/meetings/{meeting_id}/upload",
        files={"file": ("meeting.wav", buffer.getvalue(), "audio/wav")},
    )
    assert client.app.state.worker.process_next() == meeting_id
    _submit_new_person_and_unknown(client, meeting_id)
    items = client.get("/api/voiceprints").json()["items"]
    clip_path = (
        client.app.state.settings.data_dir / "voiceprints" / f"{items[0]['id']}.wav"
    )
    assert clip_path.is_file()

    assert client.delete(f"/api/voiceprints/{items[0]['id']}").status_code == 204

    assert not clip_path.exists()
