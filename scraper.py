"""
IndiaRecs Scraper — Auto-Discovery Edition
Scrapes Reddit, uses Gemini to extract products + sentiment in one pass,
auto-creates new products in Supabase. RedditRecs-style.
"""

import os
import re
import json
from apify_client import ApifyClient
from supabase import create_client
import google.generativeai as genai

APIFY_TOKEN = os.environ["APIFY_TOKEN"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

SUBREDDITS = [
    "https://www.reddit.com/r/IndianSkincareAddicts/",
    "https://www.reddit.com/r/SkincareAddiction/",
    "https://www.reddit.com/r/AsianBeauty/",
    "https://www.reddit.com/r/indianbeautyhauls/",
]

MAX_ITEMS = 50
MAX_POSTS_PER_SUB = 10
MAX_COMMENTS = 15

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
gemini = genai.GenerativeModel("gemini-1.5-flash")


def is_genuine_review(text):
    if not text or len(text.split()) < 15:
        return False
    if "AutoModerator" in text or "[deleted]" in text or "[removed]" in text:
        return False
    text_lower = text.lower()
    signals = [
        "i use", "i used", "i've used", "ive used",
        "been using", "i tried", "i've tried",
        "my skin", "for me", "works for me",
        "repurchased", "i love", "i hate",
        "after using", "since using", "highly recommend",
        "love this", "hate this", "this product",
    ]
    return any(s in text_lower for s in signals)


def extract_products_with_gemini(text):
    prompt = f"""Analyze this Reddit comment about skincare. Extract any specific BRANDED products mentioned and the user's sentiment about each.

Comment: {text}

STRICT RULES:
- Only extract specific branded products (e.g., "Minimalist Niacinamide 10%", "Cetaphil Gentle Cleanser", "Cosrx Snail Mucin")
- Brand alone is OK only if category is clear from context (e.g., "Cetaphil cleanser")
- DO NOT extract generic terms ("moisturizer", "sunscreen", "vitamin c") without a brand
- DO NOT extract products mentioned only in questions
- DO NOT extract products the user has NOT personally used
- Be conservative — when in doubt, leave it out

Return JSON exactly:
{{
  "products": [
    {{
      "name": "Full product name with brand",
      "brand": "Brand name only",
      "category": "cleanser" or "moisturiser" or "sunscreen" or "serum" or "toner" or "other",
      "sentiment": "positive" or "negative" or "neutral"
    }}
  ]
}}

If no specific branded products are mentioned: {{"products": []}}

Respond with ONLY valid JSON. No markdown, no other text."""
    try:
        response = gemini.generate_content(prompt)
        clean = response.text.strip()
        clean = re.sub(r"^```(?:json)?", "", clean).strip()
        clean = re.sub(r"```$", "", clean).strip()
        return json.loads(clean)
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
    }
    try:
        result = supabase.table("products").insert(new_data).execute()
        new_data["id"] = result.data[0]["id"]
        existing_products.append(new_data)
        return new_data, True
    except Exception as e:
        print(f"  Insert failed: {e}")
        return None, False


def save_mention(product, comment_text, sentiment, subreddit):
    try:
        supabase.table("mentions").insert({
            "product_name": product["name"],
            "comment_text": comment_text[:1000],
            "sentiment": sentiment,
            "subreddit": subreddit,
        }).execute()

        positive = product.get("positive_count", 0)
        negative = product.get("negative_count", 0)
        mentions = product.get("mention_count", 0) + 1
        if sentiment == "positive":
            positive += 1
        elif sentiment == "negative":
            negative += 1
        score = positive - negative

        supabase.table("products").update({
            "mention_count": mentions,
            "positive_count": positive,
            "negative_count": negative,
            "score": score,
        }).eq("id", product["id"]).execute()

        product["mention_count"] = mentions
        product["positive_count"] = positive
        product["negative_count"] = negative
        product["score"] = score
        return True
    except Exception as e:
        print(f"  Save failed: {e}")
        return False


def main():
    print("=" * 60)
    print("IndiaRecs Scraper - Auto-Discovery Edition")
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

        result = extract_products_with_gemini(text)
        if not result or not result.get("products"):
            skip_no_extract += 1
            continue

        subreddit = item.get("communityName", "unknown")
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

            if save_mention(product, text, sentiment, subreddit):
                saved += 1
                print(f"    {sentiment} → {product['name']}")

    print("\n[4/4] Done!")
    print("=" * 60)
    print(f"  New products discovered: {new_products}")
    print(f"  Mentions saved:          {saved}")
    print(f"  Skipped (filter):        {skip_filter}")
    print(f"  Skipped (no products):   {skip_no_extract}")
    print(f"  Skipped (invalid):       {skip_invalid}")
    print("=" * 60)


if __name__ == "__main__":
    main()
