"""热词中间层的取词与注解合并：默认项目叠加所有项目，普通项目只看自己。"""

from __future__ import annotations

from sqlalchemy import select

from meeting_api.hotword_layers import merged_hotword_notes, project_hotword_words
from meeting_api.models import Project


def _default_project_id(client) -> str:
    with client.app.state.session_factory() as session:
        return session.scalars(
            select(Project.id).where(Project.is_default.is_(True))
        ).one()


def _create_project(client, name: str) -> str:
    response = client.post("/api/projects", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _add_project_hotword(client, project_id: str, word: str, note: str | None = None) -> None:
    response = client.post(
        f"/api/projects/{project_id}/hotwords", json={"word": word, "note": note}
    )
    assert response.status_code == 201, response.text


def _add_global_hotword(client, word: str, note: str | None = None) -> None:
    response = client.post("/api/hotwords", json={"word": word, "note": note})
    assert response.status_code == 201, response.text


# --- 取词 --------------------------------------------------------------------


def test_project_hotword_words_of_default_project_is_the_union(client):
    default_id = _default_project_id(client)
    first = _create_project(client, "项目一")
    second = _create_project(client, "项目二")
    _add_project_hotword(client, first, "共同词")
    _add_project_hotword(client, first, "一的词")
    _add_project_hotword(client, second, "共同词")
    _add_project_hotword(client, second, "二的词")

    with client.app.state.session_factory() as session:
        words = project_hotword_words(session, default_id)

    assert words == sorted({"共同词", "一的词", "二的词"})


def test_project_hotword_words_of_ordinary_project_is_unchanged(client):
    first = _create_project(client, "项目一")
    second = _create_project(client, "项目二")
    _add_project_hotword(client, first, "一的词")
    _add_project_hotword(client, second, "二的词")

    with client.app.state.session_factory() as session:
        assert project_hotword_words(session, first) == ["一的词"]
        # 防御：没有项目仍然是空列表。
        assert project_hotword_words(session, None) == []


# --- 注解合并 ----------------------------------------------------------------


def test_merged_notes_of_default_project_prefer_earlier_project(client):
    default_id = _default_project_id(client)
    first = _create_project(client, "项目一")
    second = _create_project(client, "项目二")
    _add_global_hotword(client, "全局词", "全局注解")
    _add_global_hotword(client, "共同词", "全局的说法")
    _add_global_hotword(client, "只被提及的词", "全局注解要保留")
    # 项目一只写了词没写注解：不占坑，后面的项目还能给注解。
    _add_project_hotword(client, first, "共同词")
    _add_project_hotword(client, first, "只被提及的词")
    _add_project_hotword(client, first, "两个项目词")
    _add_project_hotword(client, first, "一的词", "一的注解")
    _add_project_hotword(client, second, "共同词", "二的说法")
    _add_project_hotword(client, second, "两个项目词", "二给的注解")
    # 项目一已经写过注解，排在后面的项目二说了不算。
    _add_project_hotword(client, second, "一的词", "二想改的注解")

    with client.app.state.session_factory() as session:
        merged = dict(merged_hotword_notes(session, default_id))
        words = [word for word, _ in merged_hotword_notes(session, default_id)]

    assert words == sorted(merged)
    assert merged == {
        "全局词": "全局注解",
        "共同词": "二的说法",
        "只被提及的词": "全局注解要保留",
        "两个项目词": "二给的注解",
        "一的词": "一的注解",
    }


def test_merged_notes_of_ordinary_project_are_unchanged(client):
    first = _create_project(client, "项目一")
    second = _create_project(client, "项目二")
    _add_global_hotword(client, "共同词", "全局的说法")
    _add_project_hotword(client, first, "共同词", "一的说法")
    _add_project_hotword(client, second, "二的词", "二的注解")

    with client.app.state.session_factory() as session:
        merged = dict(merged_hotword_notes(session, first))

    # 只叠自己那一层：项目二的词不进来。
    assert merged == {"共同词": "一的说法"}
