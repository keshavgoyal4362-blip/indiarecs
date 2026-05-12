"""
One-time script to generate pros/cons summaries for cleanser products.
Run manually via GitHub Actions or add to scraper.py at end of main().
Uses Gemini to summarize mentions → saves to Supabase pros/cons columns.
"""

import os
import re
import time
import json
from supabase import create_client
import google.generativeai as genai

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
genai.configure(api_key=GEMINI_API_KEY)
gemini = genai.GenerativeModel("gemini-2.5-flash-lite")


def generate_pros_cons(product_name, mentions):
    corpus = "\n".join([
        f"[{m['sentiment']}] {(m['comment_text'] or '')[:300]}"
        for m in mentions
        if m.get('comment_text') and '[removed]' not in m['comment_text']
    ][:40])

    if not corpus.strip():
        return None, None

    prompt = f"""You are analyzing Reddit reviews of "{product_name}" from Indian skincare communities.

Based on these mentions, give exactly 3 pros and 3 cons as short bullet points (max 10 words each). Be specific, not generic. Focus on what Indian users actually said.

Mentions:
{corpus}

Respond ONLY with valid JSON, no markdown:
{{"pros":["...","...","..."],"cons":["...","...","..."]}}"""

    try:
        response = gemini.generate_content(prompt)
        time.sleep(6)
        clean = response.text.strip()
        clean = re.sub(r"^```(?:json)?", "", clean).strip()
        clean = re.sub(r"```$", "", clean).strip()
        result = json.loads(clean)
        pros = "\n".join(result.get("pros", []))
        cons = "\n".join(result.get("cons", []))
        return pros, cons
    except Exception as e:
        print(f"  Gemini error for {product_name}: {e}")
        return None, None


def main():
    print("Fetching cleanser products...")
    products = supabase.table("products").select("*").eq("category", "skincare").execute().data
    cleansers = [p for p in products if (p.get("product_category") or "").lower() == "cleanser"]
    print(f"Found {len(cleansers)} cleansers")

    all_mentions = supabase.table("mentions").select("*").execute().data

    for product in cleansers:
        name = product["name"]
        mentions = [m for m in all_mentions if m.get("product_name") == name]
        print(f"\n{name} — {len(mentions)} mentions")

        if len(mentions) < 2:
            print("  Skipping — not enough mentions")
            continue

        pros, cons = generate_pros_cons(name, mentions)
        if not pros and not cons:
            print("  Skipping — Gemini returned nothing")
            continue

        supabase.table("products").update({
            "pros": pros,
            "cons": cons
        }).eq("id", product["id"]).execute()
        print(f"  ✅ Saved pros/cons")
        print(f"  PROS: {pros}")
        print(f"  CONS: {cons}")

    print("\nDone.")


if __name__ == "__main__":
    main()
