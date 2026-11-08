"""Idempotently populate the isolated demonstration through the public Menu API."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = json.loads((ROOT / "infra/demo-menu.json").read_text())
ITEM_FIELDS = ("category_id", "name", "description", "price", "image_url", "is_available")


def seed_menu(request, base: str, admin: str) -> list[dict]:
    for dish in CATALOG:
        path = ROOT / "apps/telegram-mini-app/public/design/dishes" / dish["image"]
        if not path.is_file():
            raise RuntimeError(f"Missing demonstration image: {dish['image']}")

    categories = request("GET", "/api/v1/menu/categories")
    items = []
    offset = 0
    while True:
        page = request("GET", f"/api/v1/menu/admin/items?limit=100&offset={offset}", token=admin)
        items.extend(page["items"])
        offset += len(page["items"])
        if offset >= page["total"]:
            break
        if not page["items"]:
            raise RuntimeError("Menu page ended before the reported total")

    seeded = []
    for index, dish in enumerate(CATALOG):
        category = next((row for row in categories if row["name"] == dish["category"]), None)
        if category is None:
            category = request(
                "POST",
                "/api/v1/menu/categories",
                {"name": dish["category"], "sort_order": index},
                admin,
            )
            categories.append(category)

        image = f"{base}/design/dishes/{dish['image']}"
        item = next((row for row in items if row["name"] == dish["name"]), None)
        if item is None:
            item = request(
                "POST",
                "/api/v1/menu/items",
                {
                    "category_id": category["id"],
                    "name": dish["name"],
                    "description": dish["description"],
                    "price": dish["price"],
                    "image_url": image,
                    "is_available": True,
                },
                admin,
            )
            items.append(item)
        elif item["image_url"] in (None, "", f"{base}/design/food-buckwheat.png"):
            # Repair missing/legacy demo images while retaining operator-edited item fields.
            body = {field: item[field] for field in ITEM_FIELDS}
            body["image_url"] = image
            item = request("PUT", f"/api/v1/menu/items/{item['id']}", body, admin)
        seeded.append(item)
    return seeded
