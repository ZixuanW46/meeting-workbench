from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select

from meeting_api.config import Settings
from meeting_api.db import make_engine, make_session_factory
from meeting_api.models import Meeting, Voiceprint
from meeting_api.pipeline.embedding import embedding_from_bytes
from meeting_api.voiceprints import delete_voiceprint_with_clip
from meeting_domain import TEMPLATE_CAP, cosine_similarity, plan_cap_eviction


@dataclass(frozen=True)
class SimilarTemplate:
    voiceprint_id: str
    similarity: float


def _most_similar(
    target: Voiceprint, others: list[Voiceprint]
) -> SimilarTemplate | None:
    if not others:
        return None
    target_embedding = embedding_from_bytes(target.embedding)
    best = max(
        others,
        key=lambda other: cosine_similarity(
            target_embedding,
            embedding_from_bytes(other.embedding),
        ),
    )
    return SimilarTemplate(
        voiceprint_id=best.id,
        similarity=cosine_similarity(target_embedding, embedding_from_bytes(best.embedding)),
    )


def main() -> int:
    settings = Settings()
    engine = make_engine(settings.resolved_database_url())
    session_factory = make_session_factory(engine)

    with session_factory() as session:
        person_ids = [
            person_id
            for person_id, count in session.execute(
                select(Voiceprint.person_id, func.count())
                .group_by(Voiceprint.person_id)
                .having(func.count() > TEMPLATE_CAP)
            )
        ]
        for person_id in person_ids:
            while True:
                rows = session.execute(
                    select(Voiceprint, Meeting.title)
                    .join(Meeting, Meeting.id == Voiceprint.source_meeting_id, isouter=True)
                    .where(Voiceprint.person_id == person_id)
                    .order_by(
                        Voiceprint.created_at.is_(None).desc(),
                        Voiceprint.created_at,
                        Voiceprint.id,
                    )
                ).all()
                if len(rows) <= TEMPLATE_CAP:
                    break
                voiceprints = [row[0] for row in rows]
                evict_index = plan_cap_eviction(
                    [embedding_from_bytes(voiceprint.embedding) for voiceprint in voiceprints]
                )
                if evict_index is None:
                    break
                evicted, meeting_title = rows[evict_index]
                remaining = [
                    voiceprint
                    for index, voiceprint in enumerate(voiceprints)
                    if index != evict_index
                ]
                similar = _most_similar(evicted, remaining)
                if similar is None:
                    similar_text = "无"
                else:
                    similar_text = f"{similar.voiceprint_id} ({similar.similarity:.6f})"
                print(
                    "删除模板 "
                    f"id={evicted.id} "
                    f"source_meeting_title={meeting_title or '无'} "
                    f"most_similar={similar_text}"
                )
                delete_voiceprint_with_clip(session, evicted, settings.data_dir)
                session.commit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
