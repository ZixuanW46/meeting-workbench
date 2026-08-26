from meeting_api.models import Meeting


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
