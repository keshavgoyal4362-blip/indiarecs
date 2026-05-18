"""
IndiaRecs — Generate Pros/Cons Summaries
Automatically processes ALL products in the database.
Add new products or categories and this script picks them up.
"""

import os
import re
import time
import json
from supabase import create_client
from google import genai

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

MIN_MENTIONS = 2
REGROWTH_FACTOR = 1.5
MAX_MENTIONS_FOR_PROMPT = 40
GEMINI_DELAY = 5
GEMINI_MODEL = "gemini-2.5-flash-lite"

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
gemini_client = genai.Client(api_key=GEMINI_API_KEY)


def generate_pros_cons(product_name, product_category, mentions):
    corpus = "\n".join([
        f"[{m['sentiment']}] {(m['comment_text'] or '')[:300]}"
        for m in mentions
        if m.get('comment_text') and '[removed]' not in m['comment_text']
    ][:MAX_MENTIONS_FOR_PROMPT])

    if not corpus.strip():
        return None, None

    category_hint = f" (category: {product_category})" if product_category else ""

    prompt = f"""You are analyzing Reddit reviews of "{product_name}"{category_hint} from Indian beauty/skincare communities.

Based on these user mentions, give exactly 3 pros and 3 cons as short bullet points (max 10 words each).

Rules:
- Be SPECIFIC — reference actual user experiences from the mentions
- Base pros on POSITIVE mentions, cons on NEGATIVE mentions
- Good example: "Controls oil for 6+ hours in humid weather"
- Bad example: "Good product" (too generic)
- If not enough negative mentions for 3 cons, note common concerns (price, availability, texture, fragrance)
- If not enough positive mentions for 3 pros, note what users found acceptable

Mentions:
{corpus}

Respond ONLY with valid JSON, no markdown, no explanation:
{{"pros":["...","...","..."],"cons":["...","...","..."]}}"""

    try:
        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
        )
        time.sleep(GEMINI_DELAY)

        clean = response.text.strip()
        clean = re.sub(r"^```(?:json)?", "", clean).strip()
        clean = re.sub(r"```$", "", clean).strip()
        result = json.loads(clean)

        pros = "\n".join(result.get("pros", []))
        cons = "\n".join(result.get("cons", []))
        return pros, cons

    except Exception as e:
        if "429" in str(e) or "quota" in str(e).lower():
            print(f"  ⚠️  Gemini quota hit — stopping early.")
            return "QUOTA_HIT", None
        print(f"  Gemini error for {product_name}: {e}")
        return None, None


def should_generate(product, mention_count):
    if mention_count < MIN_MENTIONS:
        return False

    has_existing = bool((product.get("pros") or "").strip() or (product.get("cons") or "").strip())

    if not has_existing:
        return True

    last_known = product.get("pros_generated_at_mentions") or product.get("mention_count") or 0
    if last_known > 0 and mention_count >= last_known * REGROWTH_FACTOR:
        return True

    return False


def main():
    print("=" * 60)
    print("IndiaRecs — Generate Pros/Cons")
    print("=" * 60)

    print("\n[1/3] Fetching all products...")
    products = supabase.table("products").select("*").execute().data
    print(f"  Found {len(products)} products")

    print("\n[2/3] Fetching all mentions...")
    all_mentions = supabase.table("mentions").select(
        "product_name, comment_text, sentiment"
    ).execute().data
    print(f"  Found {len(all_mentions)} mentions")

    mentions_by_product = {}
    for m in all_mentions:
        pn = m.get("product_name")
        if pn:
            mentions_by_product.setdefault(pn, []).append(m)

    print("\n[3/3] Generating summaries...")
    generated = 0
    skipped = 0
    failed = 0
    quota_hit = False

    products_sorted = sorted(
        products,
        key=lambda p: len(mentions_by_product.get(p["name"], [])),
        reverse=True
    )

    for product in products_sorted:
        name = product["name"]
        product_category = product.get("product_category") or ""
        mentions = mentions_by_product.get(name, [])
        mention_count = len(mentions)

        if not should_generate(product, mention_count):
            skipped += 1
            continue

        print(f"\n  📝 {name} [{product_category}] ({mention_count} mentions)")

        pros, cons = generate_pros_cons(name, product_category, mentions)

        if pros == "QUOTA_HIT":
            quota_hit = True
            break

        if not pros and not cons:
            print(f"    ❌ Gemini returned nothing")
            failed += 1
            continue

        try:
            supabase.table("products").update({
                "pros": pros,
                "cons": cons,
                "pros_generated_at_mentions": mention_count,
            }).eq("id", product["id"]).execute()

            generated += 1
            print(f"    ✅ Saved")
            print(f"       PROS: {pros}")
            print(f"       CONS: {cons}")

        except Exception as e:
            print(f"    ❌ Save failed: {e}")
            failed += 1

    print("\n" + "=" * 60)
    print(f"  Generated:  {generated}")
    print(f"  Skipped:    {skipped}")
    print(f"  Failed:     {failed}")
    if quota_hit:
        print(f"  ⚠️  Stopped early due to Gemini quota limit")
    print("=" * 60)


if __name__ == "__main__":
    main()
