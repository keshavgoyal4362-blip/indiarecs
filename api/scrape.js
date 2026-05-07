export default async function handler(req, res) {

  const SUPABASE_URL = "https://hrhhznjfpstwuxdlwyhz.supabase.co";
  const SUPABASE_KEY = "sb_publishable_SG22UKcXlKJcDlX0QfEOiQ__0sCg5Lc";
  const ARCTIC_BASE = "https://arctic-shift.photon-reddit.com/api";

  const PRODUCTS = [
    { name: "Minimalist Niacinamide 10%", searchTerms: ["minimalist niacinamide", "minimalist 10%"], brand: "Minimalist", product_category: "serum", skin_type: "oily", price_inr: 599 },
    { name: "Cetaphil Gentle Cleanser", searchTerms: ["cetaphil cleanser", "cetaphil gentle"], brand: "Cetaphil", product_category: "cleanser", skin_type: "sensitive", price_inr: 399 },
    { name: "Neutrogena Sunscreen SPF 50", searchTerms: ["neutrogena sunscreen", "neutrogena ultra sheer"], brand: "Neutrogena", product_category: "sunscreen", skin_type: "combination", price_inr: 349 },
    { name: "Dot & Key Vitamin C Serum", searchTerms: ["dot and key vitamin c", "dot & key vitamin"], brand: "Dot & Key", product_category: "serum", skin_type: "dry", price_inr: 695 },
    { name: "Plum Green Tea Toner", searchTerms: ["plum green tea toner", "plum toner"], brand: "Plum", product_category: "toner", skin_type: "oily", price_inr: 315 },
  ];

  const POSITIVE_WORDS = ["love", "great", "amazing", "excellent", "perfect", "good", "best", "recommend", "works", "effective", "holy grail", "repurchase", "gentle", "lightweight", "glowing", "cleared", "improved", "favourite", "favorite", "nice", "smooth", "hydrated", "worth", "no breakout", "no purging"];
  const NEGATIVE_WORDS = ["hate", "terrible", "awful", "bad", "worst", "broke me out", "breakout", "irritation", "burning", "sticky", "greasy", "waste", "disappointed", "doesn't work", "didn't work", "avoid", "rash", "allergic", "pilling", "white cast", "purging", "stings", "not worth"];

  const SUBREDDIT = "IndianSkincareAddicts";

  const results = {};
  const mentionsToInsert = [];

  for (const product of PRODUCTS) {
    results[product.name] = { positive: 0, negative: 0, mentions: 0 };
  }

  for (const product of PRODUCTS) {
    for (const term of product.searchTerms) {
      try {
        // Search comments by keyword
        const commentUrl = `${ARCTIC_BASE}/comments/search?subreddit=${SUBREDDIT}&body=${encodeURIComponent(term)}&limit=100&sort=desc`;
        const commentRes = await fetch(commentUrl);
        const commentData = await commentRes.json();
        const comments = commentData.data || [];

        for (const comment of comments) {
          const text = (comment.body || "").toLowerCase();
          if (!text || text === "[deleted]" || text === "[removed]") continue;

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
            subreddit: SUBREDDIT,
            created_at: new Date().toISOString(),
          });
        }

        // Search post titles by keyword
        const postUrl = `${ARCTIC_BASE}/posts/search?subreddit=${SUBREDDIT}&title=${encodeURIComponent(term)}&limit=100&sort=desc`;
        const postRes = await fetch(postUrl);
        const postData = await postRes.json();
        const posts = postData.data || [];

        for (const post of posts) {
          const text = ((post.title || "") + " " + (post.selftext || "")).toLowerCase();
          if (!text.trim()) continue;

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
            subreddit: SUBREDDIT,
            created_at: new Date().toISOString(),
          });
        }

      } catch (e) {
        console.error(`Error fetching "${term}":`, e.message);
      }
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
