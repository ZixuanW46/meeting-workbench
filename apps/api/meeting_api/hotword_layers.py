"""热词三层（全局词库 / 项目热词 / 本场热词）的查询辅助。

快照的合并规则本身在 `meeting_domain.hotwords.snapshot`；这里只负责按会议
所属项目把中间那一层取出来，供 worker 开跑与重转写路由共用。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from meeting_api.models import HotwordEntry, ProjectHotword


def global_hotword_words(session: Session) -> list[str]:
    return list(
        session.scalars(
            select(HotwordEntry.word).order_by(HotwordEntry.word, HotwordEntry.id)
        ).all()
    )


def project_hotword_words(session: Session, project_id: str | None) -> list[str]:
    """会议所属项目的热词；无项目就是空列表。"""
    if project_id is None:
        return []
    return list(
        session.scalars(
            select(ProjectHotword.word)
            .where(ProjectHotword.project_id == project_id)
            .order_by(ProjectHotword.word, ProjectHotword.id)
        ).all()
    )


def merged_hotword_notes(
    session: Session, project_id: str | None
) -> list[tuple[str, str | None]]:
    """纪要术语表的 (词, 注解) 列表：全局词库 + 项目热词，同词以项目注解为准。"""
    notes: dict[str, str | None] = {}
    for word, note in session.execute(
        select(HotwordEntry.word, HotwordEntry.note).order_by(
            HotwordEntry.word, HotwordEntry.id
        )
    ):
        notes[word] = note
    if project_id is not None:
        for word, note in session.execute(
            select(ProjectHotword.word, ProjectHotword.note)
            .where(ProjectHotword.project_id == project_id)
            .order_by(ProjectHotword.word, ProjectHotword.id)
        ):
            # 项目里给了注解就覆盖全局的说法；项目只写了词则保留全局注解。
            if note is not None or word not in notes:
                notes[word] = note
    return [(word, notes[word]) for word in sorted(notes)]
