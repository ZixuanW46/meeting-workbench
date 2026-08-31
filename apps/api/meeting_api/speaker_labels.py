"""说话人确认卡与逐字稿共用的公开标签。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from meeting_api.models import Person, SpeakerCluster


def review_ordered_clusters(
    session: Session, meeting_id: str
) -> list[SpeakerCluster]:
    """按确认卡顺序返回说话人簇：发言时长倒序，同长时按内部 id 稳定排序。"""
    return list(
        session.scalars(
            select(SpeakerCluster)
            .where(SpeakerCluster.meeting_id == meeting_id)
            .order_by(SpeakerCluster.total_seconds.desc(), SpeakerCluster.cluster_id)
        )
    )


def public_speaker_labels(session: Session, meeting_id: str) -> dict[str, str]:
    """生成公开说话人标签；匿名编号与确认卡的 1-based 顺序完全一致。"""
    clusters = review_ordered_clusters(session, meeting_id)
    person_ids = {cluster.person_id for cluster in clusters if cluster.person_id}
    people = (
        {
            person.id: person.display_name
            for person in session.scalars(select(Person).where(Person.id.in_(person_ids)))
        }
        if person_ids
        else {}
    )
    return {
        cluster.cluster_id: people.get(cluster.person_id) or f"说话人 {index}"
        for index, cluster in enumerate(clusters, start=1)
    }
