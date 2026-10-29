"""The demo resource: pagination, validation and cache invalidation."""
from __future__ import annotations


def _create(client, headers, name="Widget", **extra):
    return client.post("/api/items", headers=headers, json={"name": name, **extra})


def test_pagination_shape(client, auth_headers):
    for index in range(5):
        _create(client, auth_headers, f"Item {index}")
    body = client.get("/api/items?per_page=2", headers=auth_headers).get_json()
    assert body["total"] == 5
    assert body["pages"] == 3
    assert len(body["items"]) == 2


def test_per_page_is_clamped(client, auth_headers):
    body = client.get("/api/items?per_page=100000", headers=auth_headers).get_json()
    assert body["per_page"] == 200


def test_missing_name_is_a_400_not_a_500(client, auth_headers):
    response = _create(client, auth_headers, name="   ")
    assert response.status_code == 400
    assert "name" in response.get_json()["error"].lower()


def test_search_escapes_wildcards(client, auth_headers):
    _create(client, auth_headers, "100% cotton")
    _create(client, auth_headers, "Something else")
    body = client.get("/api/items?q=100%25", headers=auth_headers).get_json()
    assert [item["name"] for item in body["items"]] == ["100% cotton"]


def test_summary_reflects_writes(client, auth_headers):
    _create(client, auth_headers, "First")
    before = client.get("/api/items/summary", headers=auth_headers).get_json()
    _create(client, auth_headers, "Second")
    after = client.get("/api/items/summary", headers=auth_headers).get_json()
    # The write invalidates the cached summary, so the count moves immediately.
    assert after["total"] == before["total"] + 1


def test_unknown_item_is_404_json(client, auth_headers):
    response = client.get("/api/items/999999", headers=auth_headers)
    assert response.status_code == 404
    assert response.get_json()["error"] == "Item not found"


def test_api_errors_are_json_not_html(client):
    response = client.get("/api/nope")
    assert response.status_code == 404
    assert response.is_json
    assert "request_id" in response.get_json()
