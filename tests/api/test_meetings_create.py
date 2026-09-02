from meeting_api.models import Meeting, Person, SpeakerCluster
from meeting_domain import MeetingState


def test_create_meeting(client):
    response = client.post(
        "/api/meetings",
        json={
            "title": "周会",
            "expected_speakers": 4,
            "hotwords": ["声纹", "MLX"],
        },
    )

    assert response.status_code == 201
    meeting = response.json()
    assert meeting["id"]
    assert meeting["title"] == "周会"
    assert meeting["state"] == "DRAFT"
    assert meeting["expected_speakers"] == 4
    assert meeting["hotwords"] == ["声纹", "MLX"]


def test_create_meeting_without_expected_speakers(client):
    response = client.post(
        "/api/meetings",
        json={"title": "人数待定会议", "hotwords": []},
    )

    assert response.status_code == 201
    assert response.json()["expected_speakers"] is None


def test_create_meeting_without_title_uses_placeholder_and_stays_auto_named(client):
    # 标题选填：留空先占位，上传后取文件名，纪要生成后自动命名。
    response = client.post(
        "/api/meetings",
        json={"title": "", "expected_speakers": 4, "hotwords": []},
    )

    assert response.status_code == 201
    assert response.json()["title"] == "未命名会议"
    with client.app.state.session_factory() as session:
        meeting = session.get(Meeting, response.json()["id"])
        assert meeting is not None
        assert meeting.title_user_edited is False

    omitted = client.post("/api/meetings", json={"hotwords": []})
    assert omitted.status_code == 201
    assert omitted.json()["title"] == "未命名会议"


def test_create_meeting_with_title_counts_as_user_edited(client):
    response = client.post("/api/meetings", json={"title": "周会"})

    assert response.status_code == 201
    with client.app.state.session_factory() as session:
        meeting = session.get(Meeting, response.json()["id"])
        assert meeting is not None
        assert meeting.title_user_edited is True


def test_upload_filename_names_untitled_meeting_but_not_user_titled_one(client):
    untitled = client.post("/api/meetings", json={}).json()["id"]
    titled = client.post("/api/meetings", json={"title": "复盘会"}).json()["id"]
    for meeting_id in (untitled, titled):
        response = client.post(
            f"/api/meetings/{meeting_id}/upload",
            files={"file": ("2026-08-31_merged.wav", b"fake audio bytes", "audio/wav")},
        )
        assert response.status_code == 200

    assert client.get(f"/api/meetings/{untitled}").json()["title"] == "2026-08-31_merged"
    assert client.get(f"/api/meetings/{titled}").json()["title"] == "复盘会"


def test_get_meeting_detail_and_missing_meeting(client):
    created = client.post(
        "/api/meetings",
        json={"title": "项目复盘", "hotwords": ["复盘"]},
    ).json()

    response = client.get(f"/api/meetings/{created['id']}")
    assert response.status_code == 200
    assert response.json() == created

    missing = client.get("/api/meetings/does-not-exist")
    assert missing.status_code == 404


def test_update_meeting_title_persists(client):
    created = client.post(
        "/api/meetings",
        json={"title": "旧标题", "hotwords": ["复盘"]},
    ).json()
    session_factory = client.app.state.session_factory
    with session_factory() as session:
        meeting = session.get(Meeting, created["id"])
        meeting.state = MeetingState.PROCESSING.value
        session.commit()

    response = client.patch(
        f"/api/meetings/{created['id']}",
        json={"title": "  新标题  "},
    )

    assert response.status_code == 200
    updated = response.json()
    assert updated == {
        **created,
        "title": "新标题",
        "state": MeetingState.PROCESSING.value,
    }
    assert client.get(f"/api/meetings/{created['id']}").json() == updated
    with session_factory() as session:
        stored = session.get(Meeting, created["id"])
        assert stored.title == "新标题"
        assert stored.state == MeetingState.PROCESSING.value


def test_update_meeting_title_keeps_get_speaker_summary(client):
    created = client.post("/api/meetings", json={"title": "旧标题"}).json()
    session_factory = client.app.state.session_factory
    with session_factory() as session:
        person = Person(display_name="王芳")
        session.add(person)
        session.flush()
        session.add_all(
            [
                SpeakerCluster(
                    meeting_id=created["id"],
                    cluster_id="S1",
                    person_id=person.id,
                    total_seconds=20.0,
                ),
                SpeakerCluster(
                    meeting_id=created["id"],
                    cluster_id="S2",
                    person_id=None,
                    total_seconds=10.0,
                ),
            ]
        )
        session.commit()

    before = client.get(f"/api/meetings/{created['id']}").json()
    response = client.patch(
        f"/api/meetings/{created['id']}", json={"title": "新标题"}
    )

    assert before["speakers"] == ["王芳"]
    assert before["unknown_speaker_count"] == 1
    assert response.status_code == 200
    assert response.json() == {**before, "title": "新标题"}


def test_update_meeting_title_missing_meeting(client):
    response = client.patch(
        "/api/meetings/does-not-exist",
        json={"title": "新标题"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "会议不存在"


def test_update_meeting_title_rejects_empty_title(client):
    created = client.post("/api/meetings", json={"title": "旧标题"}).json()

    response = client.patch(
        f"/api/meetings/{created['id']}",
        json={"title": ""},
    )

    assert response.status_code == 422


def test_update_meeting_title_rejects_too_long_title(client):
    created = client.post("/api/meetings", json={"title": "旧标题"}).json()

    response = client.patch(
        f"/api/meetings/{created['id']}",
        json={"title": "会" * 201},
    )

    assert response.status_code == 422


def test_list_meetings_in_reverse_creation_order(client):
    first = client.post(
        "/api/meetings",
        json={"title": "第一次会议", "hotwords": []},
    ).json()
    second = client.post(
        "/api/meetings",
        json={"title": "第二次会议", "hotwords": ["最新"]},
    ).json()

    response = client.get("/api/meetings")

    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["id"] for item in items] == [second["id"], first["id"]]
    assert items == [second, first]

def test_create_meeting_treats_blank_title_as_untitled(client):
    response = client.post(
        "/api/meetings",
        json={"title": "   ", "expected_speakers": 4, "hotwords": []},
    )
    assert response.status_code == 201
    assert response.json()["title"] == "未命名会议"


def test_create_meeting_rejects_zero_expected_speakers(client):
    response = client.post(
        "/api/meetings",
        json={"title": "周会", "expected_speakers": 0, "hotwords": []},
    )
    assert response.status_code == 422


def test_create_meeting_defaults_hotwords_to_empty_list(client):
    response = client.post("/api/meetings", json={"title": "无热词会议"})

    assert response.status_code == 201
    assert response.json()["hotwords"] == []


def test_create_meeting_strips_title(client):
    response = client.post("/api/meetings", json={"title": "  周会  "})

    assert response.status_code == 201
    created = response.json()
    assert created["title"] == "周会"
    # 详情返回的也是清洗后的标题
    detail = client.get(f"/api/meetings/{created['id']}").json()
    assert detail["title"] == "周会"


def test_create_meeting_normalizes_hotwords(client):
    response = client.post(
        "/api/meetings",
        json={"title": "周会", "hotwords": ["  声纹 ", "", "MLX", "声纹", "   "]},
    )

    assert response.status_code == 201
    created = response.json()
    # 去首尾空白、去空项、去重且保序
    assert created["hotwords"] == ["声纹", "MLX"]
    detail = client.get(f"/api/meetings/{created['id']}").json()
    assert detail["hotwords"] == ["声纹", "MLX"]
