"""
IndiaRecs — Skincare Scraper
=============================

Flow:
- Reddit comment/post fetched via Pullpush.io
- First checked against cleansers catalog (name, aliases, reddit_search_terms)
  → If matched: Gemini determines sentiment only → save mention with cleanser_id → update cleanser scores
- If no cleanser match: old Gemini extraction flow → products table (serums, moisturisers, etc.)
- A single comment can trigger both flows if it mentions a cleanser AND another product
"""

import os
import re
import json
import time
import requests
from supabase import create_client

from google import genai

# ═══════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

SUBREDDITS = ["IndianSkincareAddicts", "IndianBeautyDeals", "IndianMakeupAddicts"]

PULLPUSH_COMMENT_URL = "https://api.pullpush.io/reddit/search/comment/"
PULLPUSH_POST_URL    = "https://api.pullpush.io/reddit/search/submission/"

COMMENTS_PER_SUB = 100
POSTS_PER_SUB    = 25

REVIEW_QUERIES = [
    "recommend OR recommended OR holy grail",
    "been using OR currently using OR switched to",
    "love this OR hate this OR broke me out",
    "review OR repurchase OR game changer",
]

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

supabase      = create_client(SUPABASE_URL, SUPABASE_KEY)
gemini_client = genai.Client(api_key=GEMINI_API_KEY)
GEMINI_MODEL  = "gemini-2.5-flash-lite"


# ═══════════════════════════════════════
# HELPER: SLUG GENERATION
# ═══════════════════════════════════════

def generate_slug(name):
    slug = name.lower().strip()
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'\s+', '-', slug)
    slug = re.sub(r'-+', '-', slug)
    slug = slug.strip('-')
    return slug


# ═══════════════════════════════════════
# CLEANSER CATALOG LOADER
# ═══════════════════════════════════════

def load_cleanser_catalog():
    """
    Load all active cleansers from the cleansers table.
    Builds a flat lookup list with pre-normalised match terms.
    Each entry: { id, name, match_terms: [lowercase strings] }
    """
    print("  Loading cleanser catalog from Supabase...")
    rows = supabase.table("cleansers").select(
        "id, name, aliases, reddit_search_terms"
    ).eq("is_active", True).execute().data

    catalog = []
    for row in rows:
        terms = set()

        # Add the product name itself
        terms.add(row["name"].lower().strip())

        # Add aliases (JSON array of strings)
        for alias in (row.get("aliases") or []):
            terms.add(alias.lower().strip())

        # Add reddit_search_terms (JSON array of strings)
        for term in (row.get("reddit_search_terms") or []):
            terms.add(term.lower().strip())

        catalog.append({
            "id":           row["id"],
            "name":         row["name"],
            "match_terms":  list(terms),
        })

    print(f"  Loaded {len(catalog)} active cleansers into catalog.")
    return catalog


# ═══════════════════════════════════════
# CLEANSER MATCHER
# ═══════════════════════════════════════

def match_cleansers_in_text(text, catalog):
    """
    Check comment/post text against the cleanser catalog.
    Returns list of matched catalog entries (can be more than one).
    Uses word-boundary aware matching to avoid false positives.
    """
    text_lower = text.lower()
    matched = []

    for cleanser in catalog:
        for term in cleanser["match_terms"]:
            # Use word boundary matching for short terms (< 15 chars) to reduce false positives
            if len(term) < 15:
                pattern = r'\b' + re.escape(term) + r'\b'
                if re.search(pattern, text_lower):
                    matched.append(cleanser)
                    break
            else:
                if term in text_lower:
                    matched.append(cleanser)
                    break

    return matched


# ═══════════════════════════════════════
# PULLPUSH.IO FETCHER
# ═══════════════════════════════════════

def fetch_comments_pullpush(subreddit, query, size=100):
    params = {
        "subreddit": subreddit,
        "q":         query,
        "size":      size,
        "sort":      "desc",
        "sort_type": "created_utc",
    }
    try:
        response = requests.get(PULLPUSH_COMMENT_URL, params=params, timeout=30)
        if response.status_code != 200:
            print(f"    Pullpush comment fetch failed: HTTP {response.status_code}")
            return []

        results = []
        for c in response.json().get("data", []):
            author = c.get("author", "anonymous")
            body   = c.get("body", "")
            if author in ("[deleted]", "AutoModerator", "[removed]"):
                continue
            if body in ("[deleted]", "[removed]", ""):
                continue
            permalink = c.get("permalink", "")
            results.append({
                "dataType":   "comment",
                "body":       body,
                "author":     author,
                "subreddit":  subreddit,
                "reddit_url": f"https://www.reddit.com{permalink}" if permalink else None,
            })
        return results

    except requests.exceptions.RequestException as e:
        print(f"    Network error (comments): {e}")
        return []


def fetch_posts_pullpush(subreddit, size=25):
    params = {
        "subreddit":    subreddit,
        "size":         size,
        "sort":         "desc",
        "sort_type":    "created_utc",
        "selftext:not": "[removed]",
    }
    try:
        response = requests.get(PULLPUSH_POST_URL, params=params, timeout=30)
        if response.status_code != 200:
            print(f"    Pullpush post fetch failed: HTTP {response.status_code}")
            return []

        results = []
        for p in response.json().get("data", []):
            author   = p.get("author", "anonymous")
            selftext = p.get("selftext", "")
            if author in ("[deleted]", "AutoModerator"):
                continue
            if selftext in ("[deleted]", "[removed]", ""):
                continue
            permalink = p.get("permalink", "")
            results.append({
                "dataType":   "post",
                "title":      p.get("title", ""),
                "body":       selftext,
                "author":     author,
                "subreddit":  subreddit,
                "reddit_url": f"https://www.reddit.com{permalink}" if permalink else None,
            })
        return results

    except requests.exceptions.RequestException as e:
        print(f"    Network error (posts): {e}")
        return []


def fetch_all_items():
    all_items  = []
    seen_bodies = set()

    for subreddit in SUBREDDITS:
        print(f"  Fetching r/{subreddit}...")
        sub_count = 0

        for query in REVIEW_QUERIES:
            time.sleep(API_DELAY)
            comments = fetch_comments_pullpush(subreddit, query, COMMENTS_PER_SUB)
            for c in comments:
                key = c["body"][:100].lower()
                if key not in seen_bodies:
                    seen_bodies.add(key)
                    all_items.append(c)
                    sub_count += 1
            print(f"    Query '{query[:40]}...' → {len(comments)} raw, {sub_count} unique total")

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
# REVIEW FILTER
# ═══════════════════════════════════════

def is_genuine_review(text):
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
# GEMINI: SENTIMENT ONLY (for catalog cleansers)
# ═══════════════════════════════════════

def get_cleanser_sentiment_with_gemini(text, cleanser_name):
    """
    Ask Gemini to determine sentiment for a specific known cleanser.
    Does NOT extract products — cleanser is already identified.
    """
    prompt = f"""You are a sentiment analysis expert for Indian skincare reviews on Reddit.

The user's comment has already been matched to this cleanser: "{cleanser_name}"

Your job is ONLY to determine the user's sentiment toward this specific product based on their personal experience.

Comment:
{text}

SENTIMENT RULES:
- POSITIVE: User likes it, it worked for them, they recommend it, repurchased, call it "holy grail" or "game changer"
- NEGATIVE: User says it broke them out, didn't work, caused irritation, they stopped using it, switched away from it, regret buying
- NEUTRAL: User mentions using it but expresses no clear opinion

KEY DISTINCTIONS:
- "I switched FROM X to Y" → X is NEGATIVE, Y is POSITIVE
- "People love X but it didn't work for me" → NEGATIVE
- "X is good but broke me out" → NEGATIVE
- "I used X, it was okay" → NEUTRAL
- "I stopped using X" without reason → NEGATIVE

Return ONLY this exact JSON:
{{"sentiment": "positive" or "negative" or "neutral"}}

Respond with ONLY valid JSON. No markdown, no explanation."""

    try:
        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
        )
        time.sleep(4)

        clean = response.text.strip()
        clean = re.sub(r"^```(?:json)?", "", clean).strip()
        clean = re.sub(r"```$", "", clean).strip()
        result = json.loads(clean)

        sentiment = result.get("sentiment", "neutral")
        if sentiment not in ("positive", "negative", "neutral"):
            sentiment = "neutral"
        return sentiment

    except Exception as e:
        if "429" in str(e) or "quota" in str(e).lower():
            return "QUOTA_HIT"
        print(f"  Gemini sentiment error: {e}")
        return "neutral"


# ═══════════════════════════════════════
# GEMINI: FULL EXTRACTION (for non-cleanser products)
# ═══════════════════════════════════════

def extract_products_with_gemini(text):
    """
    Full Gemini extraction for non-cleanser products (serums, moisturisers, etc.).
    Explicitly excludes cleansers since those are handled by the catalog flow.
    """
    prompt = f"""You are a sentiment analysis expert for Indian skincare product reviews on Reddit.

Analyze this comment and extract specific BRANDED products the user has PERSONALLY USED, along with their sentiment.

IMPORTANT: DO NOT extract cleansers or face washes. Those are handled separately.
Only extract: serums, moisturisers, sunscreens, toners, and other skincare products.

Comment: {text}

PRODUCT EXTRACTION RULES:
- Only extract products with a clear brand name (e.g., "Minimalist Niacinamide 10%", "Cetaphil Moisturising Cream")
- Brand alone is OK if category is clear from context
- DO NOT extract generic terms without a brand
- DO NOT extract cleansers, face washes, micellar waters, cleansing balms, or foaming washes
- DO NOT extract products only mentioned in questions ("has anyone tried X?")
- DO NOT extract products the user has NOT personally used
- USE PROPER CAPITALIZATION for brand and product names

SENTIMENT RULES — Base sentiment ONLY on the user's personal experience:
- POSITIVE: User likes it, it worked for them, they recommend it, repurchased it
- NEGATIVE: User says it broke them out, didn't work, caused irritation, they stopped using it
- NEUTRAL: User mentions using it but expresses no clear opinion

KEY DISTINCTIONS:
- "I switched FROM X to Y" → X is NEGATIVE, Y is POSITIVE
- "People love X but it didn't work for me" → NEGATIVE
- "X is good but broke me out" → NEGATIVE
- "I stopped using X" without reason → NEGATIVE

Return ONLY this exact JSON structure:
{{
  "products": [
    {{
      "name": "Full product name with brand (Proper Capitalization)",
      "brand": "Brand Name",
      "category": "moisturiser" or "sunscreen" or "serum" or "toner" or "other",
      "sentiment": "positive" or "negative" or "neutral"
    }}
  ]
}}

If no matching products found: {{"products": []}}

Respond with ONLY valid JSON. No markdown, no explanation."""

    try:
        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
        )
        time.sleep(4)

        clean = response.text.strip()
        clean = re.sub(r"^```(?:json)?", "", clean).strip()
        clean = re.sub(r"```$", "", clean).strip()
        result = json.loads(clean)

        if result and "products" in result:
            for p in result["products"]:
                if p.get("name") and p["name"] == p["name"].lower():
                    p["name"] = p["name"].title()
                if p.get("brand") and p["brand"] == p["brand"].lower():
                    p["brand"] = p["brand"].title()
        return result

    except Exception as e:
        if "429" in str(e) or "quota" in str(e).lower():
            return "QUOTA_HIT"
        print(f"  Gemini error: {e}")
        return None


# ═══════════════════════════════════════
# PRODUCT VALIDATION & DB OPS
# ═══════════════════════════════════════

def is_valid_product(extracted):
    name     = (extracted.get("name") or "").strip()
    brand    = (extracted.get("brand") or "").strip()
    category = (extracted.get("category") or "").strip().lower()
    if not name or len(name) < 5:
        return False
    if not brand or len(brand) < 3:
        return False
    if name.lower() in GENERIC_TERMS or brand.lower() in GENERIC_TERMS:
        return False
    # Reject cleansers that slipped through
    if category == "cleanser":
        return False
    if category not in VALID_CATEGORIES:
        return False
    return True


def find_or_create_product(extracted, existing_products):
    name_lower  = extracted["name"].lower()
    brand_lower = extracted["brand"].lower()
    category    = extracted["category"]

    for p in existing_products:
        if p["name"].lower() == name_lower:
            return p, False

    for p in existing_products:
        if (p.get("brand") or "").lower() == brand_lower and \
           (p.get("product_category") or "") == category:
            return p, False

    slug = generate_slug(extracted["name"])
    existing_slugs = {p.get("slug") for p in existing_products if p.get("slug")}
    if slug in existing_slugs:
        slug = generate_slug(f"{extracted['brand']} {extracted['name']}")

    new_data = {
        "name":             extracted["name"],
        "slug":             slug,
        "category":         "skincare",
        "brand":            extracted["brand"],
        "product_category": category,
        "mention_count":    0,
        "positive_count":   0,
        "negative_count":   0,
        "score":            0,
        "skin_type":        "all",
        "price_inr":        0,
        "image_url":        None,
        "affiliate_url":    None,
    }
    try:
        result = supabase.table("products").insert(new_data).execute()
        new_data["id"] = result.data[0]["id"]
        existing_products.append(new_data)
        return new_data, True
    except Exception as e:
        print(f"  Insert failed: {e}")
        return None, False


# ═══════════════════════════════════════
# MENTION SAVERS
# ═══════════════════════════════════════

def save_cleanser_mention(cleanser, comment_text, sentiment, subreddit, username, reddit_url=None):
    """Save a mention tied to the cleansers catalog via cleanser_id."""
    try:
        mention_data = {
            "cleanser_id":    cleanser["id"],
            "product_name":   cleanser["name"],   # kept for readability/debugging
            "comment_text":   comment_text[:1000],
            "sentiment":      sentiment,
            "subreddit":      subreddit,
            "username":       username,
        }
        if reddit_url:
            mention_data["reddit_url"] = reddit_url

        supabase.table("mentions").insert(mention_data).execute()
        return True
    except Exception as e:
        print(f"  Cleanser mention save failed: {e}")
        return False


def save_product_mention(product, comment_text, sentiment, subreddit, username, reddit_url=None):
    """Save a mention tied to the products table."""
    try:
        mention_data = {
            "product_name":  product["name"],
            "comment_text":  comment_text[:1000],
            "sentiment":     sentiment,
            "subreddit":     subreddit,
            "username":      username,
        }
        if reddit_url:
            mention_data["reddit_url"] = reddit_url

        supabase.table("mentions").insert(mention_data).execute()
        return True
    except Exception as e:
        print(f"  Product mention save failed: {e}")
        return False


# ═══════════════════════════════════════
# SCORE RECOMPUTATION
# ═══════════════════════════════════════

def finalize_cleanser_scores():
    """
    Recompute scores for all cleansers using mentions with cleanser_id.
    Same per-user voting + 75/25 formula as products.
    """
    print("\n  Recomputing cleanser scores...")

    mentions_data = supabase.table("mentions").select(
        "cleanser_id, username, sentiment"
    ).not_.is_("cleanser_id", "null").execute().data

    by_cleanser = {}
    for m in mentions_data:
        cid  = m.get("cleanser_id")
        if not cid:
            continue
        user      = m.get("username") or "anonymous"
        sentiment = m.get("sentiment") or "neutral"
        by_cleanser.setdefault(cid, {}).setdefault(
            user, {"positive": 0, "negative": 0, "neutral": 0}
        )
        by_cleanser[cid][user][sentiment] = by_cleanser[cid][user].get(sentiment, 0) + 1

    cleanser_stats = {}
    for cid, users in by_cleanser.items():
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
        cleanser_stats[cid] = {
            "positive_users": pos,
            "negative_users": neg,
            "neutral_users":  neu,
            "total_mentions": total_mentions,
        }

    max_positive = max(
        (s["positive_users"] for s in cleanser_stats.values()),
        default=1
    ) or 1

    cleansers = supabase.table("cleansers").select("id").eq("is_active", True).execute().data
    updated = 0
    for cleanser in cleansers:
        cid = cleanser["id"]
        if cid not in cleanser_stats:
            supabase.table("cleansers").update({
                "mention_count":  0,
                "positive_count": 0,
                "negative_count": 0,
                "score":          0,
            }).eq("id", cid).execute()
            continue

        s   = cleanser_stats[cid]
        pos = s["positive_users"]
        neg = s["negative_users"]
        denom = pos + neg

        if pos + neg + s["neutral_users"] == 0:
            score = 0.0
        else:
            norm_positive = pos / max_positive
            pos_ratio     = pos / denom if denom > 0 else 0
            score         = round((0.75 * norm_positive + 0.25 * pos_ratio) * 100, 2)

        supabase.table("cleansers").update({
            "mention_count":  s["total_mentions"],
            "positive_count": pos,
            "negative_count": neg,
            "score":          score,
        }).eq("id", cid).execute()
        updated += 1

    print(f"  Recomputed scores for {updated} cleansers (max_positive={max_positive})")


def finalize_all_scores():
    """
    Recompute scores for all products in the products table.
    Only processes mentions WITHOUT a cleanser_id (i.e. serums, moisturisers, etc.).
    """
    print("\n  Recomputing product scores (serums, moisturisers, etc.)...")

    mentions_data = supabase.table("mentions").select(
        "product_name, username, sentiment"
    ).is_("cleanser_id", "null").execute().data

    by_product = {}
    for m in mentions_data:
        pn = m.get("product_name")
        if not pn:
            continue
        user      = m.get("username") or "anonymous"
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
            "neutral_users":  neu,
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
                "mention_count":  0,
                "positive_count": 0,
                "negative_count": 0,
                "score":          0,
            }).eq("id", product["id"]).execute()
            continue

        s     = product_stats[pn]
        pos   = s["positive_users"]
        neg   = s["negative_users"]
        denom = pos + neg

        if pos + neg + s["neutral_users"] == 0:
            score = 0.0
        else:
            norm_positive = pos / max_positive
            pos_ratio     = pos / denom if denom > 0 else 0
            score         = round((0.75 * norm_positive + 0.25 * pos_ratio) * 100, 2)

        supabase.table("products").update({
            "mention_count":  s["total_mentions"],
            "positive_count": pos,
            "negative_count": neg,
            "score":          score,
        }).eq("id", product["id"]).execute()
        updated += 1

    print(f"  Recomputed scores for {updated} products (max_positive={max_positive})")


# ═══════════════════════════════════════
# MAIN
# ═══════════════════════════════════════

def main():
    print("=" * 60)
    print("IndiaRecs — Skincare Scraper")
    print("=" * 60)

    # ── 1. Load catalogs ──────────────────────────────────────
    print("\n[1/5] Loading catalogs...")
    cleanser_catalog  = load_cleanser_catalog()
    existing_products = supabase.table("products").select("*").execute().data
    print(f"  {len(existing_products)} products in DB")

    # ── 2. Fetch from Reddit via Pullpush ─────────────────────
    print("\n[2/5] Fetching from Pullpush.io...")
    items = fetch_all_items()
    print(f"\n  Total unique items fetched: {len(items)}")

    # ── 3. Process items ──────────────────────────────────────
    print("\n[3/5] Processing items...")

    cleanser_mentions_saved = 0
    product_mentions_saved  = 0
    new_products            = 0
    skip_filter             = 0
    skip_no_extract         = 0
    skip_invalid            = 0
    quota_hit               = False

    for item in items:
        text = item.get("body", "") or ""
        if item.get("dataType") == "post":
            text = (item.get("title", "") or "") + " " + text

        if not is_genuine_review(text):
            skip_filter += 1
            continue

        username   = item.get("author") or "anonymous"
        subreddit  = item.get("subreddit", "unknown") or "unknown"
        reddit_url = item.get("reddit_url")

        # ── CLEANSER FLOW ──────────────────────────────────────
        matched_cleansers = match_cleansers_in_text(text, cleanser_catalog)

        for cleanser in matched_cleansers:
            sentiment = get_cleanser_sentiment_with_gemini(text, cleanser["name"])

            if sentiment == "QUOTA_HIT":
                print("  Gemini quota hit — stopping.")
                quota_hit = True
                break

            if save_cleanser_mention(cleanser, text, sentiment, subreddit, username, reddit_url):
                cleanser_mentions_saved += 1
                print(f"    [cleanser] {sentiment} → {cleanser['name']} (by u/{username})")

        if quota_hit:
            break

        # ── PRODUCT FLOW (serums, moisturisers, etc.) ──────────
        # Always runs even if cleansers were matched — a comment can mention both
        result = extract_products_with_gemini(text)

        if result == "QUOTA_HIT":
            print("  Gemini quota hit — stopping.")
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
                print(f"  + New product: {product['name']} (/{product.get('slug', '?')})")

            sentiment = extracted.get("sentiment", "neutral")
            if sentiment not in ("positive", "negative", "neutral"):
                sentiment = "neutral"

            if save_product_mention(product, text, sentiment, subreddit, username, reddit_url):
                product_mentions_saved += 1
                print(f"    [product]  {sentiment} → {product['name']} (by u/{username})")

    # ── 4. Finalize scores ────────────────────────────────────
    print("\n[4/5] Finalizing scores...")
    try:
        finalize_cleanser_scores()
    except Exception as e:
        print(f"  Cleanser score finalize failed: {e}")

    try:
        finalize_all_scores()
    except Exception as e:
        print(f"  Product score finalize failed: {e}")

    # ── 5. Summary ────────────────────────────────────────────
    print("\n[5/5] Done.")
    print("=" * 60)
    print(f"  Cleanser mentions saved:  {cleanser_mentions_saved}")
    print(f"  Product mentions saved:   {product_mentions_saved}")
    print(f"  New products discovered:  {new_products}")
    print(f"  Skipped (filter):         {skip_filter}")
    print(f"  Skipped (no products):    {skip_no_extract}")
    print(f"  Skipped (invalid):        {skip_invalid}")
    print("=" * 60)


if __name__ == "__main__":
    main()
