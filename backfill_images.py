"""
Backfill Images — One-time script to fetch product images for existing products.
Run manually via GitHub Actions.
"""

import os
import time
import requests
from supabase import create_client

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
GOOGLE_API_KEY = os.environ["GOOGLE_API_KEY"]
GOOGLE_CX = "a3b61758d16584b37"

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


def _is_valid_image_url(url):
    """Check that a URL looks like it points to a real product image."""
    if not url or len(url) > 500:
        return False
    if not url.startswith("https://"):
        return False
    reject_patterns = ["avatar", "icon", "logo", "pixel", "tracking", "1x1", "spacer"]
    url_lower = url.lower()
    if any(p in url_lower for p in reject_patterns):
        return False
    return True


def fetch_image(product_name, brand, category):
    """Try multiple queries to find a real product image."""
    queries = [
        f'"{brand}" "{product_name}" product',
        f'{product_name} {brand} site:amazon.in OR site:nykaa.com',
        f'{product_name} {brand} product image',
        f'{brand} {category} skincare product',
    ]
    url = "https://www.googleapis.com/customsearch/v1"
    preferred_domains = ["amazon", "nykaa", "flipkart", "1mg", "purplle"]

    for query in queries:
        try:
            params = {
                "key": GOOGLE_API_KEY,
                "cx": GOOGLE_CX,
                "q": query,
                "searchType": "image",
                "num": 3,
                "imgSize": "MEDIUM",
                "imgType": "photo",
                "safe": "active",
            }
            resp = requests.get(url, params=params, timeout=10)
            data = resp.json()

            if "items" not in data:
                continue

            best_url = None
            for item in data["items"]:
                img_url = item.get("link", "")
                if not _is_valid_image_url(img_url):
                    continue
                display_link = item.get("displayLink", "").lower()
                if any(d in display_link for d in preferred_domains):
                    best_url = img_url
                    break
                if not best_url:
                    best_url = img_url

            if best_url:
                try:
                    head = requests.head(best_url, timeout=5, allow_redirects=True)
                    if head.status_code == 200 and "image" in head.headers.get("content-type", ""):
                        return best_url
                except Exception:
                    return best_url

        except Exception as e:
            print(f"  Query failed: {e}")
            continue

    return None


def main():
    print("=" * 50)
    print("Backfill Images — Fetching for existing products")
    print("=" * 50)

    products = supabase.table("products").select("*").execute().data
    missing = [p for p in products if not p.get("image_url")]

    print(f"\nFound {len(missing)} products without images (out of {len(products)} total)")
    print(f"This will use up to {len(missing) * 4} Google CSE queries (free tier = 100/day)")
    print()

    updated = 0
    for i, p in enumerate(missing):
        name = p.get("name", "")
        brand = p.get("brand", "")
        category = p.get("product_category", "")
        print(f"[{i+1}/{len(missing)}] {name}...")

        img_url = fetch_image(name, brand, category)
        if img_url:
            supabase.table("products").update({"image_url": img_url}).eq("id", p["id"]).execute()
            updated += 1
            print(f"  ✓ {img_url[:70]}...")
        else:
            print(f"  ✗ No image found")

        # Respect rate limits (2 sec between products)
        time.sleep(2)

    print(f"\n{'=' * 50}")
    print(f"Done! Updated {updated}/{len(missing)} products with images.")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()
