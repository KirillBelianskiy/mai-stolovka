"""Demo provisioning repairs missing photos without replacing operator changes."""

import importlib.util
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("demo_menu", ROOT / "infra/local_demo_menu.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class MenuAPI:
    def __init__(self):
        self.items = []
        self.categories = []
        self.writes = []
        self.offsets = []

    def __call__(self, method, path, body=None, token=None):
        url = urlsplit(path)
        if method == "GET":
            if url.path.endswith("categories"):
                return [dict(row) for row in self.categories]
            offset = int(parse_qs(url.query)["offset"][0])
            self.offsets.append(offset)
            return {
                "items": [dict(row) for row in self.items[offset : offset + 1]],
                "total": len(self.items),
            }
        self.writes.append((method, path, dict(body)))
        rows = self.categories if url.path.endswith("categories") else self.items
        if method == "PUT":
            current = next(row for row in self.items if row["id"] == url.path.split("/")[-1])
            current.update(body)
            return dict(current)
        row = {"id": str(len(rows) + 1), **body}
        rows.append(row)
        return dict(row)


class DemoMenuTests(unittest.TestCase):
    def test_fresh_and_repeated_seed_have_six_photos_without_duplicates(self):
        api = MenuAPI()
        result = module.seed_menu(api, "http://localhost:8180", "synthetic-admin")
        self.assertEqual(len(result), 6)
        self.assertTrue(all(row["image_url"].endswith(".jpg") for row in result))
        writes = len(api.writes)
        module.seed_menu(api, "http://localhost:8180", "synthetic-admin")
        self.assertEqual(len(api.writes), writes)
        self.assertIn(5, api.offsets)

    def test_repairs_missing_photo_preserving_price_availability_and_custom_photo(self):
        api = MenuAPI()
        module.seed_menu(api, "http://localhost:8180", "synthetic-admin")
        api.items[0].update(
            price=17700, description="Operator description", is_available=False, image_url=None
        )
        api.items[1]["image_url"] = "https://example.org/operator.jpg"
        writes = len(api.writes)
        module.seed_menu(api, "http://localhost:8180", "synthetic-admin")
        self.assertEqual(len(api.writes), writes + 1)
        self.assertEqual(api.items[0]["price"], 17700)
        self.assertEqual(api.items[0]["description"], "Operator description")
        self.assertFalse(api.items[0]["is_available"])
        self.assertTrue(api.items[0]["image_url"].endswith("borscht.jpg"))
        self.assertEqual(api.items[1]["image_url"], "https://example.org/operator.jpg")

    def test_all_catalog_images_are_bounded_local_jpegs(self):
        for dish in module.CATALOG:
            with self.subTest(dish=dish["name"]):
                path = ROOT / "apps/telegram-mini-app/public/design/dishes" / dish["image"]
                self.assertEqual(path.read_bytes()[:2], b"\xff\xd8")
                self.assertLess(path.stat().st_size, 200_000)


if __name__ == "__main__":
    unittest.main()
