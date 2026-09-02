from __future__ import annotations

from fastapi.testclient import TestClient

from meeting_api import worker as worker_module
from meeting_api.config import Settings
from meeting_api.db import init_db, make_engine, make_session_factory
from meeting_api.main import create_app
from meeting_api.models import Meeting
from meeting_domain import MeetingState


def test_startup_requeues_interrupted_processing_meeting(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path}/recovery.sqlite3"
    engine = make_engine(database_url)
    init_db(engine)
    session_factory = make_session_factory(engine)
    with session_factory() as session:
        session.add(
            Meeting(
                id="interrupted-meeting",
                title="中断的会议",
                state=MeetingState.PROCESSING.value,
                processing_step="ASR",
            )
        )
        session.commit()
    engine.dispose()

    transitions: list[tuple[MeetingState, MeetingState]] = []
    real_transition = worker_module.transition

    def recording_transition(current: MeetingState, target: MeetingState) -> MeetingState:
        transitions.append((current, target))
        return real_transition(current, target)

    monkeypatch.setattr(worker_module, "transition", recording_transition)
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=database_url,
        worker_disabled=True,
        minutes_backend="fake",
    )

    with TestClient(create_app(settings)) as client:
        assert client.get("/healthz").status_code == 200
        with client.app.state.session_factory() as session:
            recovered = session.get(Meeting, "interrupted-meeting")
            assert recovered is not None
            # 音频还在盘上，重启后自动重跑，用户无感；不再打成死胡同 FAILED。
            assert recovered.state == MeetingState.QUEUED.value
            assert recovered.processing_step is None
            assert recovered.processing_error is None

    assert (MeetingState.PROCESSING, MeetingState.QUEUED) in transitions
