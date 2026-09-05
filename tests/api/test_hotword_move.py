"""热词跨层移动：全局 ↔ 项目、项目 ↔ 项目，一次多条，同词合并。"""

from __future__ import annotations

DEFAULT_HOTWORDS_MANAGED = "General 自动叠加所有项目的热词，不单独维护"


def _default_project_id(client) -> str:
    items = client.get("/api/projects").json()["items"]
    (default_item,) = [item for item in items if item["is_default"]]
    return default_item["id"]


def _create_project(client, name: str) -> str:
    response = client.post("/api/projects", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _add_global(client, word: str, note: str | None = None) -> str:
    response = client.post("/api/hotwords", json={"word": word, "note": note})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _add_project(client, project_id: str, word: str, note: str | None = None) -> str:
    response = client.post(
        f"/api/projects/{project_id}/hotwords", json={"word": word, "note": note}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _global_words(client) -> dict[str, str | None]:
    return {
        item["word"]: item["note"]
        for item in client.get("/api/hotwords").json()["items"]
    }


def _project_words(client, project_id: str) -> dict[str, str | None]:
    return {
        item["word"]: item["note"]
        for item in client.get(f"/api/projects/{project_id}/hotwords").json()["items"]
    }


def _move(client, source: str | None, target: str | None, ids: list[str]):
    return client.post(
        "/api/hotwords/move",
        json={"from": {"project_id": source}, "to": {"project_id": target}, "ids": ids},
    )


# --- 三种方向 ----------------------------------------------------------------


def test_move_from_global_to_project(client):
    project_id = _create_project(client, "目标项目")
    first = _add_global(client, "词甲", "甲的注解")
    second = _add_global(client, "词乙")
    _add_global(client, "留在全局的词")

    response = _move(client, None, project_id, [first, second])

    assert response.status_code == 200, response.text
    assert response.json() == {"moved": 2, "merged": 0}
    assert _global_words(client) == {"留在全局的词": None}
    assert _project_words(client, project_id) == {"词甲": "甲的注解", "词乙": None}


def test_move_from_project_to_global(client):
    project_id = _create_project(client, "来源项目")
    entry_id = _add_project(client, project_id, "词甲", "甲的注解")
    _add_project(client, project_id, "留在项目的词")

    response = _move(client, project_id, None, [entry_id])

    assert response.status_code == 200, response.text
    assert response.json() == {"moved": 1, "merged": 0}
    assert _global_words(client) == {"词甲": "甲的注解"}
    assert _project_words(client, project_id) == {"留在项目的词": None}


def test_move_from_project_to_another_project(client):
    source = _create_project(client, "来源项目")
    target = _create_project(client, "目标项目")
    entry_id = _add_project(client, source, "词甲", "甲的注解")

    response = _move(client, source, target, [entry_id])

    assert response.status_code == 200, response.text
    assert response.json() == {"moved": 1, "merged": 0}
    assert _project_words(client, source) == {}
    assert _project_words(client, target) == {"词甲": "甲的注解"}


# --- 合并 --------------------------------------------------------------------


def test_move_merges_into_existing_word_and_keeps_target_note(client):
    project_id = _create_project(client, "目标项目")
    # 目标已有注解 → 保留目标的说法；目标注解为空 → 取来源的注解。
    _add_project(client, project_id, "有注解的词", "目标的说法")
    _add_project(client, project_id, "没注解的词")
    kept = _add_global(client, "有注解的词", "全局的说法")
    filled = _add_global(client, "没注解的词", "全局补上的注解")
    fresh = _add_global(client, "全新的词", "新词注解")

    response = _move(client, None, project_id, [kept, filled, fresh])

    assert response.status_code == 200, response.text
    assert response.json() == {"moved": 1, "merged": 2}
    assert _global_words(client) == {}
    assert _project_words(client, project_id) == {
        "有注解的词": "目标的说法",
        "没注解的词": "全局补上的注解",
        "全新的词": "新词注解",
    }


# --- 拒绝 --------------------------------------------------------------------


def test_move_with_unknown_id_changes_nothing(client):
    project_id = _create_project(client, "目标项目")
    other = _create_project(client, "别的项目")
    entry_id = _add_global(client, "词甲")
    foreign = _add_project(client, other, "别的项目的词")

    missing = _move(client, None, project_id, [entry_id, "not-an-entry"])
    assert missing.status_code == 404
    assert missing.json()["detail"] == "词语不存在"

    # 词条存在但不在来源层 → 同样按「不存在」处理，整单不动。
    wrong_layer = _move(client, None, project_id, [entry_id, foreign])
    assert wrong_layer.status_code == 404

    assert _global_words(client) == {"词甲": None}
    assert _project_words(client, project_id) == {}
    assert _project_words(client, other) == {"别的项目的词": None}


def test_move_between_the_same_layer_is_422(client):
    project_id = _create_project(client, "同一个项目")
    entry_id = _add_project(client, project_id, "词甲")
    global_id = _add_global(client, "全局词")

    same_project = _move(client, project_id, project_id, [entry_id])
    assert same_project.status_code == 422
    assert same_project.json()["detail"] == "来源与目标相同"

    same_global = _move(client, None, None, [global_id])
    assert same_global.status_code == 422
    assert same_global.json()["detail"] == "来源与目标相同"

    assert _project_words(client, project_id) == {"词甲": None}
    assert _global_words(client) == {"全局词": None}


def test_move_touching_the_default_project_is_409(client):
    default_id = _default_project_id(client)
    project_id = _create_project(client, "普通项目")
    entry_id = _add_project(client, project_id, "词甲")
    global_id = _add_global(client, "全局词")

    into_default = _move(client, project_id, default_id, [entry_id])
    assert into_default.status_code == 409
    assert into_default.json()["detail"] == DEFAULT_HOTWORDS_MANAGED

    out_of_default = _move(client, default_id, None, [global_id])
    assert out_of_default.status_code == 409
    assert out_of_default.json()["detail"] == DEFAULT_HOTWORDS_MANAGED

    assert _project_words(client, project_id) == {"词甲": None}
    assert _global_words(client) == {"全局词": None}


def test_move_with_unknown_project_is_404(client):
    project_id = _create_project(client, "普通项目")
    entry_id = _add_project(client, project_id, "词甲")

    unknown_target = _move(client, project_id, "not-a-project", [entry_id])
    assert unknown_target.status_code == 404
    assert unknown_target.json()["detail"] == "项目不存在"

    unknown_source = _move(client, "not-a-project", project_id, [entry_id])
    assert unknown_source.status_code == 404
    assert unknown_source.json()["detail"] == "项目不存在"


def test_move_rejects_empty_or_oversized_id_lists(client):
    project_id = _create_project(client, "目标项目")

    assert _move(client, None, project_id, []).status_code == 422
    assert _move(
        client, None, project_id, [f"id-{index}" for index in range(201)]
    ).status_code == 422
