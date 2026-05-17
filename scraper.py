"""
IndiaRecs Scraper — Path G Edition (v4)
========================================

Changes from v3:
- REPLACED Reddit public JSON (blocked from cloud IPs) with Pullpush.io API
- Pullpush.io = free Reddit archive, no auth, works from GitHub Actions
- Fetches COMMENTS directly with review-focused keyword search (much better hit rate)
- Also fetches posts with selftext for additional coverage
- Fixed google.generativeai deprecation warning → uses google-genai package
- All scoring/Supabase logic unchanged
"""

import os
import re
import json
import time
import requests
from supabase import create_client

# ═══════════════════════════════════════
# GEMINI SETUP — using new google-genai package
# ═══════════════════════════════════════
from google import genai

# ═══════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

# Subreddits to scrape
SUBREDDITS = ["IndianSkincareAddicts", "IndianBeautyDeals", "IndianMakeupAddicts"]

# Pullpush.io settings
PULLPUSH_COMMENT_URL = "https://api.pullpush.io/reddit/search/comment/"
PULLPUSH_POST_URL = "https://api.pullpush.io/reddit/search/submission/"

# How many items to fetch per request (max 100 for Pullpush)
COMMENTS_PER_SUB = 100
POSTS_PER_SUB = 25

# Review-focused search queries — these find comments with actual product opinions
REVIEW_QUERIES = [
    "recommend OR recommended OR holy grail",
    "been using OR currently using OR switched to",
    "love this OR hate this OR broke me out",
    "review OR repurchase OR game changer",
]

# Delay between API requests (seconds)
API_DELAY = 3

GENERIC_TERMS = {
    "moisturizer", "moisturiser", "cleanser", "sunscreen",
    "serum", "toner", "facewash", "face wash", "cream",
    "lotion", "scrub", "mask", "exfoliant", "retinol",
    "vitamin c", "niacinamide", "salicylic acid", "spf",
    "sunblock", "spot treatment",
}

VALID_CATEGORIES = {"cleanser", "moisturiser", "sunscreen", "serum", "toner", "other"}


# ═══════════════════════════════════════
# INIT CLIENTS
# ═══════════════════════════════════════

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# New google-genai client
gemini_client = genai.Client(api_key=GEMINI_API_KEY)
GEMINI_MODEL = "gemini-2.5-flash-lite"


# ═══════════════════════════════════════
# PULLPUSH.IO FETCHER (replaces Reddit JSON)
# ═══════════════════════════════════════

def fetch_comments_pullpush(subreddit, query, size=100):
    """
    Fetch comments from Pullpush.io (Reddit archive API).
    No auth needed, works from any IP including GitHub Actions.
    """
    params = {
        "subreddit": subreddit,
        "q": query,
        "size": size,
        "sort": "desc",
        "sort_type": "created_utc",
    }

    try:
        response = requests.get(PULLPUSH_COMMENT_URL, params=params, timeout=30)

        if response.status_code != 200:
            print(f"    Pullpush comment fetch failed: HTTP {response.status_code}")
            return []

        data = response.json()
        comments = data.get("data", [])

        results = []
        for c in comments:
            author = c.get("author", "anonymous")
            body = c.get("body", "")

            # Skip deleted/removed/automod
            if author in ("[deleted]", "AutoModerator", "[removed]"):
                continue
            if body in ("[deleted]", "[removed]", ""):
                continue

            results.append({
                "dataType": "comment",
                "body": body,
                "author": author,
                "subreddit": subreddit,
            })

        return results

    except requests.exceptions.RequestException as e:
        print(f"    Network error (comments): {e}")
        return []


def fetch_posts_pullpush(subreddit, size=25):
    """
    Fetch recent posts with selftext from Pullpush.io.
    Supplements comment data with post bodies that contain reviews.
    """
    params = {
        "subreddit": subreddit,
        "size": size,
        "sort": "desc",
        "sort_type": "created_utc",
        "selftext:not": "[removed]",  # Skip removed posts
    }

    try:
        response = requests.get(PULLPUSH_POST_URL, params=params, timeout=30)

        if response.status_code != 200:
            print(f"    Pullpush post fetch failed: HTTP {response.status_code}")
            return []

        data = response.json()
        posts = data.get("data", [])

        results = []
        for p in posts:
            author = p.get("author", "anonymous")
            selftext = p.get("selftext", "")
            title = p.get("title", "")

            # Skip removed/deleted
            if author in ("[deleted]", "AutoModerator"):
                continue
            if selftext in ("[deleted]", "[removed]", ""):
                continue

            results.append({
                "dataType": "post",
                "title": title,
                "body": selftext,
                "author": author,
                "subreddit": subreddit,
            })

        return results

    except requests.exceptions.RequestException as e:
        print(f"    Network error (posts): {e}")
        return []


def fetch_all_items():
    """
    Main fetcher — uses Pullpush.io to get review-rich comments + posts.
    Returns list of items for processing.
    """
    all_items = []
    seen_bodies = set()  # Deduplicate across queries

    for subreddit in SUBREDDITS:
        print(f"  Fetching r/{subreddit}...")
        sub_count = 0

        # Fetch comments with review-focused queries
        for query in REVIEW_QUERIES:
            time.sleep(API_DELAY)
            comments = fetch_comments_pullpush(subreddit, query, COMMENTS_PER_SUB)

            for c in comments:
                # Deduplicate by first 100 chars of body
                key = c["body"][:100].lower()
                if key not in seen_bodies:
                    seen_bodies.add(key)
                    all_items.append(c)
                    sub_count += 1

            print(f"    Query '{query[:40]}...' → {len(comments)} raw, {sub_count} unique total")

        # Also fetch recent posts
        time.sleep(API_DELAY)
        posts = fetch_posts_pullpush(subreddit, POSTS_PER_SUB)
        for p in posts:
            key = (p.get("body", "") or "")[:100].lower()
            if key and key not in seen_bodies:
                seen_bodies.add(key)
                all_items.append(p)
                sub_count += 1

        print(f"    + {len(posts)} posts fetched")
        print(f"    Total unique items from r/{subreddit}: {sub_count}")

    return all_items


# ═══════════════════════════════════════
# REVIEW FILTER (unchanged from v3)
# ═══════════════════════════════════════

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


# ═══════════════════════════════════════
# GEMINI EXTRACTION (updated to new SDK)
# ═══════════════════════════════════════

def extract_products_with_gemini(text):
    """
    Send review text to Gemini for product extraction + sentiment analysis.
    Uses the new google-genai SDK.
    """
    prompt = f"""You are a sentiment analysis expert for Indian skincare product reviews on Reddit.

Analyze this comment and extract specific BRANDED products the user has PERSONALLY USED, along with their sentiment.

Comment: {text}

PRODUCT EXTRACTION RULES:
- Only extract products with a clear brand name (e.g., "Minimalist Niacinamide 10%", "Cetaphil Gentle Cleanser")
- Brand alone is OK if category is clear from context (e.g., "Cetaphil cleanser")
- DO NOT extract generic terms without a brand ("moisturizer", "sunscreen", "vitamin c")
- DO NOT extract products only mentioned in questions ("has anyone tried X?")
- DO NOT extract products the user has NOT personally used
- USE PROPER CAPITALIZATION for brand and product names

SENTIMENT RULES — Base sentiment ONLY on the user's personal experience:
- POSITIVE: User likes it, it worked for them, they recommend it, repurchased it, call it "holy grail", "game changer", "love it"
- NEGATIVE: User says it broke them out, didn't work, caused irritation, they stopped using it, switched away from it, regret buying it, "wouldn't recommend"
- NEUTRAL: User mentions using it but expresses no clear opinion either way

KEY DISTINCTIONS:
- "I switched FROM X to Y" → X is NEGATIVE (they left it), Y is POSITIVE (they chose it)
- "People love X but it didn't work for me" → NEGATIVE (user's own experience wins)
- "X is good but broke me out" → NEGATIVE (skin reaction overrides general praise)
- "I used X, it was okay" → NEUTRAL
- "X worked initially but stopped working" → NEGATIVE
- "I stopped using X" without reason → NEGATIVE (they chose to stop)
- "X was my holy grail but they changed the formula" → NEGATIVE (current experience)

Return ONLY this exact JSON structure:
{{
  "products": [
    {{
      "name": "Full product name with brand (Proper Capitalization)",
      "brand": "Brand Name",
      "category": "cleanser" or "moisturiser" or "sunscreen" or "serum" or "toner" or "other",
      "sentiment": "positive" or "negative" or "neutral"
    }}
  ]
}}

If no specific branded products the user personally used are found: {{"products": []}}

Respond with ONLY valid JSON. No markdown, no explanation."""

    try:
        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
        )
        time.sleep(4)  # Respect Gemini rate limit

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
        if "429" in str(e) or "quota" in str(e).lower():
            print(f"  Gemini quota hit — stopping extraction early.")
            return "QUOTA_HIT"  # Signal to main loop to stop, but don't crash
        print(f"  Gemini error: {e}")
        return None



# ═══════════════════════════════════════
# PRODUCT VALIDATION & DB OPS (unchanged)
# ═══════════════════════════════════════

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
    """Insert into mentions table."""
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


# ═══════════════════════════════════════
# SCORE RECOMPUTATION (unchanged)
# ═══════════════════════════════════════

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


# ═══════════════════════════════════════
# MAIN
# ═══════════════════════════════════════

def main():
    print("=" * 60)
    print("IndiaRecs Scraper — Path G v4 (Pullpush.io, no auth)")
    print("=" * 60)

    print("\n[1/4] Loading existing products...")
    existing_products = supabase.table("products").select("*").execute().data
    print(f"  {len(existing_products)} products in DB")

    print("\n[2/4] Fetching from Pullpush.io (Reddit archive, no auth)...")
    items = fetch_all_items()
    print(f"\n  Total unique items fetched: {len(items)}")

    print("\n[3/4] Processing items...")
    saved = 0
    new_products = 0
    skip_filter = 0
    skip_no_extract = 0
    skip_invalid = 0

    for item in items:
        # Build the text to analyze
        text = item.get("body", "") or ""
        if item.get("dataType") == "post":
            text = (item.get("title", "") or "") + " " + text

        if not is_genuine_review(text):
            skip_filter += 1
            continue

        username = item.get("author") or "anonymous"
        subreddit = item.get("subreddit", "unknown") or "unknown"

        result = extract_products_with_gemini(text)

        # If quota hit, stop processing but continue to save phase
        if result == "QUOTA_HIT":
            break

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
                print(f"    {sentiment} → {product['name']} (by u/{username})")

    print("\n[4/4] Done with scrape, finalizing scores...")
    try:
        finalize_all_scores()
    except Exception as e:
        print(f"  Score finalize failed: {e}")

    print("\n" + "=" * 60)
    print(f"  New products discovered: {new_products}")
    print(f"  Mentions saved:          {saved}")
    print(f"  Skipped (filter):        {skip_filter}")
    print(f"  Skipped (no products):   {skip_no_extract}")
    print(f"  Skipped (invalid):       {skip_invalid}")
    print("=" * 60)


if __name__ == "__main__":
    main()
