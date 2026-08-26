from __future__ import annotations

from collections.abc import Mapping, Sequence

import pytest
from sqlalchemy import select, text

from meeting_api.models import Meeting, SpeakerCluster


def _prepare_review(
    client, *, title: str = "说话人确认测试", expected_speakers: int = 2
) -> str:
    created = client.post(
        "/api/meetings",
        json={"title": title, "expected_speakers": expected_speakers},
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


def _all_keys(value: object) -> set[str]:
    if isinstance(value, Mapping):
        return set(value) | {
            key for child in value.values() for key in _all_keys(child)
        }
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return {key for child in value for key in _all_keys(child)}
    return set()


def test_get_review_returns_cards_with_samples_and_text_without_fake_precision(client):
    meeting_id = _prepare_review(client)

    response = client.get(f"/api/meetings/{meeting_id}/review")

    assert response.status_code == 200
    body = response.json()
    assert {card["cluster_id"] for card in body["cards"]} == {"S1", "S2"}
    cards = {card["cluster_id"]: card for card in body["cards"]}
    assert cards["S1"]["suggested_person_id"] == "fake-person-1"
    assert cards["S2"]["suggested_person_id"] is None
    for card in cards.values():
        assert card["text"]
        assert 2 <= len(card["sample_clips"]) <= 3
        assert all(
            clip["start_seconds"] < clip["end_seconds"]
            for clip in card["sample_clips"]
        )

    forbidden = {"score", "percent", "confidence"}
    assert not ({key.lower() for key in _all_keys(body)} & forbidden)


def test_all_decisions_advance_state_and_apply_final_labels(client):
    meeting_id = _prepare_review(client)

    # 建议身份只是建议；提交人工决定之前不得成为最终身份。
    with client.app.state.session_factory() as session:
        before = session.scalars(
            select(SpeakerCluster)
            .where(SpeakerCluster.meeting_id == meeting_id)
            .order_by(SpeakerCluster.cluster_id)
        ).all()
        assert before[0].suggested_person_id == "fake-person-1"
        assert all(cluster.person_id is None for cluster in before)
        assert all(not cluster.is_unknown for cluster in before)

    response = client.post(
        f"/api/meetings/{meeting_id}/review/decisions",
        json={
            "decisions": [
                {"cluster_id": "S1", "kind": "CONFIRM"},
                {
                    "cluster_id": "S2",
                    "kind": "NEW_PERSON",
                    "display_name": "李雷",
                },
            ]
        },
    )

    assert response.status_code == 200
    assert response.json()["state"] == "GENERATING_MINUTES"
    with client.app.state.session_factory() as session:
        meeting = session.get(Meeting, meeting_id)
        clusters = session.scalars(
            select(SpeakerCluster)
            .where(SpeakerCluster.meeting_id == meeting_id)
            .order_by(SpeakerCluster.cluster_id)
        ).all()
        people = session.execute(text("SELECT id, display_name FROM persons")).all()

    assert meeting.state == "GENERATING_MINUTES"
    assert not meeting.has_unconfirmed_speakers
    assert clusters[0].person_id == "fake-person-1"
    assert not clusters[0].is_unknown
    assert clusters[1].person_id is not None
    assert not clusters[1].is_unknown
    assert (clusters[1].person_id, "李雷") in people


def test_missing_decision_returns_409_with_cluster_and_keeps_review_state(client):
    meeting_id = _prepare_review(client)

    response = client.post(
        f"/api/meetings/{meeting_id}/review/decisions",
        json={"decisions": [{"cluster_id": "S1", "kind": "CONFIRM"}]},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["missing_cluster_ids"] == ["S2"]
    with client.app.state.session_factory() as session:
        meeting = session.get(Meeting, meeting_id)
    assert meeting.state == "AWAITING_SPEAKER_REVIEW"


def test_explicit_unknown_decisions_are_valid_and_mark_meeting_and_clusters(client):
    meeting_id = _prepare_review(client)

    response = client.post(
        f"/api/meetings/{meeting_id}/review/decisions",
        json={
            "decisions": [
                {"cluster_id": "S1", "kind": "KEEP_UNKNOWN"},
                {"cluster_id": "S2", "kind": "UNDECIDED_UNKNOWN"},
            ]
        },
    )

    assert response.status_code == 200
    with client.app.state.session_factory() as session:
        meeting = session.get(Meeting, meeting_id)
        clusters = session.scalars(
            select(SpeakerCluster).where(SpeakerCluster.meeting_id == meeting_id)
        ).all()
    assert meeting.has_unconfirmed_speakers is True
    assert all(cluster.person_id is None for cluster in clusters)
    assert all(cluster.is_unknown for cluster in clusters)


@pytest.mark.parametrize("kind", ["REASSIGN", "LINK_EXISTING"])
def test_existing_person_decisions_require_person_id(client, kind):
    meeting_id = _prepare_review(client, title=f"缺 person_id：{kind}")

    response = client.post(
        f"/api/meetings/{meeting_id}/review/decisions",
        json={
            "decisions": [
                {"cluster_id": "S1", "kind": kind},
                {"cluster_id": "S2", "kind": "UNDECIDED_UNKNOWN"},
            ]
        },
    )

    assert response.status_code == 422
    with client.app.state.session_factory() as session:
        meeting = session.get(Meeting, meeting_id)
    assert meeting.state == "AWAITING_SPEAKER_REVIEW"


def test_merge_chain_resolves_transitively_to_final_person(client):
    meeting_id = _prepare_review(client, title="链式合并", expected_speakers=3)

    response = client.post(
        f"/api/meetings/{meeting_id}/review/decisions",
        json={
            "decisions": [
                {"cluster_id": "S1", "kind": "CONFIRM"},
                {
                    "cluster_id": "S2",
                    "kind": "MERGE_WITH_CLUSTER",
                    "merge_into_cluster_id": "S1",
                },
                {
                    "cluster_id": "S3",
                    "kind": "MERGE_WITH_CLUSTER",
                    "merge_into_cluster_id": "S2",
                },
            ]
        },
    )

    assert response.status_code == 200
    assert not response.json()["has_unconfirmed_speakers"]
    with client.app.state.session_factory() as session:
        clusters = session.scalars(
            select(SpeakerCluster).where(SpeakerCluster.meeting_id == meeting_id)
        ).all()
    assert all(cluster.person_id == "fake-person-1" for cluster in clusters)
    assert all(not cluster.is_unknown for cluster in clusters)


def test_merge_cycle_is_rejected_and_state_unchanged(client):
    meeting_id = _prepare_review(client, title="合并成环")

    response = client.post(
        f"/api/meetings/{meeting_id}/review/decisions",
        json={
            "decisions": [
                {
                    "cluster_id": "S1",
                    "kind": "MERGE_WITH_CLUSTER",
                    "merge_into_cluster_id": "S2",
                },
                {
                    "cluster_id": "S2",
                    "kind": "MERGE_WITH_CLUSTER",
                    "merge_into_cluster_id": "S1",
                },
            ]
        },
    )

    assert response.status_code == 422
    with client.app.state.session_factory() as session:
        meeting = session.get(Meeting, meeting_id)
        clusters = session.scalars(
            select(SpeakerCluster).where(SpeakerCluster.meeting_id == meeting_id)
        ).all()
    assert meeting.state == "AWAITING_SPEAKER_REVIEW"
    assert all(cluster.person_id is None for cluster in clusters)


def test_confirm_requires_suggested_person_to_exist_in_persons(client):
    meeting_id = _prepare_review(client, title="建议身份已失效")

    # SQLite 未开外键强制：人为删掉建议指向的人，CONFIRM 不得落一个悬空 id。
    with client.app.state.session_factory() as session:
        session.execute(text("DELETE FROM persons WHERE id = 'fake-person-1'"))
        session.commit()

    response = client.post(
        f"/api/meetings/{meeting_id}/review/decisions",
        json={
            "decisions": [
                {"cluster_id": "S1", "kind": "CONFIRM"},
                {"cluster_id": "S2", "kind": "KEEP_UNKNOWN"},
            ]
        },
    )

    assert response.status_code == 422
    with client.app.state.session_factory() as session:
        meeting = session.get(Meeting, meeting_id)
    assert meeting.state == "AWAITING_SPEAKER_REVIEW"


def test_decisions_rejected_outside_speaker_review_state(client):
    created = client.post("/api/meetings", json={"title": "尚未上传"})
    meeting_id = created.json()["id"]

    response = client.post(
        f"/api/meetings/{meeting_id}/review/decisions",
        json={"decisions": []},
    )

    assert response.status_code == 409
    assert client.get(f"/api/meetings/{meeting_id}").json()["state"] == "DRAFT"
