// Shared compare-page logic — pages call window.initComparePage(config) to bootstrap.

import { createClient } from 'https://esm.sh/@supabase/supabase-js@2';

// ─── Config: change these once, all pages benefit ─────────────────────
const SUPABASE_URL = 'https://hrhhznjfpstwuxdlwyhz.supabase.co';
const SUPABASE_KEY = 'sb_publishable_SG22UKcXlKJcDlX0QfEOiQ__0sCg5Lc';
const AMAZON_AFFILIATE_TAG = 'indiarecs-21';
const AMAZON_DOMAIN = 'https://www.amazon.in';

const GRADIENTS = [
  ['#ff6b35','#a855f7'], ['#06b96f','#3b82f6'], ['#f59e0b','#ec4899'],
  ['#a855f7','#3b82f6'], ['#e94560','#f59e0b'], ['#06b96f','#a855f7'],
];

const GLOBAL_BRANDS = ['cetaphil','neutrogena','cerave','ponds','himalaya','biotique','dove','garnier','loreal','nivea','olay','lakme','bioderma','minimalist','fixderma','plum','mcaffeine','the ordinary','ordinary','klairs','innisfree','cosrx'];

// ─── Pure helpers ─────────────────────────────────────────────────────
function slugify(s) {
  return String(s || '').toLowerCase().trim().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
}

function timeAgo(d) {
  if (!d) return 'recently';
  const m = Math.floor((Date.now() - new Date(d).getTime()) / 60000);
  if (m < 1) return 'just now';
  if (m < 60) return m + 'm ago';
  const h = Math.floor(m / 60);
  if (h < 24) return h + 'h ago';
  const dd = Math.floor(h / 24);
  if (dd < 7) return dd + 'd ago';
  return Math.floor(dd / 7) + 'w ago';
}

function escapeHtml(s) {
  return String(s || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function gradientForName(name) {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) & 0xffffffff;
  const [a, b] = GRADIENTS[Math.abs(h) % GRADIENTS.length];
  return `linear-gradient(135deg,${a} 0%,${b} 100%)`;
}

function buildProductImg(p, size) {
  const letter = (p.name || '?').trim().charAt(0).toUpperCase();
  const grad = gradientForName(p.name || '');
  const brand = (p.brand || '').toLowerCase().trim();
  const fontSize = size === 'large' ? '64px' : '20px';
  const fallback = `<div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:${fontSize};font-weight:bold;color:white;background:${grad};border-radius:10px;z-index:-1;">${letter}</div>`;
  const plainFallback = `<div style="width:100%;height:100%;display:flex;align-items:center;justify-content:center;font-size:${fontSize};font-weight:bold;color:white;background:${grad};border-radius:10px;">${letter}</div>`;

  if (p.image_url) {
    return `<img src="${escapeHtml(p.image_url)}" style="width:100%;height:100%;object-fit:contain;padding:8px;" onerror="this.style.display='none'" alt="${escapeHtml(p.name)}">${fallback}`;
  }
  const isGlobal = GLOBAL_BRANDS.some(b => brand.includes(b));
  if (isGlobal && brand) {
    const domain = brand.replace(/[^a-z0-9]/g, '') + '.com';
    return `<img src="https://logo.clearbit.com/${domain}" style="width:100%;height:100%;object-fit:contain;padding:8px;" onerror="this.style.display='none'" alt="${escapeHtml(p.name)}">${fallback}`;
  }
  return plainFallback;
}

function buildAmazonUrl(product) {
  const asin = (product.amazon_asin || '').trim();
  if (asin) return `${AMAZON_DOMAIN}/dp/${encodeURIComponent(asin)}?tag=${AMAZON_AFFILIATE_TAG}`;
  const query = [product.brand, product.name].filter(Boolean).join(' ').trim();
  return `${AMAZON_DOMAIN}/s?k=${encodeURIComponent(query)}&tag=${AMAZON_AFFILIATE_TAG}`;
}

// ─── Main entry point — pages call this once ──────────────────────────
window.initComparePage = function(config) {
  // Validate config — fail loud rather than render broken pages.
  const required = ['title', 'slug', 'filter', 'emoji'];
  for (const key of required) {
    if (!config[key]) throw new Error(`initComparePage: missing required config "${key}"`);
  }

  const supabase = createClient(SUPABASE_URL, SUPABASE_KEY);
  let productsGlobal = [];

  function matchesCategory(p) {
    const cat = (p.category || '').toLowerCase();
    const pcat = (p.product_category || '').toLowerCase();
    return cat === 'skincare' && config.filter.test(pcat);
  }

  async function loadAll() {
    const [productsRes, mentionsRes] = await Promise.all([
      supabase.from('products').select('*').order('score', { ascending: false }),
      supabase.from('mentions').select('*').order('created_at', { ascending: false })
    ]);
    const allProducts = productsRes.data || [];
    const allMentions = mentionsRes.data || [];

    productsGlobal = allProducts.filter(matchesCategory);
    const productNames = new Set(productsGlobal.map(p => p.name));
    const mentions = allMentions.filter(m => productNames.has(m.product_name));

    renderHeader(mentions);
    renderSubreddits(mentions);
    renderProductList(productsGlobal);
    if (productsGlobal.length > 0) renderFeatured(productsGlobal[0], 0);
  }

  window.selectProduct = function(index) {
    document.querySelectorAll('.product-row[data-idx]').forEach((row, i) => {
      row.classList.toggle('featured', i === index);
      const rank = row.querySelector('.product-rank');
      if (rank) rank.classList.toggle('rank-featured', i === index);
    });
    renderFeatured(productsGlobal[index], index);
  };

  function renderHeader(mentions) {
    document.getElementById('metaCount').textContent = mentions.length;
    document.getElementById('metaPlural').textContent = mentions.length === 1 ? '' : 's';
    document.getElementById('metaUpdated').textContent =
      mentions.length > 0 ? timeAgo(mentions[0].created_at) : 'no mentions yet';
  }

  function renderSubreddits(mentions) {
    const counts = {};
    mentions.forEach(m => { if (m.subreddit) counts[m.subreddit] = (counts[m.subreddit] || 0) + 1; });
    const sorted = Object.entries(counts).sort((a, b) => b[1] - a[1]);
    const el = document.getElementById('subredditList');
    if (!sorted.length) {
      el.innerHTML = '<div class="skeleton-text">No mentions in this category yet. Scraper runs weekly.</div>';
      return;
    }
    el.innerHTML = sorted.slice(0, 6).map(([sub, count]) => `
      <div class="subreddit-item">
        <div class="subreddit-icon">r/</div>
        <div class="subreddit-name">r/${escapeHtml(sub)}</div>
        <div class="subreddit-count">${count}</div>
      </div>`).join('');
    if (sorted.length > 6) {
      el.innerHTML += `<a class="view-all-link">Showing 6 of ${sorted.length} subreddits · View all</a>`;
    }
  }

  function renderProductList(products) {
    const el = document.getElementById('productList');
    const lowerTitle = config.title.toLowerCase();
    if (!products.length) {
      el.innerHTML = `
        <div style="text-align:center;padding:40px 20px;color:var(--text-dim);">
          <div style="font-size:36px;margin-bottom:12px;">${config.emoji}</div>
          <strong style="color:var(--text);display:block;margin-bottom:6px;font-size:16px;">No ${lowerTitle} discovered yet</strong>
          <p style="font-size:13px;max-width:320px;margin:0 auto;">Our scraper runs weekly. ${config.title} mentioned on Reddit will appear here.</p>
        </div>`;
      return;
    }
    let html = products.map((p, i) => productRow(p, i + 1, i === 0, i)).join('');
    if (products.length < 5) {
      for (let i = 0; i < 5 - products.length; i++) {
        html += `<div class="product-row skeleton">
          <div class="product-rank">${products.length + i + 1}</div>
          <div class="product-info">
            <div class="product-row-name skeleton-text">More products coming</div>
            <div class="product-row-meta">As we scan more Reddit reviews</div>
          </div>
          <div class="product-img"><div style="width:100%;height:100%;display:flex;align-items:center;justify-content:center;color:var(--text-muted);font-size:16px;">?</div></div>
        </div>`;
      }
    }
    el.innerHTML = html;
  }

  function productRow(p, rank, isFeatured, idx) {
    const pos = p.positive_count || 0;
    const neg = p.negative_count || 0;
    const total = p.mention_count || 0;
    const neu = Math.max(0, total - pos - neg);
    const denom = pos + neu + neg;
    const pct = denom > 0 ? Math.round((pos / denom) * 100) : 0;
    return `<div class="product-row${isFeatured ? ' featured' : ''}" data-idx="${idx}" onclick="selectProduct(${idx})">
      <div class="product-rank${isFeatured ? ' rank-featured' : ''}">${rank}</div>
      <div class="product-info">
        <div class="product-row-name"><div class="product-row-name-text">${escapeHtml(p.name || 'Unknown')}</div></div>
        ${denom > 0 ? `
          <div class="sentiment-summary">
            <span class="positive-pill">${pct}% positive</span>
            <span class="user-count">of ${total} mention${total === 1 ? '' : 's'}</span>
          </div>
          <div class="sentiment-bar">
            <div class="pos" style="width:${(pos/denom)*100}%"></div>
            <div class="neu" style="width:${(neu/denom)*100}%"></div>
            <div class="neg" style="width:${(neg/denom)*100}%"></div>
          </div>
        ` : `<div class="sentiment-summary"><span class="user-count">${total} mention${total === 1 ? '' : 's'} · awaiting sentiment</span></div>`}
        <div class="product-row-meta">${p.brand ? escapeHtml(p.brand) : ''}${p.brand && p.product_category ? ' · ' : ''}${p.product_category ? escapeHtml(p.product_category) : ''}</div>
      </div>
      <div class="product-img">${buildProductImg(p, 'small')}</div>
    </div>`;
  }

  function renderFeatured(product, rank) {
    const panel = document.getElementById('featuredPanel');
    if (!product) {
      panel.innerHTML = `<div class="empty-featured"><h3>No products yet</h3><p>Check back as the scraper finds ${config.title.toLowerCase()}.</p></div>`;
      return;
    }
    const pos = product.positive_count || 0;
    const neg = product.negative_count || 0;
    const total = product.mention_count || 0;
    const neu = Math.max(0, total - pos - neg);
    const denom = pos + neu + neg;
    const posPct = denom > 0 ? Math.round((pos / denom) * 100) : 0;
    const neuPct = denom > 0 ? Math.round((neu / denom) * 100) : 0;
    const negPct = denom > 0 ? Math.round((neg / denom) * 100) : 0;
    const pros = (product.pros || '').split('\n').filter(x => x.trim());
    const cons = (product.cons || '').split('\n').filter(x => x.trim());
    const productSlug = slugify(product.name);
    const amazonUrl = buildAmazonUrl(product);
    const hasAsin = !!(product.amazon_asin && String(product.amazon_asin).trim());
    const ctaSubtext = hasAsin ? 'View product on Amazon →' : 'Find on Amazon →';

    panel.innerHTML = `
      <div class="featured-card">
        <div class="featured-top">
          <div class="featured-top-info">
            <div class="featured-rank-tag">Rank <strong>#${rank + 1}</strong></div>
            <div class="featured-name">${escapeHtml(product.name)}</div>
            <div class="featured-tags">
              ${product.product_category ? `<span class="featured-tag">${escapeHtml(product.product_category)}</span>` : ''}
              ${product.skin_type ? `<span class="featured-tag neutral">${escapeHtml(product.skin_type)}</span>` : '<span class="featured-tag neutral">All Skin Types</span>'}
            </div>
            ${product.brand ? `<div class="featured-desc">By <strong style="color:var(--text);">${escapeHtml(product.brand)}</strong> · ${total} Reddit mention${total === 1 ? '' : 's'} analyzed</div>` : ''}
          </div>
          <div class="featured-img-wrap">${buildProductImg(product, 'large')}</div>
        </div>

        <div class="sentiment-card">
          <div class="sentiment-card-head">
            <div class="sentiment-card-title">Sentiment Score</div>
            <div class="sentiment-card-help">ⓘ How it works</div>
          </div>
          ${denom > 0 ? `
            <div class="sentiment-row">
              <span class="sentiment-emoji">👍</span>
              <div class="sentiment-bar-wrap"><div class="sentiment-bar-fill positive" style="width:${posPct}%"></div></div>
              <span class="sentiment-count"><strong>${pos}</strong> (${posPct}%)</span>
            </div>
            <div class="sentiment-row">
              <span class="sentiment-emoji">😐</span>
              <div class="sentiment-bar-wrap"><div class="sentiment-bar-fill neutral" style="width:${neuPct}%"></div></div>
              <span class="sentiment-count"><strong>${neu}</strong> (${neuPct}%)</span>
            </div>
            <div class="sentiment-row">
              <span class="sentiment-emoji">👎</span>
              <div class="sentiment-bar-wrap"><div class="sentiment-bar-fill negative" style="width:${negPct}%"></div></div>
              <span class="sentiment-count"><strong>${neg}</strong> (${negPct}%)</span>
            </div>
          ` : '<div style="color:var(--text-muted);font-size:12px;text-align:center;">Sentiment data appearing as we scan more mentions.</div>'}
        </div>

        <div class="pros-cons-grid">
          <div class="pc-card">
            <div class="pc-title pros">Top Pros</div>
            ${pros.length > 0 ? pros.map(p => `<div class="pc-quote pros">${escapeHtml(p)}</div>`).join('') : '<div class="pc-empty">AI summary generating soon.</div>'}
          </div>
          <div class="pc-card">
            <div class="pc-title cons">Top Cons</div>
            ${cons.length > 0 ? cons.map(c => `<div class="pc-quote cons">${escapeHtml(c)}</div>`).join('') : '<div class="pc-empty">AI summary generating soon.</div>'}
          </div>
        </div>

        <div class="amazon-cta-wrap">
          <a href="${amazonUrl}" target="_blank" rel="sponsored nofollow noopener" class="amazon-cta">
            <div class="amazon-cta-left">
              <div class="amazon-cta-icon">🛒</div>
              <div class="amazon-cta-text">
                <div class="amazon-cta-title">Buy on Amazon</div>
                <div class="amazon-cta-sub">${ctaSubtext}</div>
              </div>
            </div>
            <div class="amazon-cta-arrow">→</div>
          </a>
        </div>

        <div class="cta-primary-wrap">
          <a href="/skincare/${config.slug}/${productSlug}" class="cta-primary">View full analysis →</a>
        </div>

        <p class="affiliate-disclosure">As an Amazon Associate, IndiaRecs earns from qualifying purchases. This doesn't affect our Reddit-based rankings.</p>
      </div>`;
  }

  loadAll().catch(err => {
    console.error('Load failed:', err);
    document.getElementById('productList').innerHTML =
      `<div style="text-align:center;padding:40px;color:var(--text-dim);">Couldn't load data. Check console.</div>`;
  });
};
