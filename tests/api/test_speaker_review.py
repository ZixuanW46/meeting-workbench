from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest
from sqlalchemy import select, text

from meeting_api.models import Meeting, Person, SpeakerCluster, Voiceprint
from meeting_api.pipeline.diarization import FakeDiarizationBackend, SpeakerSegment
from meeting_api.pipeline.embedding import FakeEmbeddingBackend, embedding_to_bytes
from meeting_api.pipeline.serial import SingleModelSlot
from meeting_api.worker import Worker


def _s1_windows(expected_speakers: int) -> list[tuple[float, float]]:
    """fake 切分里 S1 的前几段时间窗：声纹口径与试听片段口径一致。"""
    n = expected_speakers
    return [
        (float(i * 5), float(i * 5 + 5))
        for i in range(max(4, 2 * n))
        if i % n == 0
    ][:3]


def _seed_s1_voiceprint(client, expected_speakers: int = 2) -> None:
    backend = FakeEmbeddingBackend()
    with SingleModelSlot().use(backend) as loaded:
        embedding = embedding_to_bytes(
            loaded.embed(Path("unused.wav"), _s1_windows(expected_speakers))
        )
    with client.app.state.session_factory() as session:
        session.add(Person(id="fake-person-1", display_name="已知用户 1"))
        session.add(Voiceprint(person_id="fake-person-1", embedding=embedding))
        session.commit()


def _prepare_review(
    client, *, title: str = "说话人确认测试", expected_speakers: int = 2
) -> str:
    _seed_s1_voiceprint(client, expected_speakers)
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
        assert 2 <= len(card["sample_clips"]) <= 5
        assert all(
            clip["start_seconds"] < clip["end_seconds"]
            for clip in card["sample_clips"]
        )

    forbidden = {"score", "percent", "confidence"}
    assert not ({key.lower() for key in _all_keys(body)} & forbidden)


class _UnevenDiarization(FakeDiarizationBackend):
    """三个主簇时长悬殊，外加一个 0.7s 碎簇（时间上贴着 S2 尾部）。"""

    def diarize(self, audio_path, expected_speakers=None):
        del audio_path, expected_speakers
        return [
            SpeakerSegment(0.0, 2.0, "S1"),
            SpeakerSegment(2.0, 20.0, "S2"),
            SpeakerSegment(20.0, 20.7, "S9"),
            SpeakerSegment(21.0, 31.0, "S3"),
            SpeakerSegment(31.0, 32.5, "S1"),
        ]


def test_review_cards_sorted_by_speaking_time_and_carry_total_seconds(client):
    # 真实录音动辄几十簇：主要说话人必须排最前，卡片要标累计发言时长，
    # 时长以切分产物为准（粗粒度转写求和会失真），碎簇秒数计入吸收它的主簇。
    _seed_s1_voiceprint(client)
    created = client.post("/api/meetings", json={"title": "时长排序"})
    meeting_id = created.json()["id"]
    uploaded = client.post(
        f"/api/meetings/{meeting_id}/upload",
        files={"file": ("meeting.wav", b"fake audio bytes", "audio/wav")},
    )
    assert uploaded.status_code == 200
    worker = Worker(
        client.app.state.session_factory,
        client.app.state.settings,
        diarization_backend=_UnevenDiarization(),
    )
    assert worker.process_next() == meeting_id

    body = client.get(f"/api/meetings/{meeting_id}/review").json()

    assert [card["cluster_id"] for card in body["cards"]] == ["S2", "S3", "S1"]
    totals = [card["total_seconds"] for card in body["cards"]]
    assert totals == pytest.approx([18.7, 10.0, 3.5])


def test_get_review_clips_carry_transcript_and_people_directory(client):
    # 每个试听片段带该时间窗内的逐段转写摘录；建议身份给显示名（无数值置信度）；
    # 附全局人员清单，供「换成其他人 / 从声纹库选择」下拉使用。
    meeting_id = _prepare_review(client)

    body = client.get(f"/api/meetings/{meeting_id}/review").json()

    cards = {card["cluster_id"]: card for card in body["cards"]}
    s1_clips = cards["S1"]["sample_clips"]
    assert all("text" in clip for clip in s1_clips)
    # fake 流水线：S1 的第一个片段 [0,5) 覆盖假转写第一段；[10,15) 无转写落在其上。
    assert "假转写第一段" in s1_clips[0]["text"]
    assert s1_clips[1]["text"] == ""
    assert "假转写第二段" in cards["S2"]["sample_clips"][0]["text"]

    assert cards["S1"]["suggested_display_name"] == "已知用户 1"
    assert cards["S2"]["suggested_display_name"] is None

    assert body["people"] == [
        {"id": "fake-person-1", "display_name": "已知用户 1"}
    ]


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


def _drive_to_ready(client, meeting_id: str) -> None:
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
    assert client.app.state.worker.process_next() == meeting_id
    assert client.get(f"/api/meetings/{meeting_id}").json()["state"] == "READY"


def test_reopen_review_backfills_confirmed_identity_and_regenerates_minutes(client):
    # 事后想改说话人决定不该整场重转写：READY 可重开确认停点，
    # 上一轮确认的身份回填为建议，确认后只重出纪要。
    meeting_id = _prepare_review(client)
    _drive_to_ready(client, meeting_id)
    first_minutes = client.get(f"/api/meetings/{meeting_id}/minutes").json()["markdown"]

    reopened = client.post(f"/api/meetings/{meeting_id}/review/reopen")

    assert reopened.status_code == 200
    assert reopened.json()["state"] == "AWAITING_SPEAKER_REVIEW"
    review = client.get(f"/api/meetings/{meeting_id}/review")
    assert review.status_code == 200
    cards = {card["cluster_id"]: card for card in review.json()["cards"]}
    # 上一轮 S1 落名王芳：重开后显示为建议身份，可一键确认。
    assert cards["S1"]["suggested_person_id"] is not None

    resubmitted = client.post(
        f"/api/meetings/{meeting_id}/review/decisions",
        json={
            "decisions": [
                {"cluster_id": "S1", "kind": "CONFIRM"},
                {"cluster_id": "S2", "kind": "NEW_PERSON", "display_name": "李雷"},
            ]
        },
    )
    assert resubmitted.status_code == 200
    assert resubmitted.json()["has_unconfirmed_speakers"] is False
    assert client.app.state.worker.process_next() == meeting_id

    detail = client.get(f"/api/meetings/{meeting_id}")
    assert detail.json()["state"] == "READY"
    second_minutes = client.get(f"/api/meetings/{meeting_id}/minutes").json()["markdown"]
    # 第一版带「含未确认说话人」标记；全部确认后的终版不再带。
    assert first_minutes.startswith("含未确认说话人")
    assert not second_minutes.startswith("含未确认说话人")


def test_reopen_review_allowed_from_partial_ready(client):
    meeting_id = _prepare_review(client)
    from meeting_api.minutes.adapter import FakeMinutesAdapter, MinutesCliError

    reviewed = client.post(
        f"/api/meetings/{meeting_id}/review/decisions",
        json={
            "decisions": [
                {"cluster_id": "S1", "kind": "UNDECIDED_UNKNOWN"},
                {"cluster_id": "S2", "kind": "UNDECIDED_UNKNOWN"},
            ]
        },
    )
    assert reviewed.status_code == 200
    client.app.state.worker.minutes_adapter = FakeMinutesAdapter(
        error=MinutesCliError("模拟 CLI 失败")
    )
    assert client.app.state.worker.process_next() == meeting_id
    assert client.get(f"/api/meetings/{meeting_id}").json()["state"] == "PARTIAL_READY"

    reopened = client.post(f"/api/meetings/{meeting_id}/review/reopen")

    assert reopened.status_code == 200
    assert reopened.json()["state"] == "AWAITING_SPEAKER_REVIEW"


def test_reopen_review_rejected_outside_completed_states(client):
    meeting_id = _prepare_review(client)

    response = client.post(f"/api/meetings/{meeting_id}/review/reopen")

    assert response.status_code == 409
    assert (
        client.get(f"/api/meetings/{meeting_id}").json()["state"]
        == "AWAITING_SPEAKER_REVIEW"
    )


def test_enrollment_replaces_redundant_template_with_fresh_provenance(client):
    # 同一环境重复确认（候选与既有模板余弦=1）：不堆重复模板，
    # 替换那条并刷新 来源会议/转写摘录。
    meeting_id = _prepare_review(client)

    response = client.post(
        f"/api/meetings/{meeting_id}/review/decisions",
        json={
            "decisions": [
                {"cluster_id": "S1", "kind": "CONFIRM"},
                {"cluster_id": "S2", "kind": "NEW_PERSON", "display_name": "李雷"},
            ]
        },
    )
    assert response.status_code == 200

    with client.app.state.session_factory() as session:
        s1_rows = session.scalars(
            select(Voiceprint).where(Voiceprint.person_id == "fake-person-1")
        ).all()
        lei_rows = session.scalars(
            select(Voiceprint)
            .join(Person, Person.id == Voiceprint.person_id)
            .where(Person.display_name == "李雷")
        ).all()
    assert len(s1_rows) == 1
    assert s1_rows[0].source_meeting_id == meeting_id
    assert "假转写第一段" in s1_rows[0].snippet_text
    assert len(lei_rows) == 1
    assert lei_rows[0].source_meeting_id == meeting_id
    assert "假转写第二段" in lei_rows[0].snippet_text


def _orthogonal_vector() -> tuple[float, ...]:
    """与 fake 切分 S1 窗向量近似正交的确定性向量，用来种子一条「不同环境」模板。"""
    backend = FakeEmbeddingBackend()
    with SingleModelSlot().use(backend) as loaded:
        return loaded.embed(Path("unused.wav"), [(100.0, 105.0)])


def test_enrollment_appends_template_when_voice_differs(client):
    # 换了环境（候选与既有模板近似正交）：追加为第二条模板而不是覆盖。
    # 不用跨文件 import tests.*：pythonpath 只有 domain/api，CI 的 python -m pytest 找不到 tests 包。
    with client.app.state.session_factory() as session:
        session.add(Person(id="fake-person-1", display_name="已知用户 1"))
        session.add(
            Voiceprint(
                person_id="fake-person-1",
                embedding=embedding_to_bytes(_orthogonal_vector()),
            )
        )
        session.commit()
    created = client.post(
        "/api/meetings", json={"title": "追加模板", "expected_speakers": 2}
    )
    meeting_id = created.json()["id"]
    uploaded = client.post(
        f"/api/meetings/{meeting_id}/upload",
        files={"file": ("meeting.wav", b"fake audio bytes", "audio/wav")},
    )
    assert uploaded.status_code == 200
    assert client.app.state.worker.process_next() == meeting_id

    response = client.post(
        f"/api/meetings/{meeting_id}/review/decisions",
        json={
            "decisions": [
                {"cluster_id": "S1", "kind": "LINK_EXISTING", "person_id": "fake-person-1"},
                {"cluster_id": "S2", "kind": "UNDECIDED_UNKNOWN"},
            ]
        },
    )
    assert response.status_code == 200

    with client.app.state.session_factory() as session:
        rows = session.scalars(
            select(Voiceprint)
            .where(Voiceprint.person_id == "fake-person-1")
            .order_by(Voiceprint.created_at.is_(None).desc(), Voiceprint.created_at)
        ).all()
    assert len(rows) == 2
    assert rows[1].source_meeting_id == meeting_id


def test_enrollment_writes_audition_clip_for_real_wav(client, tmp_path):
    # 每条模板留一段代表性试听切片（≤10 秒），供声纹库页人工核对。
    import io
    import wave as wave_module

    created = client.post(
        "/api/meetings", json={"title": "试听切片", "expected_speakers": 2}
    )
    meeting_id = created.json()["id"]
    buffer = io.BytesIO()
    with wave_module.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16000)
        writer.writeframes(b"\x00\x00" * int(16000 * 20))
    uploaded = client.post(
        f"/api/meetings/{meeting_id}/upload",
        files={"file": ("meeting.wav", buffer.getvalue(), "audio/wav")},
    )
    assert uploaded.status_code == 200
    assert client.app.state.worker.process_next() == meeting_id

    response = client.post(
        f"/api/meetings/{meeting_id}/review/decisions",
        json={
            "decisions": [
                {"cluster_id": "S1", "kind": "NEW_PERSON", "display_name": "王芳"},
                {"cluster_id": "S2", "kind": "UNDECIDED_UNKNOWN"},
            ]
        },
    )
    assert response.status_code == 200

    with client.app.state.session_factory() as session:
        row = session.scalars(
            select(Voiceprint)
            .join(Person, Person.id == Voiceprint.person_id)
            .where(Person.display_name == "王芳")
        ).one()
    clip_path = (
        client.app.state.settings.data_dir / "voiceprints" / f"{row.id}.wav"
    )
    assert clip_path.is_file()
    assert clip_path.stat().st_size > 44  # 大于空 wav 头


def _prepare_three_cluster_review(client) -> str:
    # 3 人布局下 fake 切分给 S1 的窗是 (0,5)+(15,20)：种子声纹按同窗生成才有建议。
    backend = FakeEmbeddingBackend()
    with SingleModelSlot().use(backend) as loaded:
        vector = loaded.embed(Path("unused.wav"), [(0.0, 5.0), (15.0, 20.0)])
    with client.app.state.session_factory() as session:
        session.add(Person(id="fake-person-1", display_name="已知用户 1"))
        session.add(
            Voiceprint(
                person_id="fake-person-1", embedding=embedding_to_bytes(vector)
            )
        )
        session.commit()
    created = client.post(
        "/api/meetings", json={"title": "尾簇就近", "expected_speakers": 3}
    )
    meeting_id = created.json()["id"]
    uploaded = client.post(
        f"/api/meetings/{meeting_id}/upload",
        files={"file": ("meeting.wav", b"fake audio bytes", "audio/wav")},
    )
    assert uploaded.status_code == 200
    assert client.app.state.worker.process_next() == meeting_id
    return meeting_id


def _copy_cluster_embedding(client, meeting_id, source_cluster, target_cluster):
    with client.app.state.session_factory() as session:
        rows = {
            cluster.cluster_id: cluster
            for cluster in session.scalars(
                select(SpeakerCluster).where(SpeakerCluster.meeting_id == meeting_id)
            )
        }
        rows[target_cluster].embedding = rows[source_cluster].embedding
        session.commit()


def test_nearest_confirmed_assigns_tail_to_closest_anchor_without_enrollment(client):
    meeting_id = _prepare_three_cluster_review(client)
    # 让 S3 的簇声纹与 S1 完全一致：就近归属必然落到 S1 确认的人。
    _copy_cluster_embedding(client, meeting_id, "S1", "S3")

    response = client.post(
        f"/api/meetings/{meeting_id}/review/decisions",
        json={
            "decisions": [
                {"cluster_id": "S1", "kind": "CONFIRM"},
                {"cluster_id": "S2", "kind": "NEW_PERSON", "display_name": "李雷"},
                {"cluster_id": "S3", "kind": "NEAREST_CONFIRMED"},
            ]
        },
    )

    assert response.status_code == 200
    assert response.json()["has_unconfirmed_speakers"] is False
    with client.app.state.session_factory() as session:
        clusters = {
            cluster.cluster_id: cluster
            for cluster in session.scalars(
                select(SpeakerCluster).where(SpeakerCluster.meeting_id == meeting_id)
            )
        }
        voiceprint_people = [
            row.person_id
            for row in session.execute(text("SELECT person_id FROM voiceprints"))
        ]
    assert clusters["S3"].person_id == "fake-person-1"
    assert clusters["S3"].assigned_via == "voiceprint_nearest"
    assert clusters["S1"].assigned_via is None
    # 就近归属不入声纹库：库里只有 S1 确认与李雷新建的模板。
    assert sorted(voiceprint_people).count("fake-person-1") == 1
    assert len(voiceprint_people) == 2


def test_nearest_confirmed_without_anchor_returns_422(client):
    meeting_id = _prepare_review(client)

    response = client.post(
        f"/api/meetings/{meeting_id}/review/decisions",
        json={
            "decisions": [
                {"cluster_id": "S1", "kind": "NEAREST_CONFIRMED"},
                {"cluster_id": "S2", "kind": "NEAREST_CONFIRMED"},
            ]
        },
    )

    assert response.status_code == 422
    assert "已确认" in str(response.json()["detail"])
    assert (
        client.get(f"/api/meetings/{meeting_id}").json()["state"]
        == "AWAITING_SPEAKER_REVIEW"
    )


def test_nearest_confirmed_with_missing_embedding_returns_422(client):
    meeting_id = _prepare_review(client)
    with client.app.state.session_factory() as session:
        for cluster in session.scalars(
            select(SpeakerCluster).where(SpeakerCluster.meeting_id == meeting_id)
        ):
            if cluster.cluster_id == "S2":
                cluster.embedding = None
        session.commit()

    response = client.post(
        f"/api/meetings/{meeting_id}/review/decisions",
        json={
            "decisions": [
                {"cluster_id": "S1", "kind": "CONFIRM"},
                {"cluster_id": "S2", "kind": "NEAREST_CONFIRMED"},
            ]
        },
    )

    assert response.status_code == 422
    assert "重转写" in str(response.json()["detail"])


def test_nearest_assignment_marks_minutes_and_transcript(client):
    meeting_id = _prepare_three_cluster_review(client)
    _copy_cluster_embedding(client, meeting_id, "S1", "S3")
    response = client.post(
        f"/api/meetings/{meeting_id}/review/decisions",
        json={
            "decisions": [
                {"cluster_id": "S1", "kind": "CONFIRM"},
                {"cluster_id": "S2", "kind": "NEW_PERSON", "display_name": "李雷"},
                {"cluster_id": "S3", "kind": "NEAREST_CONFIRMED"},
            ]
        },
    )
    assert response.status_code == 200
    # 给 S3 插一条转写行，验证逐字稿署名带「（就近归属）」标注。
    from meeting_api.models import TranscriptSegment

    with client.app.state.session_factory() as session:
        session.add(
            TranscriptSegment(
                meeting_id=meeting_id,
                start_seconds=90.0,
                end_seconds=92.0,
                text="补一句。",
                cluster_id="S3",
            )
        )
        session.commit()

    assert client.app.state.worker.process_next() == meeting_id

    minutes = client.get(f"/api/meetings/{meeting_id}/minutes")
    assert minutes.status_code == 200
    assert minutes.json()["markdown"].startswith("部分次要发言按声纹就近归属")
    transcript = client.get(f"/api/meetings/{meeting_id}/export/transcript.md").text
    assert "（就近归属）" in transcript
    assert "已知用户 1（就近归属）：补一句。" in transcript
