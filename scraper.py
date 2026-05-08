"""
IndiaRecs Scraper — Apify Edition
Scrapes Reddit via Apify, filters genuine reviews, runs sentiment 
analysis with Gemini, saves results to Supabase.
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
        "after using", "since using",
    ]
    return any(s in text_lower for s in signals)


def find_product_match(text, products):
    text_lower = text.lower()
    for product in products:
        if product["name"].lower() in text_lower:
            return product
        brand = product.get("brand") or ""
        if len(brand) > 3 and brand.lower() in text_lower:
            ptype = product.get("product_category") or ""
            if ptype and ptype in text_lower:
                return product
    return None


def classify_sentiment(text, product_name):
    prompt = f"""Analyze this Reddit comment about a skincare product and respond ONLY with valid JSON.

Product: {product_name}
Comment: {text}

Return JSON with these exact fields:
{{
  "is_review": "yes" or "no",
  "sentiment": "positive", "negative", or "neutral",
  "summary": "one short sentence"
}}

Respond with only the JSON, no other text."""
    try:
        response = gemini.generate_content(prompt)
        clean = response.text.strip()
        clean = re.sub(r"^```(?:json)?", "", clean).strip()
        clean = re.sub(r"```$", "", clean).strip()
        return json.loads(clean)
    except Exception as e:
        print(f"  Gemini error: {e}")
        return None


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

        print(f"  Saved {sentiment} mention for {product['name']}")
        return True
    except Exception as e:
        print(f"  Save failed: {e}")
        return False


def main():
    print("=" * 60)
    print("IndiaRecs Scraper Starting")
    print("=" * 60)

    print("\n[1/4] Loading products from Supabase...")
    products = supabase.table("products").select("*").execute().data
    print(f"  Loaded {len(products)} products")
    if not products:
        print("  No products in database. Add some first.")
        return

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

    print("\n[3/4] Processing scraped items...")
    items = list(apify.dataset(run["defaultDatasetId"]).iterate_items())
    print(f"  Got {len(items)} items")

    saved = 0
    skip_filter = 0
    skip_match = 0
    skip_not_review = 0

    for item in items:
        if item.get("dataType") not in ("post", "comment"):
            continue
        text = item.get("body", "") or ""
        if item.get("dataType") == "post":
            text = (item.get("title", "") or "") + " " + text

        if not is_genuine_review(text):
            skip_filter += 1
            continue

        matched = find_product_match(text, products)
        if not matched:
            skip_match += 1
            continue

        print(f"\n  Match: {matched['name']}")
        print(f"  Preview: {text[:100]}...")

        result = classify_sentiment(text, matched["name"])
        if not result or result.get("is_review") != "yes":
            skip_not_review += 1
            continue

        subreddit = item.get("communityName", "unknown")
        if save_mention(matched, text, result["sentiment"], subreddit):
            saved += 1

    print("\n[4/4] Done!")
    print("=" * 60)
    print(f"  Saved:                {saved}")
    print(f"  Skipped (filter):     {skip_filter}")
    print(f"  Skipped (no match):   {skip_match}")
    print(f"  Skipped (not review): {skip_not_review}")
    print("=" * 60)


if __name__ == "__main__":
    main()
