"""
IndiaRecs Fragrance Scraper — v1
==================================
Parallel to scraper.py (skincare) but targets fragrances.

Key differences from skincare scraper:
- Loads curated fragrance list from `fragrances` table (source of truth)
- Gemini MATCHES comments to the list (no discovery/invention)
- Returns specificity_score (0.0–1.0) per match
- Saves to shared `mentions` table with specificity_score
- Score recomputation targets `fragrances` table using 75/25 formula
- Subreddits: r/DesiFragranceAddicts, r/desifemfrag
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

# Fragrance subreddits
SUBREDDITS = ["DesiFragranceAddicts", "desifemfrag"]

# Pullpush.io endpoints (same as skincare scraper)
PULLPUSH_COMMENT_URL = "https://api.pullpush.io/reddit/search/comment/"
PULLPUSH_POST_URL    = "https://api.pullpush.io/reddit/search/submission/"

# Fetch sizes
COMMENTS_PER_QUERY = 100
POSTS_PER_SUB      = 25

# Review-focused queries for fragrance subreddits
REVIEW_QUERIES = [
    "recommend OR recommended OR holy grail",
    "been wearing OR currently wearing OR blind buy",
    "love this OR hate this OR scrubber",
    "review OR repurchase OR game changer",
    "longevity OR sillage OR projection",
    "smells like OR reminds me OR similar to",
]

# Delay between API calls (seconds)
API_DELAY = 3


# ═══════════════════════════════════════
# INIT CLIENTS
# ═══════════════════════════════════════

supabase      = create_client(SUPABASE_URL, SUPABASE_KEY)
gemini_client = genai.Client(api_key=GEMINI_API_KEY)
GEMINI_MODEL  = "gemini-2.5-flash-lite"


# ═══════════════════════════════════════
# LOAD FRAGRANCE LIST FROM DB
# ═══════════════════════════════════════

def load_fragrance_list():
    """
    Load all active fragrances from Supabase.
    Returns list of dicts with id, name, aliases, reddit_search_terms.
    This is the MASTER LIST — Gemini only matches to these, never invents.
    """
    result = supabase.table("fragrances").select(
        "id, name, brand, aliases, reddit_search_terms"
    ).eq("is_active", True).execute()

    fragrances = result.data or []
    print(f"  Loaded {len(fragrances)} active fragrances from DB")
    return fragrances


def build_fragrance_lookup(fragrances):
    """
    Build a dict: canonical_name (lowercase) → fragrance row.
    Used to resolve Gemini's match back to a DB row.
    """
    lookup = {}
    for f in fragrances:
        lookup[f["name"].lower()] = f
        for alias in (f.get("aliases") or []):
            lookup[alias.lower()] = f
    return lookup


# ═══════════════════════════════════════
# PULLPUSH FETCHERS (same pattern as skincare)
# ═══════════════════════════════════════

def fetch_comments_pullpush(subreddit, query, size=100):
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
        comments = response.json().get("data", [])
        results = []
        for c in comments:
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
        "subreddit": subreddit,
        "size": size,
        "sort": "desc",
        "sort_type": "created_utc",
        "selftext:not": "[removed]",
    }
    try:
        response = requests.get(PULLPUSH_POST_URL, params=params, timeout=30)
        if response.status_code != 200:
            print(f"    Pullpush post fetch failed: HTTP {response.status_code}")
            return []
        posts = response.json().get("data", [])
        results = []
        for p in posts:
            author   = p.get("author", "anonymous")
            selftext = p.get("selftext", "")
            title    = p.get("title", "")
            if author in ("[deleted]", "AutoModerator"):
                continue
            if selftext in ("[deleted]", "[removed]", ""):
                continue
            permalink = p.get("permalink", "")
            results.append({
                "dataType":   "post",
                "title":      title,
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
    """
    Fetch comments + posts from fragrance subreddits.
    Also fetches using each fragrance's reddit_search_terms for targeted coverage.
    """
    all_items  = []
    seen_bodies = set()

    for subreddit in SUBREDDITS:
        print(f"  Fetching r/{subreddit}...")
        sub_count = 0

        # General review-focused queries
        for query in REVIEW_QUERIES:
            time.sleep(API_DELAY)
            comments = fetch_comments_pullpush(subreddit, query, COMMENTS_PER_QUERY)
            for c in comments:
                key = c["body"][:100].lower()
                if key not in seen_bodies:
                    seen_bodies.add(key)
                    all_items.append(c)
                    sub_count += 1
            print(f"    Query '{query[:40]}' → {len(comments)} raw")

        # Recent posts
        time.sleep(API_DELAY)
        posts = fetch_posts_pullpush(subreddit, POSTS_PER_SUB)
        for p in posts:
            key = (p.get("body") or "")[:100].lower()
            if key and key not in seen_bodies:
                seen_bodies.add(key)
                all_items.append(p)
                sub_count += 1

        print(f"    Total unique from r/{subreddit}: {sub_count}")

    return all_items


# ═══════════════════════════════════════
# REVIEW FILTER (fragrance-aware)
# ═══════════════════════════════════════

def is_genuine_fragrance_review(text):
    """
    Must mention fragrance context AND show review intent.
    Looser than skincare filter — fragrance reviews are naturally shorter.
    """
    if not text or len(text.split()) < 15:
        return False
    if "AutoModerator" in text or "[deleted]" in text or "[removed]" in text:
        return False

    text_lower = text.lower()

    fragrance_keywords = [
        "perfume", "fragrance", "cologne", "edp", "edt", "parfum",
        "oud", "attar", "scent", "smell", "spritz", "spray",
        "longevity", "sillage", "projection", "drydown", "dry down",
        "blind buy", "decant", "bottle", "opening", "basenote",
        "base note", "top note", "heart note", "clone", "dupe",
    ]
    if not any(k in text_lower for k in fragrance_keywords):
        return False

    review_signals = [
        "i use", "i used", "i've used", "ive used", "been wearing",
        "i tried", "i've tried", "ive tried", "smells like", "for me",
        "works for me", "love this", "hate this", "would recommend",
        "highly recommend", "holy grail", "after wearing", "since wearing",
        "blind buy", "repurchase", "scrubber", "compliment", "projection",
        "lasts", "longevity", "fades", "worth it", "obsessed with",
        "reminds me", "similar to", "smells amazing", "can't stand",
        "my favourite", "my favorite", "go-to", "signature scent",
    ]
    return any(s in text_lower for s in review_signals)


# ═══════════════════════════════════════
# GEMINI MATCHING (core difference from skincare)
# ═══════════════════════════════════════

def match_fragrances_with_gemini(text, fragrances):
    """
    Send comment + fragrance list to Gemini.
    Gemini MATCHES to existing fragrances only — never invents new ones.

    Returns list of matches:
    [{ "name": "Dior Sauvage EDP", "sentiment": "positive", "specificity_score": 0.9 }]

    specificity_score:
      1.0 = exact match (named concentration + brand)
      0.7 = named fragrance but not concentration (e.g. "Sauvage" could be EDT or EDP)
      0.4 = brand only or very vague reference
      0.0 = no match
    """

    # Build a compact fragrance list for the prompt
    # Include name + key aliases to help matching
    fragrance_lines = []
    for f in fragrances:
        aliases = f.get("aliases") or []
        alias_str = f" (also known as: {', '.join(aliases[:3])})" if aliases else ""
        fragrance_lines.append(f"- {f['name']}{alias_str}")

    fragrance_list_str = "\n".join(fragrance_lines)

    prompt = f"""You are a fragrance review analyst for the Indian market.

Your job is to read a Reddit comment and identify which fragrances from the provided list the user has PERSONALLY USED OR WORN, along with their sentiment.

FRAGRANCE LIST (match ONLY to these — do not invent):
{fragrance_list_str}

Reddit Comment:
{text}

MATCHING RULES:
- Only match if the user has personally used/worn the fragrance
- Do NOT match fragrances only mentioned in questions ("has anyone tried X?")
- Do NOT match fragrances mentioned by others ("my friend uses X")
- Match aliases and abbreviations to their canonical name (e.g. "BDC" → "Bleu de Chanel EDP")
- If "Sauvage" is mentioned without EDT/EDP, match BOTH Dior Sauvage EDT and Dior Sauvage EDP with lower specificity

SENTIMENT RULES:
- POSITIVE: user likes it, recommends it, repurchased, calls it holy grail, compliments received
- NEGATIVE: scrubber, doesn't like it, stopped wearing, broke out, headache, overrated
- NEUTRAL: mentions using it with no clear opinion

SPECIFICITY SCORE:
- 1.0 = exact name + concentration mentioned (e.g. "Dior Sauvage EDP")
- 0.7 = fragrance named but concentration ambiguous (e.g. "Sauvage" or "Bleu de Chanel")
- 0.4 = brand + vague reference (e.g. "that Dior woody one")
- 0.0 = no match

Return ONLY this exact JSON:
{{
  "matches": [
    {{
      "name": "Exact canonical name from the list above",
      "sentiment": "positive" or "negative" or "neutral",
      "specificity_score": 0.0 to 1.0
    }}
  ]
}}

If no fragrances from the list are personally used: {{"matches": []}}
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
        return result.get("matches", [])

    except Exception as e:
        if "429" in str(e) or "quota" in str(e).lower():
            print(f"  Gemini quota hit — stopping extraction early.")
            return "QUOTA_HIT"
        print(f"  Gemini error: {e}")
        return []


# ═══════════════════════════════════════
# SAVE MENTION
# ═══════════════════════════════════════

def save_mention(fragrance_name, comment_text, sentiment, subreddit,
                 username, specificity_score, reddit_url=None):
    """Save a fragrance mention to the shared mentions table."""
    try:
        data = {
            "product_name":      fragrance_name,
            "comment_text":      comment_text[:1000],
            "sentiment":         sentiment,
            "subreddit":         subreddit,
            "username":          username,
            "specificity_score": specificity_score,
        }
        if reddit_url:
            data["reddit_url"] = reddit_url

        supabase.table("mentions").insert(data).execute()
        return True
    except Exception as e:
        print(f"  Save mention failed: {e}")
        return False


# ═══════════════════════════════════════
# SCORE RECOMPUTATION (fragrances table)
# ═══════════════════════════════════════

def finalize_fragrance_scores():
    """
    Recompute scores for all fragrances using:
    - specificity_score weighted voting (not raw count)
    - Per-user dominant sentiment (1 user = max 1 vote per fragrance)
    - 75/25 formula: 0.75 * norm_positive + 0.25 * pos_ratio

    specificity_score acts as vote weight:
    A user who says "Dior Sauvage EDP" (1.0) counts more than
    someone who says "that Sauvage" (0.7).
    """
    print("\n  Recomputing fragrance scores...")

    # Load all fragrance mentions
    # We identify them by checking if product_name matches a fragrance
    fragrance_names = set(
        f["name"] for f in
        supabase.table("fragrances").select("name").execute().data
    )

    mentions_data = supabase.table("mentions").select(
        "product_name, username, sentiment, specificity_score"
    ).execute().data

    # Filter to fragrance mentions only
    fragrance_mentions = [
        m for m in mentions_data
        if m.get("product_name") in fragrance_names
    ]

    # Aggregate: per fragrance, per user, weighted by specificity
    by_fragrance = {}
    for m in fragrance_mentions:
        fn        = m["product_name"]
        user      = m.get("username") or "anonymous"
        sentiment = m.get("sentiment") or "neutral"
        weight    = float(m.get("specificity_score") or 1.0)

        by_fragrance.setdefault(fn, {}).setdefault(
            user, {"positive": 0.0, "negative": 0.0, "neutral": 0.0, "total": 0}
        )
        by_fragrance[fn][user][sentiment] += weight
        by_fragrance[fn][user]["total"]   += 1

    # Compute per-fragrance stats
    fragrance_stats = {}
    for fn, users in by_fragrance.items():
        pos = neg = neu = 0.0
        total_mentions = 0
        for user, counts in users.items():
            total_mentions += counts["total"]
            # Dominant sentiment by weighted score
            dominant = max(
                ["positive", "negative", "neutral"],
                key=lambda s: counts[s]
            )
            if dominant == "positive":
                pos += 1
            elif dominant == "negative":
                neg += 1
            else:
                neu += 1
        fragrance_stats[fn] = {
            "positive_users": pos,
            "negative_users": neg,
            "neutral_users":  neu,
            "total_mentions": total_mentions,
        }

    max_positive = max(
        (s["positive_users"] for s in fragrance_stats.values()),
        default=1
    ) or 1

    # Update fragrances table
    fragrances = supabase.table("fragrances").select("id, name").execute().data
    updated = 0

    for fragrance in fragrances:
        fn = fragrance["name"]

        if fn not in fragrance_stats:
            supabase.table("fragrances").update({
                "mention_count":  0,
                "positive_count": 0,
                "negative_count": 0,
                "score":          0,
                "last_scraped_at": "now()",
            }).eq("id", fragrance["id"]).execute()
            continue

        s   = fragrance_stats[fn]
        pos = s["positive_users"]
        neg = s["negative_users"]
        den = pos + neg

        norm_positive = pos / max_positive
        pos_ratio     = pos / den if den > 0 else 0
        score         = round((0.75 * norm_positive + 0.25 * pos_ratio) * 100, 2)

        supabase.table("fragrances").update({
            "mention_count":  s["total_mentions"],
            "positive_count": int(pos),
            "negative_count": int(neg),
            "score":          score,
            "last_scraped_at": "now()",
        }).eq("id", fragrance["id"]).execute()
        updated += 1

    print(f"  Updated scores for {updated} fragrances (max_positive={max_positive})")


# ═══════════════════════════════════════
# MAIN
# ═══════════════════════════════════════

def main():
    print("=" * 60)
    print("IndiaRecs Fragrance Scraper — v1")
    print("Subreddits: r/DesiFragranceAddicts, r/desifemfrag")
    print("=" * 60)

    # Step 1: Load fragrance master list
    print("\n[1/4] Loading fragrance master list...")
    fragrances      = load_fragrance_list()
    fragrance_lookup = build_fragrance_lookup(fragrances)

    # Step 2: Fetch Reddit content
    print("\n[2/4] Fetching from Pullpush.io...")
    items = fetch_all_items()
    print(f"\n  Total unique items fetched: {len(items)}")

    # Step 3: Process each item
    print("\n[3/4] Processing items...")
    saved         = 0
    skip_filter   = 0
    skip_no_match = 0

    for item in items:
        text = item.get("body", "") or ""
        if item.get("dataType") == "post":
            text = (item.get("title", "") or "") + " " + text

        if not is_genuine_fragrance_review(text):
            skip_filter += 1
            continue

        username   = item.get("author") or "anonymous"
        subreddit  = item.get("subreddit", "unknown")
        reddit_url = item.get("reddit_url")

        matches = match_fragrances_with_gemini(text, fragrances)

        if matches == "QUOTA_HIT":
            break

        if not matches:
            skip_no_match += 1
            continue

        for match in matches:
            matched_name       = match.get("name", "").strip()
            sentiment          = match.get("sentiment", "neutral")
            specificity_score  = float(match.get("specificity_score", 1.0))

            if sentiment not in ("positive", "negative", "neutral"):
                sentiment = "neutral"

            # Verify the matched name exists in our DB (safety check)
            fragrance_row = fragrance_lookup.get(matched_name.lower())
            if not fragrance_row:
                print(f"  Gemini returned unknown fragrance '{matched_name}' — skipping")
                continue

            # Use canonical name from DB (not whatever Gemini returned)
            canonical_name = fragrance_row["name"]

            if save_mention(
                canonical_name, text, sentiment,
                subreddit, username, specificity_score, reddit_url
            ):
                saved += 1
                print(f"    {sentiment} ({specificity_score}) → {canonical_name} (u/{username})")

    # Step 4: Recompute scores
    print("\n[4/4] Finalizing fragrance scores...")
    try:
        finalize_fragrance_scores()
    except Exception as e:
        print(f"  Score finalize failed: {e}")

    print("\n" + "=" * 60)
    print(f"  Mentions saved:        {saved}")
    print(f"  Skipped (filter):      {skip_filter}")
    print(f"  Skipped (no match):    {skip_no_match}")
    print("=" * 60)


if __name__ == "__main__":
    main()
