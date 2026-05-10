"""
IndiaRecs Scraper
- Keyword + review-intent filter
- Username tracking for per-user voting
- 75/25 weighted score formula
- Score recomputation runs at end of every scrape
- Strips r/ prefix from subreddit names
- Real product images fetched via Google Custom Search API
"""

import os
import re
import json
import time
import requests
from apify_client import ApifyClient
from supabase import create_client
import google.generativeai as genai

APIFY_TOKEN = os.environ["APIFY_TOKEN"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GOOGLE_API_KEY = os.environ["GOOGLE_API_KEY"]
GOOGLE_CX = os.environ.get("GOOGLE_CX", "a3b61758d16584b37")

SUBREDDITS = [
    "https://www.reddit.com/r/IndianSkincareAddicts/",
    "https://www.reddit.com/r/indianbeautyhauls/",
    "https://www.reddit.com/r/skincareaddictsindia/",
]

MAX_ITEMS = 30
MAX_POSTS_PER_SUB = 8
MAX_COMMENTS = 10

GENERIC_TERMS = {
    "moisturizer", "moisturiser", "cleanser", "sunscreen",
    "serum", "toner", "facewash", "face wash", "cream",
    "lotion", "scrub", "mask", "exfoliant", "retinol",
    "vitamin c", "niacinamide", "salicylic acid", "spf",
    "sunblock", "spot treatment",
}

VALID_CATEGORIES = {"cleanser", "moisturiser", "sunscreen", "serum", "toner", "other"}

apify = ApifyClient(APIFY_TOKEN)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
genai.configure(api_key=GEMINI_API_KEY)
gemini = genai.GenerativeModel("gemini-2.5-flash-lite")


def is_genuine_review(text):
    """Strict filter — must mention skincare AND show review intent."""
    if not text or len(text.split()) < 20:
        return False
    if "AutoModerator" in text or "[deleted]" in text or "[removed]" in text:
        return False
    text_lower = text.lower()

    skincare_keywords = [
        "moisturiz", "moisturis", "serum", "sunscreen", "spf",
        "cleanser", "face wash", "facewash", "toner", "exfoliat",
        "retinol", "niacinamide", "vitamin c", "salicylic", "hyaluronic",
        "acne", "pimple", "breakout", "pigment", "ceramide",
        "peptide", "skincare", "skin care",
    ]
    if not any(k in text_lower for k in skincare_keywords):
        return False

    review_signals = [
        "i use", "i used", "i've used", "ive used", "been using",
        "i tried", "i've tried", "ive tried", "my skin", "for me",
        "works for me", "worked for me", "doesn't work", "did not work",
        "broke me out", "cleared my", "helped my", "love this",
        "hate this", "would recommend", "highly recommend",
        "holy grail", "after using", "since using", "changed my",
        "honest review", "ditched", "switched to", "swear by",
        "game changer", "best i've used", "obsessed with", "the best",
        "wouldn't recommend", "regret", "worth it", "love it",
        "hate it", "made my skin", "tried this", "currently using",
    ]
    return any(s in text_lower for s in review_signals)


def extract_products_with_gemini(text):
    prompt = f"""Analyze this Reddit comment about skincare. Extract any specific BRANDED products mentioned and the user's sentiment about each.

Comment: {text}

STRICT RULES:
- Only extract specific branded products (e.g., "Minimalist Niacinamide 10%", "Cetaphil Gentle Cleanser", "Cosrx Snail Mucin")
- Brand alone is OK only if category is clear from context (e.g., "Cetaphil cleanser")
- DO NOT extract generic terms ("moisturizer", "sunscreen", "vitamin c") without a brand
- DO NOT extract products mentioned only in questions
- DO NOT extract products the user has NOT personally used
- USE PROPER CAPITALIZATION: "The Ordinary Salicylic Acid 2%", "Joy pH 5.5 Cleanser", "Cetaphil Gentle Cleanser"
- DO NOT return all-lowercase product names
- Be conservative — when in doubt, leave it out

Return JSON exactly:
{{
  "products": [
    {{
      "name": "Full product name with brand (proper capitalization)",
      "brand": "Brand name only (proper capitalization)",
      "category": "cleanser" or "moisturiser" or "sunscreen" or "serum" or "toner" or "other",
      "sentiment": "positive" or "negative" or "neutral"
    }}
  ]
}}

If no specific branded products are mentioned: {{"products": []}}

Respond with ONLY valid JSON. No markdown, no other text."""
    try:
        response = gemini.generate_content(prompt)
        time.sleep(5)
        clean = response.text.strip()
        clean = re.sub(r"^```(?:json)?", "", clean).strip()
        clean = re.sub(r"```$", "", clean).strip()
        result = json.loads(clean)
        # Safety net: title-case any product names that came back all-lowercase
        if result and "products" in result:
            for p in result["products"]:
                if p.get("name") and p["name"] == p["name"].lower():
                    p["name"] = p["name"].title()
                if p.get("brand") and p["brand"] == p["brand"].lower():
                    p["brand"] = p["brand"].title()
        return result
    except Exception as e:
        print(f"  Gemini error: {e}")
        return None


def is_valid_product(extracted):
    name = (extracted.get("name") or "").strip()
    brand = (extracted.get("brand") or "").strip()
    category = (extracted.get("category") or "").strip().lower()
    if not name or len(name) < 5:
        return False
    if not brand or len(brand) < 3:
        return False
    if name.lower() in GENERIC_TERMS or brand.lower() in GENERIC_TERMS:
        return False
    if category not in VALID_CATEGORIES:
        return False
    return True

def generate_product_image(product_name, brand, category):
    """
    Fetch a real product image via Google Custom Search API.
    Tries multiple query strategies, prefers retailer images, validates results.
    """
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
            response = requests.get(url, params=params, timeout=10)
            data = response.json()

            if "items" not in data or len(data["items"]) == 0:
                continue

            best_url = None
            for item in data["items"]:
                img_url = item.get("link", "")
                if not _is_valid_image_url(img_url):
                    continue
                display_link = item.get("displayLink", "").lower()
                if any(domain in display_link for domain in preferred_domains):
                    best_url = img_url
                    break
                if not best_url:
                    best_url = img_url

            if best_url:
                try:
                    head = requests.head(best_url, timeout=5, allow_redirects=True)
                    content_type = head.headers.get("content-type", "")
                    if head.status_code == 200 and "image" in content_type:
                        return best_url
                except Exception:
                    return best_url

        except Exception as e:
            print(f"  Image query failed ({query[:40]}...): {e}")
            continue

    return None


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



def find_or_create_product(extracted, existing_products):
    name_lower = extracted["name"].lower()
    brand_lower = extracted["brand"].lower()
    category = extracted["category"]

    for p in existing_products:
        if p["name"].lower() == name_lower:
            return p, False

    for p in existing_products:
        if (p.get("brand") or "").lower() == brand_lower and \
           (p.get("product_category") or "") == category:
            return p, False

    new_data = {
        "name": extracted["name"],
        "category": "skincare",
        "brand": extracted["brand"],
        "product_category": category,
        "mention_count": 0,
        "positive_count": 0,
        "negative_count": 0,
        "score": 0,
        "skin_type": "all",
        "price_inr": 0,
        "image_url": None,
    }
    try:
        result = supabase.table("products").insert(new_data).execute()
        new_data["id"] = result.data[0]["id"]
        existing_products.append(new_data)
        return new_data, True
    except Exception as e:
        print(f"  Insert failed: {e}")
        return None, False


def save_mention(product, comment_text, sentiment, subreddit, username):
    """Just inserts into mentions table — score recompute happens later in finalize_all_scores()."""
    try:
        supabase.table("mentions").insert({
            "product_name": product["name"],
            "comment_text": comment_text[:1000],
            "sentiment": sentiment,
            "subreddit": subreddit,
            "username": username,
        }).execute()
        return True
    except Exception as e:
        print(f"  Save failed: {e}")
        return False


def finalize_all_scores():
    """
    Recompute every product's score using:
    - Per-user voting (1 user = 1 vote per product, based on their dominant sentiment)
    - 75/25 weighted formula: 0.75 * normalized_positive_users + 0.25 * positive_ratio
    """
    print("\n  Recomputing scores (per-user voting + 75/25 weighted formula)...")

    mentions_data = supabase.table("mentions").select(
        "product_name, username, sentiment"
    ).execute().data

    by_product = {}
    for m in mentions_data:
        pn = m.get("product_name")
        if not pn:
            continue
        user = m.get("username") or "anonymous"
        sentiment = m.get("sentiment") or "neutral"
        by_product.setdefault(pn, {}).setdefault(
            user, {"positive": 0, "negative": 0, "neutral": 0}
        )
        by_product[pn][user][sentiment] = by_product[pn][user].get(sentiment, 0) + 1

    product_stats = {}
    for pn, users in by_product.items():
        pos = neg = neu = 0
        total_mentions = 0
        for user, counts in users.items():
            total_mentions += counts["positive"] + counts["negative"] + counts["neutral"]
            dominant = max(counts, key=counts.get)
            if dominant == "positive":
                pos += 1
            elif dominant == "negative":
                neg += 1
            else:
                neu += 1
        product_stats[pn] = {
            "positive_users": pos,
            "negative_users": neg,
            "neutral_users": neu,
            "total_mentions": total_mentions,
        }

    max_positive = max(
        (s["positive_users"] for s in product_stats.values()),
        default=1
    ) or 1

    products = supabase.table("products").select("id, name").execute().data
    updated = 0
    for product in products:
        pn = product["name"]
        if pn not in product_stats:
            supabase.table("products").update({
                "mention_count": 0,
                "positive_count": 0,
                "negative_count": 0,
                "score": 0,
            }).eq("id", product["id"]).execute()
            continue

        s = product_stats[pn]
        pos = s["positive_users"]
        neg = s["negative_users"]
        denom = pos + neg

        if pos + neg + s["neutral_users"] == 0:
            score = 0.0
        else:
            norm_positive = pos / max_positive
            pos_ratio = pos / denom if denom > 0 else 0
            score = round((0.75 * norm_positive + 0.25 * pos_ratio) * 100, 2)

        supabase.table("products").update({
            "mention_count": s["total_mentions"],
            "positive_count": pos,
            "negative_count": neg,
            "score": score,
        }).eq("id", product["id"]).execute()
        updated += 1

    print(f"  Recomputed scores for {updated} products (max_positive={max_positive})")


def main():
    print("=" * 60)
    print("IndiaRecs Scraper - Path G Edition v2 + Image Fetch")
    print("=" * 60)

    print("\n[1/4] Loading existing products...")
    existing_products = supabase.table("products").select("*").execute().data
    print(f"  {len(existing_products)} products in DB")

    print("\n[2/4] Starting Apify Reddit scraper...")
    run_input = {
        "startUrls": [{"url": url} for url in SUBREDDITS],
        "skipComments": False,
        "skipUserPosts": False,
        "skipCommunity": False,
        "maxItems": MAX_ITEMS,
        "maxPostCount": MAX_POSTS_PER_SUB,
        "maxComments": MAX_COMMENTS,
        "maxCommunitiesCount": 1,
        "maxUserCount": 0,
        "scrollTimeout": 40,
    }
    run = apify.actor("trudax/reddit-scraper-lite").call(run_input=run_input)
    print(f"  Apify run done: {run['id']}")
    print(f"  Cost: ${run.get('usageTotalUsd', 0):.3f}")

    print("\n[3/4] Processing items...")
    items = list(apify.dataset(run["defaultDatasetId"]).iterate_items())
    print(f"  Got {len(items)} items")

    saved = 0
    new_products = 0
    images_generated = 0
    skip_filter = 0
    skip_no_extract = 0
    skip_invalid = 0

    for item in items:
        if item.get("dataType") not in ("post", "comment"):
            continue
        text = item.get("body", "") or ""
        if item.get("dataType") == "post":
            text = (item.get("title", "") or "") + " " + text

        if not is_genuine_review(text):
            skip_filter += 1
            continue

        username = item.get("username") or item.get("author") or "anonymous"
        subreddit = item.get("communityName", "unknown") or "unknown"
        # Strip r/ prefix if Apify includes it (fixes r/r/ display bug)
        if subreddit.startswith("r/"):
            subreddit = subreddit[2:]

        result = extract_products_with_gemini(text)
        if not result or not result.get("products"):
            skip_no_extract += 1
            continue

        for extracted in result["products"]:
            if not is_valid_product(extracted):
                skip_invalid += 1
                continue

            product, is_new = find_or_create_product(extracted, existing_products)
            if not product:
                continue
            if is_new:
                new_products += 1
                print(f"  + New product: {product['name']}")

            sentiment = extracted.get("sentiment", "neutral")
            if sentiment not in ("positive", "negative", "neutral"):
                sentiment = "neutral"

            if save_mention(product, text, sentiment, subreddit, username):
                saved += 1

                # Fetch real image on first mention if not exists
                if is_new and not product.get("image_url"):
                    img_url = generate_product_image(
                        product["name"],
                        product["brand"],
                        product["product_category"]
                    )
                    if img_url:
                        supabase.table("products").update({
                            "image_url": img_url
                        }).eq("id", product["id"]).execute()
                        images_generated += 1
                        print(f"      🖼️ Image fetched: {img_url[:50]}...")

                print(f"    {sentiment} → {product['name']} (by u/{username})")

    print("\n[4/4] Done with scrape, finalizing scores...")
    try:
        finalize_all_scores()
    except Exception as e:
        print(f"  Score finalize failed: {e}")

    print("=" * 60)
    print(f"  New products discovered: {new_products}")
    print(f"  Images fetched:          {images_generated}")
    print(f"  Mentions saved:          {saved}")
    print(f"  Skipped (filter):        {skip_filter}")
    print(f"  Skipped (no products):   {skip_no_extract}")
    print(f"  Skipped (invalid):       {skip_invalid}")
    print("=" * 60)


if __name__ == "__main__":
    main()
