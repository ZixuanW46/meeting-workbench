"""默认项目 General：自动存在、不可删、不单独维护热词、兜住所有会议。

默认项目靠 `is_default` 标记识别，绝不靠名字——它可以被改名。
"""

from __future__ import annotations

DEFAULT_UNDELETABLE = "General 是默认项目，不能删除"
DEFAULT_HOTWORDS_MANAGED = "General 自动叠加所有项目的热词，不单独维护"


def _default_project(client) -> dict:
    items = client.get("/api/projects").json()["items"]
    defaults = [item for item in items if item["is_default"]]
    assert len(defaults) == 1, items
    return defaults[0]


def _create_project(client, name: str) -> str:
    response = client.post("/api/projects", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _add_project_hotword(client, project_id: str, word: str, note: str | None = None) -> str:
    response = client.post(
        f"/api/projects/{project_id}/hotwords", json={"word": word, "note": note}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _create_meeting(client, payload: dict) -> str:
    response = client.post("/api/meetings", json=payload)
    assert response.status_code == 201, response.text
    return response.json()["id"]


# --- 存在性 ------------------------------------------------------------------


def test_lifespan_creates_exactly_one_default_project(client):
    items = client.get("/api/projects").json()["items"]

    assert [item["name"] for item in items] == ["General"]
    assert items[0]["is_default"] is True
    assert items[0]["position"] == 0


def test_project_response_carries_is_default_flag(client):
    _create_project(client, "普通项目")

    items = client.get("/api/projects").json()["items"]

    assert {item["name"]: item["is_default"] for item in items} == {
        "General": True,
        "普通项目": False,
    }
    assert set(items[0]) == {
        "id",
        "name",
        "created_at",
        "meeting_count",
        "hotword_count",
        "position",
        "is_default",
    }


def test_default_project_cannot_be_deleted(client):
    general = _default_project(client)

    response = client.delete(f"/api/projects/{general['id']}")

    assert response.status_code == 409
    assert response.json()["detail"] == DEFAULT_UNDELETABLE
    assert _default_project(client)["id"] == general["id"]


def test_default_project_can_be_renamed_and_reordered(client):
    general = _default_project(client)
    other = _create_project(client, "另一个项目")

    renamed = client.patch(f"/api/projects/{general['id']}", json={"name": "总库"})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "总库"
    assert renamed.json()["is_default"] is True

    reordered = client.put(
        "/api/projects/order", json={"ids": [other, general["id"]]}
    )
    assert reordered.status_code == 200
    assert [item["id"] for item in reordered.json()["items"]] == [other, general["id"]]
    assert _default_project(client)["id"] == general["id"]


# --- 会议永远有项目 ----------------------------------------------------------


def test_delete_project_moves_its_meetings_to_default_project(client):
    general = _default_project(client)
    project_id = _create_project(client, "待删项目")
    meeting_id = _create_meeting(
        client, {"title": "待删项目的会", "project_id": project_id}
    )

    assert client.delete(f"/api/projects/{project_id}").status_code == 204

    detail = client.get(f"/api/meetings/{meeting_id}").json()
    assert detail["project_id"] == general["id"]
    assert detail["project_name"] == "General"


def test_create_meeting_without_project_lands_in_default_project(client):
    general = _default_project(client)

    implicit = client.get(
        f"/api/meetings/{_create_meeting(client, {'title': '没给项目'})}"
    ).json()
    explicit = client.get(
        f"/api/meetings/{_create_meeting(client, {'title': '给了 null', 'project_id': None})}"
    ).json()

    assert implicit["project_id"] == general["id"]
    assert implicit["project_name"] == "General"
    assert explicit["project_id"] == general["id"]


def test_patch_meeting_project_id_null_falls_back_to_default_project(client):
    general = _default_project(client)
    project_id = _create_project(client, "原项目")
    meeting_id = _create_meeting(client, {"title": "改挂的会", "project_id": project_id})

    detached = client.patch(f"/api/meetings/{meeting_id}", json={"project_id": None})

    assert detached.status_code == 200
    assert detached.json()["project_id"] == general["id"]
    assert detached.json()["project_name"] == "General"


# --- 默认项目不单独维护热词 --------------------------------------------------


def test_default_project_rejects_hotword_writes(client):
    general = _default_project(client)
    project_id = _create_project(client, "普通项目")
    entry_id = _add_project_hotword(client, project_id, "项目词")

    created = client.post(
        f"/api/projects/{general['id']}/hotwords", json={"word": "不该有的词"}
    )
    assert created.status_code == 409
    assert created.json()["detail"] == DEFAULT_HOTWORDS_MANAGED

    patched = client.patch(
        f"/api/projects/{general['id']}/hotwords/{entry_id}", json={"note": "越权"}
    )
    assert patched.status_code == 409
    assert patched.json()["detail"] == DEFAULT_HOTWORDS_MANAGED

    deleted = client.delete(f"/api/projects/{general['id']}/hotwords/{entry_id}")
    assert deleted.status_code == 409
    assert deleted.json()["detail"] == DEFAULT_HOTWORDS_MANAGED

    # 拒绝之后普通项目的词条原样还在。
    assert [
        item["word"]
        for item in client.get(f"/api/projects/{project_id}/hotwords").json()["items"]
    ] == ["项目词"]


def test_default_project_hotwords_list_is_the_union_of_all_projects(client):
    general = _default_project(client)
    first = _create_project(client, "项目一")
    second = _create_project(client, "项目二")
    _add_project_hotword(client, first, "共同词")
    _add_project_hotword(client, first, "一的词", "一的注解")
    _add_project_hotword(client, second, "共同词", "二的说法")
    _add_project_hotword(client, second, "二的词")

    items = client.get(f"/api/projects/{general['id']}/hotwords").json()["items"]

    assert [item["word"] for item in items] == sorted(
        {"共同词", "一的词", "二的词"}
    )
    # 同词只出现一次；注解取「先写了注解的项目」的说法。
    assert {item["word"]: item["note"] for item in items} == {
        "共同词": "二的说法",
        "一的词": "一的注解",
        "二的词": None,
    }
    assert all(item["id"] for item in items)
