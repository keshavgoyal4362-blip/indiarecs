import os
import re
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

# Indian skincare products to track
PRODUCTS = [
    "Minimalist", "Cetaphil", "Neutrogena", "Plum",
    "Dot & Key", "Mamaearth", "Lakme", "Biotique",
    "Forest Essentials", "Kama Ayurveda", "WOW",
    "MCaffeine", "The Derma Co", "Fixderma",
    "Sebamed", "CeraVe", "La Roche-Posay", "Innisfree",
    "Himalaya", "Garnier", "Lotus", "VLCC", "Jovees",
    "Nykaa Naturals", "mCaffeine", "Foxtale", "Pilgrim",
    "Anua", "Some By Mi", "Cosrx", "Bioderma",
    "Avene", "Ducray", "Vichy", "Kiehl's"
]

SUBREDDITS = [
    "IndianSkincareAddicts",
    "SkincareAddiction",
    "indianbeautyhauls",
    "AsianBeauty"
]

# Smart filter — only keep genuine review comments
def is_genuine_review(text):
    if not text or len(text.split()) < 15:
        return False

    text_lower = text.lower()

    # Filter out questions
    question_starters = [
        "where can", "where do", "which one",
        "can anyone", "does anyone", "has anyone tried",
        "what is", "what are", "how do", "how long",
        "is there", "are there", "should i", "would you"
    ]
    for q in question_starters:
        if text_lower.startswith(q):
            return False

    # Must contain experience signals
    experience_signals = [
        "i use", "i used", "been using", "i tried",
        "my skin", "works for me", "worked for me",
        "doesn't work", "did not work", "did not help",
        "i bought", "purchased", "repurchased", "i repurchase",
        "switched to", "my routine", "in my experience",
        "personally", "i have been", "i've been",
        "i noticed", "i saw", "i felt", "broke me out",
        "broke out", "cleared my", "helped my",
        "love this", "hate this", "would recommend",
        "would not recommend", "holy grail", "HG"
    ]

    has_experience = any(signal in text_lower for signal in experience_signals)
    return has_experience

# Gemini LLM classifier
def classify_with_gemini(product_name, comment_text):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"

    prompt = f"""You are analyzing Reddit comments about skincare products.

Product: {product_name}
Comment: {comment_text}

Answer these three questions in exactly this format:
IS_REVIEW: yes or no
SENTIMENT: positive or negative or neutral
SUMMARY: one sentence max describing what the person said about the product

Rules:
- IS_REVIEW is yes only if the person is sharing their own experience with this product
- IS_REVIEW is no if it is a question, comparison, or passing mention
- SENTIMENT is based only on what they say about this specific product
- SUMMARY should be blank if IS_REVIEW is no"""

    try:
        response = requests.post(url, json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 100}
        }, timeout=15)

        if response.status_code == 200:
            text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
            lines = text.strip().split("\n")
            result = {}
            for line in lines:
                if ":" in line:
                    key, val = line.split(":", 1)
                    result[key.strip()] = val.strip().lower()

            is_review = result.get("is_review", "no") == "yes"
            sentiment = result.get("sentiment", "neutral")
            summary = result.get("summary", "")

            if sentiment not in ["positive", "negative", "neutral"]:
                sentiment = "neutral"

            return is_review, sentiment, summary
        else:
            print(f"Gemini error: {response.status_code}")
            return False, "neutral", ""

    except Exception as e:
        print(f"Gemini exception: {e}")
        return False, "neutral", ""

# Fetch posts from Arctic Shift
def fetch_posts(subreddit, limit=100):
    url = f"https://arctic-shift.photon-reddit.com/api/posts/search?subreddit={subreddit}&limit={limit}&sort=new"
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        if response.status_code == 200:
            data = response.json()
            return data.get("data", [])
        else:
            print(f"Arctic Shift error for r/{subreddit}: {response.status_code}")
            return []
    except Exception as e:
        print(f"Fetch error: {e}")
        return []

# Fetch comments for a post
def fetch_comments(post_id, subreddit, limit=50):
    url = f"https://arctic-shift.photon-reddit.com/api/comments/search?link_id={post_id}&limit={limit}"
    try:
        time.sleep(0.5)
        response = requests.get(url, headers=HEADERS, timeout=15)
        if response.status_code == 200:
            data = response.json()
            return data.get("data", [])
        return []
    except Exception as e:
        print(f"Comment fetch error: {e}")
        return []

# Save mention to Supabase
def save_mention(product_name, comment_text, sentiment, subreddit, summary=""):
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
        print(f"Save mention error: {e}")

# Update product score in Supabase
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
            new_score = new_pos - new_neg

            requests.patch(
                f"{SUPABASE_URL}/rest/v1/products?name=eq.{requests.utils.quote(product_name)}",
                headers=SUPABASE_HEADERS,
                json={
                    "mention_count": new_mentions,
                    "positive_count": new_pos,
                    "negative_count": new_neg,
                    "score": new_score
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
        print(f"Update product error: {e}")

# Main scraper
def scrape_subreddit(subreddit, limit=100):
    print(f"\nScraping r/{subreddit}...")
    posts = fetch_posts(subreddit, limit)
    print(f"Found {len(posts)} posts")

    genuine_reviews = 0
    gemini_calls = 0

    for post in posts:
        post_id = post.get("id", "")
        title = post.get("title", "")
        selftext = post.get("selftext", "")

        # Check post title and body
        texts_to_check = []
        if title:
            texts_to_check.append(title)
        if selftext and selftext not in ["[removed]", "[deleted]", ""]:
            texts_to_check.append(selftext)

        # Fetch and check comments
        comments = fetch_comments(post_id, subreddit)
        for comment in comments:
            body = comment.get("body", "")
            if body and body not in ["[removed]", "[deleted]"]:
                texts_to_check.append(body)

        # Process each text
        for text in texts_to_check:
            for product in PRODUCTS:
                if product.lower() in text.lower():

                    # Step 1: Smart keyword filter
                    if not is_genuine_review(text):
                        continue

                    # Step 2: Gemini classification
                    print(f"  Gemini checking: {product} mention...")
                    is_review, sentiment, summary = classify_with_gemini(product, text)
                    gemini_calls += 1

                    if is_review:
                        save_mention(product, text, sentiment, subreddit, summary)
                        update_product(product, sentiment)
                        genuine_reviews += 1
                        print(f"  SAVED: {product} — {sentiment}")

                    # Small delay to avoid rate limiting
                    time.sleep(0.3)

    print(f"r/{subreddit} done — {genuine_reviews} genuine reviews saved, {gemini_calls} Gemini calls used")

if __name__ == "__main__":
    print("Starting IndiaRecs smart scraper...")
    print("Using Arctic Shift + Gemini AI filtering\n")

    for subreddit in SUBREDDITS:
        scrape_subreddit(subreddit, limit=50)
        time.sleep(2)

    print("\nAll done! Check your Supabase database and refresh your website.")
