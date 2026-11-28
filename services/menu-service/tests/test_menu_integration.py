import json
import time
from io import BytesIO
from uuid import uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from PIL import Image

pytestmark = pytest.mark.integration


def headers(private: bytes, role: str = "ADMIN") -> dict[str, str]:
    now = int(time.time())
    token = jwt.encode(
        {
            "sub": str(uuid4()),
            "jti": str(uuid4()),
            "role": role,
            "token_use": "access",
            "iat": now,
            "nbf": now,
            "exp": now + 900,
            "iss": "mai-food-users",
            "aud": "mai-food-api",
        },
        private,
        algorithm="RS256",
        headers={"kid": "local-v1"},
    )
    return {"Authorization": "Bearer " + token}


def test_admin_crud_availability_filters_and_foreign_keys(
    integration_client: TestClient, auth_keys: tuple[bytes, bytes]
) -> None:
    client = integration_client
    auth = headers(auth_keys[0])
    category = client.post("/categories", headers=auth, json={"name": "Обед", "sort_order": 1})
    assert category.status_code == 201, category.text
    category_id = category.json()["id"]
    assert client.get("/categories").json()[0]["name"] == "Обед"
    body = {"category_id": category_id, "name": "Суп", "price": 12000}
    created = client.post("/items", headers=auth, json=body)
    assert created.status_code == 201, created.text
    item_id = created.json()["id"]
    assert client.get("/items", params={"category_id": category_id}).json()["total"] == 1
    assert client.get(f"/items/{item_id}").json()["price"] == 12000
    assert client.delete(f"/categories/{category_id}", headers=auth).status_code == 409
    hidden = client.put(f"/items/{item_id}", headers=auth, json={**body, "is_available": False})
    assert hidden.status_code == 200
    assert client.get("/items").json()["total"] == 0
    assert client.get(f"/items/{item_id}").status_code == 404
    assert client.get("/admin/items", headers=auth).json()["total"] == 1
    assert (
        client.put(f"/categories/{category_id}", headers=auth, json={"name": "Горячее"}).status_code
        == 200
    )
    assert (
        client.post("/items", headers=auth, json={**body, "category_id": str(uuid4())}).status_code
        == 409
    )
    assert client.delete(f"/items/{item_id}", headers=auth).status_code == 204
    assert client.delete(f"/categories/{category_id}", headers=auth).status_code == 204
    assert client.get("/categories").json() == []


@pytest.mark.parametrize("role", ["CLIENT", "COOK", "CASHIER"])
def test_non_admin_roles_cannot_mutate(
    integration_client: TestClient, auth_keys: tuple[bytes, bytes], role: str
) -> None:
    auth = headers(auth_keys[0], role)
    item_id = str(uuid4())
    for method, path, body in [
        ("post", "/categories", {"name": "X"}),
        ("put", f"/categories/{item_id}", {"name": "X"}),
        ("delete", f"/categories/{item_id}", None),
        ("post", "/items", {"category_id": item_id, "name": "X", "price": 1}),
        ("put", f"/items/{item_id}", {"category_id": item_id, "name": "X", "price": 1}),
        ("delete", f"/items/{item_id}", None),
        ("get", "/admin/items", None),
    ]:
        response = integration_client.request(method, path, headers=auth, json=body)
        assert response.status_code == 403, response.text


@pytest.mark.parametrize(
    "changes",
    [
        {"price": -1},
        {"price": 12.5},
        {"price": True},
        {"name": " "},
        {"image_url": "javascript:alert(1)"},
        {"is_available": "yes"},
        {"price": 2**31},
        {"unexpected": "field"},
    ],
)
def test_bad_item_input_rejected(
    integration_client: TestClient, auth_keys: tuple[bytes, bytes], changes: dict[str, object]
) -> None:
    body = {"category_id": str(uuid4()), "name": "Soup", "price": 100, **changes}
    assert (
        integration_client.post("/items", headers=headers(auth_keys[0]), json=body).status_code
        == 422
    )


def test_pagination_and_unknown_item(
    integration_client: TestClient, auth_keys: tuple[bytes, bytes]
) -> None:
    client = integration_client
    auth = headers(auth_keys[0])
    category_id = client.post("/categories", headers=auth, json={"name": "Lunch"}).json()["id"]
    for name in ["A", "B", "C"]:
        assert (
            client.post(
                "/items", headers=auth, json={"category_id": category_id, "name": name, "price": 0}
            ).status_code
            == 201
        )
    page = client.get("/items", params={"limit": 1, "offset": 1}).json()
    assert page["total"] == 3 and page["items"][0]["name"] == "B"
    assert client.get("/items", params={"limit": 101}).status_code == 422
    assert client.get("/items", params={"offset": -1}).status_code == 422
    assert client.get(f"/items/{uuid4()}").status_code == 404


def test_batch_snapshot_available_only(integration_client, auth_keys):
    client = integration_client
    admin = headers(auth_keys[0])
    category = client.post("/categories", headers=admin, json={"name": "Snapshot"}).json()["id"]
    item = client.post(
        "/items", headers=admin, json={"category_id": category, "name": "Soup", "price": 100}
    ).json()
    result = client.post("/item-snapshots", json={"item_ids": [item["id"]]})
    assert result.status_code == 200 and result.json()["items"][0]["price"] == 100
    assert (
        client.post("/item-snapshots", json={"item_ids": [item["id"], item["id"]]}).status_code
        == 422
    )
    assert client.post("/item-snapshots", json={"item_ids": [str(uuid4())]}).status_code == 409
    client.put(
        f"/items/{item['id']}",
        headers=admin,
        json={
            **{
                k: v
                for k, v in item.items()
                if k in {"name", "category_id", "description", "price", "image_url", "is_available"}
            },
            "is_available": False,
        },
    )
    assert client.post("/item-snapshots", json={"item_ids": [item["id"]]}).status_code == 409


def test_file_upload_publishes_two_independent_photos(integration_client, auth_keys):
    client = integration_client
    admin = headers(auth_keys[0])
    category_id = client.post("/categories", headers=admin, json={"name": "Lunch"}).json()["id"]
    fields = {"item_json": json.dumps({"category_id": category_id, "name": "Soup", "price": 15000})}

    def file(color):
        output = BytesIO()
        Image.new("RGB", (16, 32), color).save(output, "PNG")
        return ("test.png", output.getvalue(), "image/png")

    both = {"menu_photo": file("red"), "detail_photo": file("green")}
    path = "/admin/items/upload"
    assert client.post(path, data=fields, files=both).status_code == 401
    cashier = headers(auth_keys[0], "CASHIER")
    assert client.post(path, headers=cashier, data=fields, files=both).status_code == 403
    rejected = client.post(
        path,
        headers=admin,
        data=fields,
        files={**both, "detail_photo": ("pretend.png", b"<svg/>", "image/png")},
    )
    assert rejected.status_code == 422
    assert client.get("/items").json()["items"] == []

    created = client.post(path, headers=admin, data=fields, files=both)
    assert created.status_code == 201, created.text
    dish = created.json()
    item_id = dish["id"]
    assert client.get(f"/items/{item_id}").json() == dish

    def read_photo(url):
        response = client.get(url.removeprefix("/api/v1/menu"))
        assert response.status_code == 200, response.text
        assert response.headers["content-type"] == "image/webp"
        assert response.headers["x-content-type-options"] == "nosniff"
        return response.content

    assert read_photo(dish["menu_image_url"]) != read_photo(dish["detail_image_url"])
    edit_path = f"/admin/items/{item_id}/upload"
    replacement = client.put(
        edit_path, headers=admin, data=fields, files={"detail_photo": file("blue")}
    )
    assert replacement.status_code == 200, replacement.text
    updated = replacement.json()
    assert updated["menu_image_url"] == dish["menu_image_url"]
    assert updated["detail_image_url"] != dish["detail_image_url"]
    old_detail = dish["detail_image_url"].removeprefix("/api/v1/menu")
    assert client.get(old_detail).status_code == 404
    assert client.delete(f"/items/{item_id}", headers=admin).status_code == 204
    assert client.get(dish["menu_image_url"].removeprefix("/api/v1/menu")).status_code == 404


def test_upload_edit_preserves_legacy_url(integration_client, auth_keys):
    client = integration_client
    admin = headers(auth_keys[0])
    category_id = client.post("/categories", headers=admin, json={"name": "Lunch"}).json()["id"]
    fields = {"category_id": category_id, "name": "Soup", "price": 100}
    photo = "https://example.test/legacy.jpg"
    previous = client.post("/items", headers=admin, json={**fields, "image_url": photo}).json()
    updated = client.put(
        f"/admin/items/{previous['id']}/upload",
        headers=admin,
        data={"item_json": json.dumps({**fields, "price": 125})},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["image_url"] == photo
    assert updated.json()["price"] == 125
    assert updated.json()["detail_image_url"] is None


def test_zero_stock_stays_published_and_empty_categories_are_counted(
    integration_client, auth_keys, monkeypatch
):
    client = integration_client
    admin = headers(auth_keys[0])
    category = client.post("/categories", headers=admin, json={"name": "Lunch"}).json()["id"]
    assert client.get("/categories").json()[0]["published_item_count"] == 0
    dish = client.post(
        "/items", headers=admin, json={"category_id": category, "name": "Soup", "price": 105}
    ).json()

    async def sold_out(ids):
        return {item_id: 0 for item_id in ids}

    monkeypatch.setattr(client.app.state.stock, "remaining", sold_out)
    assert client.get("/categories").json()[0]["published_item_count"] == 1
    page = client.get("/items").json()
    assert page["total"] == 1 and page["items"][0]["remaining_quantity"] == 0
    assert client.get(f"/items/{dish['id']}").json()["remaining_quantity"] == 0
