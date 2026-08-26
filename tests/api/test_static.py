from __future__ import annotations

from fastapi.testclient import TestClient

from meeting_api.config import Settings
from meeting_api.main import create_app


def test_existing_web_dist_is_served_without_shadowing_api_routes(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    index = "<!doctype html><title>M13 静态前端</title>"
    (dist / "index.html").write_text(index, encoding="utf-8")
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{tmp_path}/static.sqlite3",
        static_dir=dist,
        worker_disabled=True,
        minutes_backend="fake",
    )

    with TestClient(create_app(settings)) as client:
        assert client.get("/").text == index
        assert client.get("/index.html").text == index
        assert client.get("/healthz").json() == {"status": "ok"}
        assert client.get("/api/meetings").status_code == 200
