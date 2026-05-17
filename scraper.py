"""
IndiaRecs Scraper — Path G Edition (v3)

Changes from v2:
- REMOVED Apify dependency — now uses Reddit's free public JSON API (no auth needed)
- IMPROVED Gemini prompt with explicit sentiment rules (fixes mislabeling)
- Built-in rate limiting for Reddit API (~10 req/min)
- Recursive comment tree flattening
- All other logic (scoring, Supabase, filtering) unchanged
"""

import os
import re
import json
import time
import requests
from supabase import create_client
import google.generativeai as genai


# ═══════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

# Subreddits to scrape (just the name, no URL or r/ prefix)
SUBREDDITS = ["IndianSkincareAddicts", "IndianBeautyDeals", "IndianMakeupAddicts"]

# How many posts to fetch per subreddit
MAX_POSTS_PER_SUB = 15

# Max comments to fetch per post (top-level + nested)
MAX_COMMENTS_PER_POST = 15

# Delay between Reddit API requests (seconds) — keeps us under rate limit
REDDIT_DELAY = 7  # ~8-9 requests per minute to stay safe

# User-Agent header — Reddit blocks requests without one
# Use a descriptive name so Reddit doesn't flag it as a bot
REDDIT_HEADERS = {
    "User-Agent": "IndiaRecsResearchBot/1.0 (skincare product research; educational project)"
}

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
genai.configure(api_key=GEMINI_API_KEY)
gemini = genai.GenerativeModel("gemini-2.5-flash-lite")


# ═══════════════════════════════════════
# REDDIT JSON API FETCHER (replaces Apify)
# ═══════════════════════════════════════

def fetch_posts(subreddit, limit=15):
    """
    Fetch recent posts from a subreddit using Reddit's public JSON API.
    Uses pagination if needed to get up to `limit` posts.
    Returns list of post dicts with keys: title, body, author, subreddit, post_id, num_comments
    """
    posts = []
    after = None  # Pagination cursor
    per_page = min(limit, 25)  # Reddit max per request is 25 for public API

    while len(posts) < limit:
        url = f"https://www.reddit.com/r/{subreddit}/new.json?limit={per_page}"
        if after:
            url += f"&after={after}"

        try:
            response = requests.get(url, headers=REDDIT_HEADERS, timeout=15)

            if response.status_code == 429:
                # Rate limited — wait and retry once
                print(f"    Rate limited on r/{subreddit}, waiting 60s...")
                time.sleep(60)
                response = requests.get(url, headers=REDDIT_HEADERS, timeout=15)

            if response.status_code != 200:
                print(f"    Failed to fetch r/{subreddit}: HTTP {response.status_code}")
                break

            data = response.json()
            children = data.get("data", {}).get("children", [])

            if not children:
                break  # No more posts

            for child in children:
                post_data = child.get("data", {})
                posts.append({
                    "dataType": "post",
                    "title": post_data.get("title", ""),
                    "body": post_data.get("selftext", ""),
                    "author": post_data.get("author", "anonymous"),
                    "subreddit": subreddit,
                    "post_id": post_data.get("id", ""),
                    "num_comments": post_data.get("num_comments", 0),
                    "permalink": post_data.get("permalink", ""),
                })

            # Update pagination cursor
            after = data.get("data", {}).get("after")
            if not after:
                break  # No more pages

            time.sleep(REDDIT_DELAY)

        except requests.exceptions.RequestException as e:
            print(f"    Network error fetching r/{subreddit}: {e}")
            break

    return posts[:limit]


def fetch_comments(subreddit, post_id, max_comments=15):
    """
    Fetch comments for a specific post using Reddit's public JSON API.
    Recursively flattens the comment tree.
    Returns list of comment dicts with keys: body, author, subreddit
    """
    url = f"https://www.reddit.com/r/{subreddit}/comments/{post_id}.json?limit={max_comments}&depth=3"

    try:
        response = requests.get(url, headers=REDDIT_HEADERS, timeout=15)

        if response.status_code == 429:
            print(f"    Rate limited fetching comments, waiting 60s...")
            time.sleep(60)
            response = requests.get(url, headers=REDDIT_HEADERS, timeout=15)

        if response.status_code != 200:
            print(f"    Failed to fetch comments for {post_id}: HTTP {response.status_code}")
            return []

        data = response.json()

        # Reddit returns [post_listing, comments_listing]
        if len(data) < 2:
            return []

        comments_listing = data[1].get("data", {}).get("children", [])
        comments = []
        _flatten_comments(comments_listing, comments, subreddit, max_comments)
        return comments

    except requests.exceptions.RequestException as e:
        print(f"    Network error fetching comments for {post_id}: {e}")
        return []


def _flatten_comments(children, results, subreddit, max_comments):
    """
    Recursively flatten Reddit's nested comment tree into a flat list.
    Stops when we hit max_comments.
    """
    for child in children:
        if len(results) >= max_comments:
            return

        if child.get("kind") != "t1":
            continue  # Skip "more" placeholders and non-comment items

        comment_data = child.get("data", {})
        body = comment_data.get("body", "")
        author = comment_data.get("author", "anonymous")

        # Skip deleted/removed/automod
        if author in ("[deleted]", "AutoModerator"):
            continue

        results.append({
            "dataType": "comment",
            "body": body,
            "author": author,
            "subreddit": subreddit,
        })

        # Recurse into replies
        replies = comment_data.get("replies")
        if replies and isinstance(replies, dict):
            reply_children = replies.get("data", {}).get("children", [])
            _flatten_comments(reply_children, results, subreddit, max_comments)


def fetch_all_items():
    """
    Main fetcher — replaces the entire Apify section.
    Returns a list of items in the same format the rest of the scraper expects.
    """
    all_items = []

    for subreddit in SUBREDDITS:
        print(f"  Fetching r/{subreddit}...")

        posts = fetch_posts(subreddit, limit=MAX_POSTS_PER_SUB)
        print(f"    Got {len(posts)} posts")

        for post in posts:
            # Add the post itself as an item
            all_items.append(post)

            # Only fetch comments if the post has some
            if post["num_comments"] > 0:
                time.sleep(REDDIT_DELAY)
                comments = fetch_comments(subreddit, post["post_id"], MAX_COMMENTS_PER_POST)
                all_items.extend(comments)
                print(f"    Post '{post['title'][:40]}...' → {len(comments)} comments")

        print(f"    Total items from r/{subreddit}: {len([i for i in all_items if i['subreddit'] == subreddit])}")
        time.sleep(REDDIT_DELAY)  # Pause between subreddits

    return all_items


# ═══════════════════════════════════════
# REVIEW FILTER (unchanged from v2)
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
# GEMINI EXTRACTION (improved prompt)
# ═══════════════════════════════════════

def extract_products_with_gemini(text):
    """
    Send review text to Gemini for product extraction + sentiment analysis.
    IMPROVED: Explicit sentiment rules with edge-case examples to fix mislabeling.
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
        response = gemini.generate_content(prompt)
        time.sleep(5)  # Respect Gemini rate limit
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
            raise SystemExit(1)
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
    """Insert into mentions table — score recompute happens later."""
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
    print("IndiaRecs Scraper — Path G Edition v3 (Free Reddit JSON)")
    print("=" * 60)

    print("\n[1/4] Loading existing products...")
    existing_products = supabase.table("products").select("*").execute().data
    print(f"  {len(existing_products)} products in DB")

    print("\n[2/4] Fetching from Reddit (public JSON API, no auth)...")
    items = fetch_all_items()
    print(f"\n  Total items fetched: {len(items)}")

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
