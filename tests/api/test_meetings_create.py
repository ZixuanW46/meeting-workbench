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


def test_create_meeting_rejects_empty_title(client):
    response = client.post(
        "/api/meetings",
        json={"title": "", "expected_speakers": 4, "hotwords": []},
    )

    assert response.status_code == 422


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

def test_create_meeting_rejects_blank_title(client):
    response = client.post(
        "/api/meetings",
        json={"title": "   ", "expected_speakers": 4, "hotwords": []},
    )
    assert response.status_code == 422


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

