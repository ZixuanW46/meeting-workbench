from sqlalchemy import event

from meeting_api.models import Meeting, Person, SpeakerCluster


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
