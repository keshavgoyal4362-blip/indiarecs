import os
import time
import requests

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

HEADERS = {"User-Agent": "IndiaRecs/1.0 (research project)"}

SUPABASE_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=minimal"
}

PRODUCTS = [
    "Minimalist", "Cetaphil", "Neutrogena", "Plum",
    "Dot & Key", "Mamaearth", "Lakme", "Biotique",
    "Forest Essentials", "Kama Ayurveda", "WOW",
    "MCaffeine", "The Derma Co", "Fixderma",
    "Sebamed", "CeraVe", "La Roche-Posay", "Innisfree",
    "Himalaya", "Garnier", "Lotus", "VLCC", "Jovees",
    "Nykaa Naturals", "Foxtale", "Pilgrim",
    "Anua", "Some By Mi", "Cosrx", "Bioderma",
    "Avene", "Ducray", "Vichy", "Kiehl's"
]

SUBREDDITS = [
    "IndianSkincareAddicts",
    "SkincareAddiction",
    "indianbeautyhauls",
    "AsianBeauty"
]

BOTS = ["automoderator", "bot", "automod"]

def is_genuine_review(text):
    if not text or len(text.split()) < 15:
        return False
    text_lower = text.lower()
    question_starters = [
        "where can", "where do", "which one should",
        "can anyone recommend", "does anyone know",
        "has anyone tried", "what is", "how do i",
        "should i buy", "is there a"
    ]
    for q in question_starters:
        if text_lower.startswith(q):
            return False
    experience_signals = [
        "i use", "i used", "been using", "i tried",
        "my skin", "works for me", "worked for me",
        "doesn't work", "did not work", "i bought",
        "purchased", "repurchased", "switched to",
        "my routine", "in my experience", "personally",
        "i've been", "i noticed", "broke me out",
        "cleared my", "helped my", "love this",
        "hate this", "would recommend", "holy grail",
        "i apply", "i started", "after using"
    ]
    return any(signal in text_lower for signal in experience_signals)

def classify_with_gemini(product_name, comment_text):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    prompt = f"""You are analyzing Reddit comments about skincare products.

Product: {product_name}
Comment: {comment_text[:500]}

Answer in exactly this format:
IS_REVIEW: yes or no
SENTIMENT: positive or negative or neutral
SUMMARY: one sentence max

Rules:
- IS_REVIEW is yes only if the person shares their own experience with this product
- IS_REVIEW is no if it is a question, passing mention, or bot message
- SENTIMENT is based only on what they say about this specific product"""

    try:
        response = requests.post(url, json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 80}
        }, timeout=15)

        if response.status_code == 200:
            text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
            result = {}
            for line in text.strip().split("\n"):
                if ":" in line:
                    key, val = line.split(":", 1)
                    result[key.strip()] = val.strip().lower()
            is_review = result.get("is_review", "no") == "yes"
            sentiment = result.get("sentiment", "neutral")
            if sentiment not in ["positive", "negative", "neutral"]:
                sentiment = "neutral"
            return is_review, sentiment
        else:
            print(f"  Gemini error: {response.status_code} — {response.text[:100]}")
            return False, "neutral"
    except Exception as e:
        print(f"  Gemini exception: {e}")
        return False, "neutral"

def fetch_posts(subreddit, limit=100):
    url = f"https://arctic-shift.photon-reddit.com/api/posts/search?subreddit={subreddit}&limit={limit}"
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        print(f"  Posts API status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, dict):
                return data.get("data", [])
            elif isinstance(data, list):
                return data
        return []
    except Exception as e:
        print(f"  Fetch posts error: {e}")
        return []

def fetch_comments(subreddit, limit=200):
    url = f"https://arctic-shift.photon-reddit.com/api/comments/search?subreddit={subreddit}&limit={limit}"
    try:
        time.sleep(0.5)
        response = requests.get(url, headers=HEADERS, timeout=15)
        print(f"  Comments API status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, dict):
                return data.get("data", [])
            elif isinstance(data, list):
                return data
        return []
    except Exception as e:
        print(f"  Fetch comments error: {e}")
        return []

def save_mention(product_name, comment_text, sentiment, subreddit):
    try:
        requests.post(
            f"{SUPABASE_URL}/rest/v1/mentions",
            headers=SUPABASE_HEADERS,
            json={
                "product_name": product_name,
                "comment_text": comment_text[:600],
                "sentiment": sentiment,
                "subreddit": subreddit
            }
        )
    except Exception as e:
        print(f"  Save error: {e}")

def update_product(product_name, sentiment):
    try:
        res = requests.get(
            f"{SUPABASE_URL}/rest/v1/products?name=eq.{requests.utils.quote(product_name)}&select=*",
            headers=SUPABASE_HEADERS
        )
        data = res.json()
        if data:
            p = data[0]
            new_pos = p["positive_count"] + (1 if sentiment == "positive" else 0)
            new_neg = p["negative_count"] + (1 if sentiment == "negative" else 0)
            new_mentions = p["mention_count"] + 1
            requests.patch(
                f"{SUPABASE_URL}/rest/v1/products?name=eq.{requests.utils.quote(product_name)}",
                headers=SUPABASE_HEADERS,
                json={
                    "mention_count": new_mentions,
                    "positive_count": new_pos,
                    "negative_count": new_neg,
                    "score": new_pos - new_neg
                }
            )
        else:
            requests.post(
                f"{SUPABASE_URL}/rest/v1/products",
                headers=SUPABASE_HEADERS,
                json={
                    "name": product_name,
                    "category": "skincare",
                    "mention_count": 1,
                    "positive_count": 1 if sentiment == "positive" else 0,
                    "negative_count": 1 if sentiment == "negative" else 0,
                    "score": 1 if sentiment == "positive" else -1 if sentiment == "negative" else 0,
                    "skin_type": "all",
                    "product_category": "general",
                    "price_inr": 0,
                    "brand": product_name
                }
            )
    except Exception as e:
        print(f"  Update error: {e}")

def process_texts(texts, subreddit, source_type):
    genuine = 0
    for text in texts:
        if not text or text in ["[removed]", "[deleted]", ""]:
            continue
        author = text.get("author", "").lower() if isinstance(text, dict) else ""
        if any(bot in author for bot in BOTS):
            continue
        body = text.get("body", text.get("selftext", text.get("title", ""))) if isinstance(text, dict) else text
        if not body or body in ["[removed]", "[deleted]"]:
            continue
        for product in PRODUCTS:
            if product.lower() in body.lower():
                if not is_genuine_review(body):
                    continue
                print(f"  Gemini checking {product} in {source_type}...")
                is_review, sentiment = classify_with_gemini(product, body)
                if is_review:
                    save_mention(product, body, sentiment, subreddit)
                    update_product(product, sentiment)
                    genuine += 1
                    print(f"  SAVED: {product} — {sentiment}")
                time.sleep(0.3)
    return genuine

def scrape_subreddit(subreddit, limit=100):
    print(f"\nScraping r/{subreddit}...")
    total = 0

    posts = fetch_posts(subreddit, limit)
    print(f"  Found {len(posts)} posts")
    total += process_texts(posts, subreddit, "post")

    comments = fetch_comments(subreddit, limit * 2)
    print(f"  Found {len(comments)} comments")
    total += process_texts(comments, subreddit, "comment")

    print(f"  r/{subreddit} done — {total} genuine reviews saved")

if __name__ == "__main__":
    print("Starting IndiaRecs smart scraper...")
    print("Arctic Shift + Gemini AI filtering\n")
    for subreddit in SUBREDDITS:
        scrape_subreddit(subreddit, limit=50)
        time.sleep(2)
    print("\nAll done!")
