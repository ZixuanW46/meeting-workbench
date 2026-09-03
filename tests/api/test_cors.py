def _allowed_methods(response) -> set[str]:
    header = response.headers["access-control-allow-methods"]
    return {method.strip() for method in header.split(",")}


def test_cors_preflight_allows_delete(client):
    response = client.options(
        "/api/hotwords/1",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "DELETE",
        },
    )

    assert response.status_code == 200
    assert "DELETE" in _allowed_methods(response)


def test_cors_preflight_allows_patch(client):
    response = client.options(
        "/api/hotwords/1",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "PATCH",
        },
    )

    assert response.status_code == 200
    assert "PATCH" in _allowed_methods(response)
