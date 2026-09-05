"""热词三层（全局词库 / 项目热词 / 本场热词）的查询辅助。

快照的合并规则本身在 `meeting_domain.hotwords.snapshot`；这里只负责按会议
所属项目把中间那一层取出来，供 worker 开跑与重转写路由共用。

默认项目是个例外：它不维护自己的热词，中间层取「所有项目热词的并集」。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from meeting_api.models import HotwordEntry, Project, ProjectHotword


def global_hotword_words(session: Session) -> list[str]:
    return list(
        session.scalars(
            select(HotwordEntry.word).order_by(HotwordEntry.word, HotwordEntry.id)
        ).all()
    )


def project_layer_ids(session: Session, project_id: str | None) -> list[str]:
    """中间层实际要叠的项目 id：默认项目叠全部，普通项目只叠自己。

    顺序是项目展示顺序（position, id），注解冲突时靠前的项目说了算。
    """
    if project_id is None:
        return []
    project = session.get(Project, project_id)
    if project is None:
        return []
    if not project.is_default:
        return [project_id]
    return list(
        session.scalars(select(Project.id).order_by(Project.position, Project.id)).all()
    )


def project_hotword_words(session: Session, project_id: str | None) -> list[str]:
    """会议所属项目的热词；无项目就是空列表，默认项目取所有项目的并集。"""
    layer_ids = project_layer_ids(session, project_id)
    if not layer_ids:
        return []
    words = session.scalars(
        select(ProjectHotword.word).where(ProjectHotword.project_id.in_(layer_ids))
    ).all()
    return sorted(set(words))


def merged_hotword_notes(
    session: Session, project_id: str | None
) -> list[tuple[str, str | None]]:
    """纪要术语表的 (词, 注解) 列表：全局词库 + 项目热词，同词以项目注解为准。

    默认项目会依次叠上每个项目：先写了注解的项目说了算，只写词不写注解的
    项目不占坑（全局注解仍然保留，后面的项目还能补注解）。
    """
    notes: dict[str, str | None] = {}
    for word, note in session.execute(
        select(HotwordEntry.word, HotwordEntry.note).order_by(
            HotwordEntry.word, HotwordEntry.id
        )
    ):
        notes[word] = note
    # 已经被某个项目的注解占住的词，后面的项目不再覆盖。
    claimed: set[str] = set()
    for layer_id in project_layer_ids(session, project_id):
        for word, note in session.execute(
            select(ProjectHotword.word, ProjectHotword.note)
            .where(ProjectHotword.project_id == layer_id)
            .order_by(ProjectHotword.word, ProjectHotword.id)
        ):
            if word not in notes:
                notes[word] = note
                if note is not None:
                    claimed.add(word)
            elif note is not None and word not in claimed:
                # 项目里给了注解就覆盖全局的说法；项目只写了词则保留原注解。
                notes[word] = note
                claimed.add(word)
    return [(word, notes[word]) for word in sorted(notes)]
