export default async function handler(req, res) {

  const SUPABASE_URL = "https://hrhhznjfpstwuxdlwyhz.supabase.co";
  const SUPABASE_KEY = "sb_publishable_SG22UKcXlKJcDlX0QfEOiQ__0sCg5Lc";
  const ARCTIC_BASE = "https://arctic-shift.photon-reddit.com/api";

  const PRODUCTS = [
    { name: "Minimalist Niacinamide 10%", keywords: ["minimalist niacinamide", "minimalist 10%", "minimalist niacin"], brand: "Minimalist", product_category: "serum", skin_type: "oily", price_inr: 599 },
    { name: "Cetaphil Gentle Cleanser", keywords: ["cetaphil gentle", "cetaphil cleanser", "cetaphil wash", "cetaphil"], brand: "Cetaphil", product_category: "cleanser", skin_type: "sensitive", price_inr: 399 },
    { name: "Neutrogena Sunscreen SPF 50", keywords: ["neutrogena sunscreen", "neutrogena spf", "neutrogena ultra sheer", "neutrogena"], brand: "Neutrogena", product_category: "sunscreen", skin_type: "combination", price_inr: 349 },
    { name: "Dot & Key Vitamin C Serum", keywords: ["dot & key vitamin c", "dot and key vitamin c", "dot & key"], brand: "Dot & Key", product_category: "serum", skin_type: "dry", price_inr: 695 },
    { name: "Plum Green Tea Toner", keywords: ["plum green tea toner", "plum toner", "plum green tea", "plum skincare"], brand: "Plum", product_category: "toner", skin_type: "oily", price_inr: 315 },
  ];

  const POSITIVE_WORDS = ["love", "great", "amazing", "excellent", "perfect", "good", "best", "recommend", "works", "effective", "holy grail", "repurchase", "gentle", "lightweight", "glowing", "cleared", "improved", "favourite", "favorite", "nice", "smooth", "hydrated", "worth", "non-comedogenic", "no breakout", "no purging"];
  const NEGATIVE_WORDS = ["hate", "terrible", "awful", "bad", "worst", "broke me out", "breakout", "irritation", "burning", "sticky", "greasy", "waste", "disappointed", "doesn't work", "didn't work", "avoid", "rash", "allergic", "pilling", "white cast", "purging", "stings", "too heavy", "not worth"];

  const SUBREDDITS = ["IndianSkincareAddicts", "SkincareAddiction", "AsianBeauty", "tretinoin"];

  const results = {};
  const mentionsToInsert = [];

  for (const product of PRODUCTS) {
    results[product.name] = { positive: 0, negative: 0, mentions: 0 };
  }

  // Search COMMENTS
  for (const subreddit of SUBREDDITS) {
    try {
      const url = `${ARCTIC_BASE}/comments/search?subreddit=${subreddit}&limit=500&sort=desc`;
      const response = await fetch(url);
      const data = await response.json();
      const comments = data.data || [];

      for (const comment of comments) {
        const text = (comment.body || "").toLowerCase();
        if (!text || text === "[deleted]" || text === "[removed]") continue;

        for (const product of PRODUCTS) {
          const mentioned = product.keywords.some(kw => text.includes(kw.toLowerCase()));
          if (!mentioned) continue;

          results[product.name].mentions++;
          const posScore = POSITIVE_WORDS.filter(w => text.includes(w)).length;
          const negScore = NEGATIVE_WORDS.filter(w => text.includes(w)).length;
          let sentiment = "neutral";
          if (posScore > negScore) { sentiment = "positive"; results[product.name].positive++; }
          else if (negScore > posScore) { sentiment = "negative"; results[product.name].negative++; }

          mentionsToInsert.push({
            product_name: product.name,
            comment_text: comment.body.slice(0, 500),
            sentiment,
            subreddit,
            created_at: new Date().toISOString(),
          });
        }
      }
    } catch (e) {
      console.error(`Error fetching comments from ${subreddit}:`, e.message);
    }
  }

  // Search POSTS (titles + selftext)
  for (const subreddit of SUBREDDITS) {
    try {
      const url = `${ARCTIC_BASE}/posts/search?subreddit=${subreddit}&limit=500&sort=desc`;
      const response = await fetch(url);
      const data = await response.json();
      const posts = data.data || [];

      for (const post of posts) {
        const text = ((post.title || "") + " " + (post.selftext || "")).toLowerCase();
        if (!text.trim()) continue;

        for (const product of PRODUCTS) {
          const mentioned = product.keywords.some(kw => text.includes(kw.toLowerCase()));
          if (!mentioned) continue;

          results[product.name].mentions++;
          const posScore = POSITIVE_WORDS.filter(w => text.includes(w)).length;
          const negScore = NEGATIVE_WORDS.filter(w => text.includes(w)).length;
          let sentiment = "neutral";
          if (posScore > negScore) { sentiment = "positive"; results[product.name].positive++; }
          else if (negScore > posScore) { sentiment = "negative"; results[product.name].negative++; }

          mentionsToInsert.push({
            product_name: product.name,
            comment_text: (post.title + ": " + (post.selftext || "")).slice(0, 500),
            sentiment,
            subreddit,
            created_at: new Date().toISOString(),
          });
        }
      }
    } catch (e) {
      console.error(`Error fetching posts from ${subreddit}:`, e.message);
    }
  }

  // Save mentions to Supabase
  if (mentionsToInsert.length > 0) {
    await fetch(`${SUPABASE_URL}/rest/v1/mentions`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "apikey": SUPABASE_KEY,
        "Authorization": `Bearer ${SUPABASE_KEY}`,
        "Prefer": "resolution=ignore-duplicates",
      },
      body: JSON.stringify(mentionsToInsert),
    });
  }

  // Update products table
  for (const product of PRODUCTS) {
    const r = results[product.name];
    const score = r.positive - r.negative;

    await fetch(`${SUPABASE_URL}/rest/v1/products?name=eq.${encodeURIComponent(product.name)}`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        "apikey": SUPABASE_KEY,
        "Authorization": `Bearer ${SUPABASE_KEY}`,
        "Prefer": "return=minimal",
      },
      body: JSON.stringify({
        mention_count: r.mentions,
        positive_count: r.positive,
        negative_count: r.negative,
        score,
      }),
    });
  }

  res.status(200).json({
    message: "Scrape complete!",
    summary: results,
    mentions_saved: mentionsToInsert.length,
  });
}
