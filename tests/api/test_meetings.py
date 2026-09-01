from sqlalchemy import event, select

from meeting_api.models import Meeting, Person, SpeakerCluster, TranscriptSegment, Voiceprint
from meeting_api.pipeline.embedding import embedding_to_bytes
from meeting_api.storage import meeting_dir
from meeting_domain import MeetingState


def test_empty_meeting_list(client):
    resp = client.get("/api/meetings")
    assert resp.status_code == 200
    assert resp.json() == {"items": []}


def test_list_returns_seeded_meeting(client):
    session_factory = client.app.state.session_factory
    with session_factory() as session:
        session.add(Meeting(title="周会", expected_speakers=4))
        session.commit()

    items = client.get("/api/meetings").json()["items"]
    assert len(items) == 1
    assert items[0]["title"] == "周会"
    assert items[0]["state"] == "DRAFT"
    assert items[0]["expected_speakers"] == 4


def test_meeting_detail_returns_confirmed_speakers_and_unknown_count(client):
    session_factory = client.app.state.session_factory
    with session_factory() as session:
        meeting = Meeting(title="评审会")
        will = Person(display_name="Will")
        leo = Person(display_name="Leo")
        session.add_all([meeting, will, leo])
        session.flush()
        session.add_all(
            [
                SpeakerCluster(
                    meeting_id=meeting.id,
                    cluster_id="S1",
                    person_id=will.id,
                    total_seconds=15.0,
                ),
                SpeakerCluster(
                    meeting_id=meeting.id,
                    cluster_id="S2",
                    person_id=leo.id,
                    total_seconds=40.0,
                ),
                SpeakerCluster(
                    meeting_id=meeting.id,
                    cluster_id="S3",
                    person_id=will.id,
                    total_seconds=30.0,
                ),
                SpeakerCluster(
                    meeting_id=meeting.id,
                    cluster_id="S4",
                    person_id=None,
                    total_seconds=80.0,
                ),
            ]
        )
        session.commit()
        meeting_id = meeting.id

    response = client.get(f"/api/meetings/{meeting_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["speakers"] == ["Will", "Leo"]
    assert payload["unknown_speaker_count"] == 1


def test_meeting_response_hides_unknown_count_before_any_identity_is_confirmed(client):
    session_factory = client.app.state.session_factory
    with session_factory() as session:
        meeting = Meeting(title="未确认会议")
        session.add(meeting)
        session.flush()
        session.add_all(
            [
                SpeakerCluster(
                    meeting_id=meeting.id,
                    cluster_id="S1",
                    person_id=None,
                    total_seconds=10.0,
                ),
                SpeakerCluster(
                    meeting_id=meeting.id,
                    cluster_id="S2",
                    person_id=None,
                    total_seconds=20.0,
                ),
            ]
        )
        session.commit()
        meeting_id = meeting.id

    response = client.get(f"/api/meetings/{meeting_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["speakers"] == []
    assert payload["unknown_speaker_count"] == 0


def test_list_meetings_batches_speaker_summary_queries(client):
    session_factory = client.app.state.session_factory
    with session_factory() as session:
        person = Person(display_name="Will")
        session.add(person)
        session.flush()
        meetings = [Meeting(title=f"会议 {index}") for index in range(3)]
        session.add_all(meetings)
        session.flush()
        session.add_all(
            SpeakerCluster(
                meeting_id=meeting.id,
                cluster_id="S1",
                person_id=person.id,
                total_seconds=float(index + 1),
            )
            for index, meeting in enumerate(meetings)
        )
        session.commit()

    statements: list[str] = []

    def count_selects(conn, cursor, statement, parameters, context, executemany):
        del conn, cursor, parameters, context, executemany
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(client.app.state.engine, "before_cursor_execute", count_selects)
    try:
        response = client.get("/api/meetings")
    finally:
        event.remove(client.app.state.engine, "before_cursor_execute", count_selects)

    assert response.status_code == 200
    assert [item["speakers"] for item in response.json()["items"]] == [
        ["Will"],
        ["Will"],
        ["Will"],
    ]
    assert len(statements) <= 2


def test_delete_meeting_removes_detail_list_and_meeting_rows(client):
    session_factory = client.app.state.session_factory
    with session_factory() as session:
        meeting = Meeting(title="要删除的会议")
        kept = Meeting(title="保留的会议")
        session.add_all([meeting, kept])
        session.flush()
        session.add_all(
            [
                SpeakerCluster(
                    meeting_id=meeting.id,
                    cluster_id="S1",
                    total_seconds=12.0,
                ),
                TranscriptSegment(
                    meeting_id=meeting.id,
                    start_seconds=0.0,
                    end_seconds=1.0,
                    text="要删除",
                    cluster_id="S1",
                ),
            ]
        )
        session.commit()
        meeting_id = meeting.id
        kept_id = kept.id

    response = client.delete(f"/api/meetings/{meeting_id}")

    assert response.status_code == 204
    assert response.content == b""
    assert client.get(f"/api/meetings/{meeting_id}").status_code == 404
    listed_ids = {item["id"] for item in client.get("/api/meetings").json()["items"]}
    assert listed_ids == {kept_id}
    with session_factory() as session:
        assert session.get(Meeting, meeting_id) is None
        assert (
            session.scalars(
                select(SpeakerCluster).where(SpeakerCluster.meeting_id == meeting_id)
            ).all()
            == []
        )
        assert (
            session.scalars(
                select(TranscriptSegment).where(TranscriptSegment.meeting_id == meeting_id)
            ).all()
            == []
        )


def test_delete_meeting_removes_data_directory(client):
    session_factory = client.app.state.session_factory
    with session_factory() as session:
        meeting = Meeting(title="有文件目录的会议")
        session.add(meeting)
        session.commit()
        meeting_id = meeting.id
    target_dir = meeting_dir(client.app.state.settings, meeting_id)
    (target_dir / "raw").mkdir(parents=True)
    (target_dir / "raw" / "audio.wav").write_bytes(b"audio")

    response = client.delete(f"/api/meetings/{meeting_id}")

    assert response.status_code == 204
    assert not target_dir.exists()


def test_delete_processing_meeting_returns_409(client):
    session_factory = client.app.state.session_factory
    with session_factory() as session:
        meeting = Meeting(title="处理中会议", state=MeetingState.QUEUED.value)
        session.add(meeting)
        session.commit()
        meeting_id = meeting.id

    response = client.delete(f"/api/meetings/{meeting_id}")

    assert response.status_code == 409
    assert response.json()["detail"] == "处理中的会议不能删除"
    assert client.get(f"/api/meetings/{meeting_id}").status_code == 200


def test_delete_missing_meeting_returns_404(client):
    response = client.delete("/api/meetings/not-found")

    assert response.status_code == 404
    assert response.json()["detail"] == "会议不存在"


def test_delete_meeting_keeps_voiceprints_and_people(client):
    session_factory = client.app.state.session_factory
    with session_factory() as session:
        meeting = Meeting(title="声纹来源会议")
        person = Person(display_name="王芳")
        session.add_all([meeting, person])
        session.flush()
        voiceprint = Voiceprint(
            person_id=person.id,
            embedding=embedding_to_bytes((1.0, 0.0, 0.0)),
            source_meeting_id=meeting.id,
            snippet_text="试听摘录",
        )
        session.add(voiceprint)
        session.commit()
        meeting_id = meeting.id
        person_id = person.id
        voiceprint_id = voiceprint.id

    response = client.delete(f"/api/meetings/{meeting_id}")

    assert response.status_code == 204
    listed = client.get("/api/voiceprints").json()
    assert [person["id"] for person in listed["people"]] == [person_id]
    assert [item["id"] for item in listed["items"]] == [voiceprint_id]
    assert listed["items"][0]["source_meeting_title"] is None
    with session_factory() as session:
        assert session.get(Person, person_id) is not None
        voiceprint = session.get(Voiceprint, voiceprint_id)
        assert voiceprint is not None
        assert voiceprint.source_meeting_id is None
