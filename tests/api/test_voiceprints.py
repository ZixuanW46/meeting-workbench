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
    # 与热词 API 保持一致的 {items: []} 包装。
    assert set(body) == {"items"}
    items = body["items"]
    assert len(items) == 1
    assert set(items[0]) == {"id", "person_id", "display_name"}
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
    assert client.get("/api/voiceprints").json() == {"items": []}

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
