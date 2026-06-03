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

const GLOBAL_BRANDS = [
  'cetaphil','neutrogena','cerave','ponds','himalaya','biotique','dove',
  'garnier','loreal','nivea','olay','lakme','bioderma','minimalist',
  'fixderma','plum','mcaffeine','the ordinary','ordinary','klairs',
  'innisfree','cosrx','simple','dot & key','dot and key','foxtale',
  'the derma co','dr sheth','reequil','la roche-posay','la roche posay',
  'aqualogica','deconstruct','conscious chemist','chemist at play'
];

// ─── Pure helpers ─────────────────────────────────────────────────────
function slugify(s) {
  return String(s || '')
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

function timeAgo(d) {
  if (!d) return 'recently';

  const date = new Date(d);
  if (Number.isNaN(date.getTime())) return 'recently';

  const m = Math.floor((Date.now() - date.getTime()) / 60000);

  if (m < 1) return 'just now';
  if (m < 60) return m + 'm ago';

  const h = Math.floor(m / 60);
  if (h < 24) return h + 'h ago';

  const dd = Math.floor(h / 24);
  if (dd < 7) return dd + 'd ago';

  return Math.floor(dd / 7) + 'w ago';
}

function escapeHtml(s) {
  return String(s || '').replace(/[&<>"']/g, c => ({
    '&':'&amp;',
    '<':'&lt;',
    '>':'&gt;',
    '"':'&quot;',
    "'":'&#39;'
  }[c]));
}

function gradientForName(name) {
  let h = 0;

  for (let i = 0; i < name.length; i++) {
    h = (h * 31 + name.charCodeAt(i)) & 0xffffffff;
  }

  const [a, b] = GRADIENTS[Math.abs(h) % GRADIENTS.length];
  return `linear-gradient(135deg,${a} 0%,${b} 100%)`;
}

function getField(obj, preferredField, fallbackField) {
  if (!obj) return null;

  if (preferredField && obj[preferredField] !== undefined && obj[preferredField] !== null) {
    return obj[preferredField];
  }

  if (fallbackField && obj[fallbackField] !== undefined && obj[fallbackField] !== null) {
    return obj[fallbackField];
  }

  return null;
}

function getName(p, config) {
  return getField(p, config.nameField, 'name') || 'Unknown';
}

function getBrand(p, config) {
  return getField(p, config.brandField, 'brand') || '';
}

function getImageUrl(p, config) {
  return getField(p, config.imageField, 'image_url') || '';
}

function getCategoryLabel(p, config) {
  return (
    getField(p, config.typeField, 'product_category') ||
    p.cleanser_type ||
    p.product_category ||
    ''
  );
}

function getSkinType(p, config) {
  return (
    getField(p, config.skinTypeField, 'skin_type') ||
    p.skin_type ||
    ''
  );
}

function getPriceTier(p, config) {
  return (
    getField(p, config.priceTierField, 'price_tier') ||
    p.price_tier ||
    ''
  );
}

function getMentionCount(p, config) {
  return Number(getField(p, config.mentionCountField, 'mention_count') || 0);
}

function getPositiveCount(p, config) {
  return Number(getField(p, config.positiveCountField, 'positive_count') || 0);
}

function getNegativeCount(p, config) {
  return Number(getField(p, config.negativeCountField, 'negative_count') || 0);
}

function getUpdatedAt(p, config) {
  return (
    getField(p, config.updatedField, 'updated_at') ||
    p.last_scraped_at ||
    p.updated_at ||
    p.created_at ||
    null
  );
}

function getClearbitDomain(brand) {
  const b = String(brand || '').toLowerCase().trim();

  const knownDomains = {
    'cetaphil': 'cetaphil.com',
    'neutrogena': 'neutrogena.com',
    'cerave': 'cerave.com',
    'cera ve': 'cerave.com',
    'simple': 'simpleskincare.com',
    'bioderma': 'bioderma.com',
    'la roche-posay': 'laroche-posay.com',
    'la roche posay': 'laroche-posay.com',
    'minimalist': 'beminimalist.co',
    'plum': 'plumgoodness.com',
    'dot & key': 'dotandkey.com',
    'dot and key': 'dotandkey.com',
    'the derma co': 'thedermaco.com',
    'foxtale': 'foxtale.in',
    'dr. sheth\'s': 'drsheths.com',
    'dr sheths': 'drsheths.com',
    'dr sheth': 'drsheths.com',
    'reequil': 'reequil.com',
    're\'equil': 'reequil.com',
    'himalaya': 'himalayawellness.in',
    'garnier': 'garnier.in',
    'ponds': 'ponds.in',
    'pond\'s': 'ponds.in',
    'clean & clear': 'cleanandclear.com',
    'clean and clear': 'cleanandclear.com',
    'mamaearth': 'mamaearth.in',
    'aqualogica': 'aqualogica.in',
    'deconstruct': 'thedeconstruct.in',
    'conscious chemist': 'consciouschemist.com',
    'chemist at play': 'chemistatplay.com',
    'suganda': 'suganda.co',
    'earth rhythm': 'earthrhythm.com',
    'mcaffeine': 'mcaffeine.com',
    'pilgrim': 'discoverpilgrim.com',
    'cosrx': 'cosrx.com',
    'beauty of joseon': 'beautyofjoseon.com',
    'the face shop': 'thefaceshop.in',
    'innisfree': 'innisfree.com',
    'kaya': 'kaya.in',
    'forest essentials': 'forestessentialsindia.com',
    'kama ayurveda': 'kamaayurveda.in',
    'biotique': 'biotique.com',
    'good vibes': 'purplle.com',
    'dermdoc': 'purplle.com',
    'joy': 'joypersonalcare.com',
    'nivea': 'nivea.in',
    'lakme': 'lakmeindia.com',
    'wow skin science': 'buywow.in',
    'dove': 'dove.com',
    'avene': 'aveneusa.com',
    'klairs': 'klairscosmetics.com',
    'isntree': 'isntree.com'
  };

  if (knownDomains[b]) return knownDomains[b];

  return b.replace(/[^a-z0-9]/g, '') + '.com';
}

function buildProductImg(p, size, config) {
  const name = getName(p, config);
  const brand = getBrand(p, config);
  const imageUrl = getImageUrl(p, config);

  const letter = name.trim().charAt(0).toUpperCase() || '?';
  const grad = gradientForName(name || '');
  const brandLower = brand.toLowerCase().trim();
  const fontSize = size === 'large' ? '64px' : '20px';

  const fallbackOverlay = `<div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:${fontSize};font-weight:bold;color:white;background:${grad};border-radius:10px;z-index:-1;">${letter}</div>`;

  const plainFallback = `<div style="width:100%;height:100%;display:flex;align-items:center;justify-content:center;font-size:${fontSize};font-weight:bold;color:white;background:${grad};border-radius:10px;">${letter}</div>`;

  if (imageUrl) {
    return `<img src="${escapeHtml(imageUrl)}" style="width:100%;height:100%;object-fit:contain;padding:8px;" onerror="this.style.display='none'" alt="${escapeHtml(name)}">${fallbackOverlay}`;
  }

  const isGlobal = GLOBAL_BRANDS.some(b => brandLower.includes(b));

  if (isGlobal && brandLower) {
    const domain = getClearbitDomain(brandLower);

    return `<img src="https://logo.clearbit.com/${domain}" style="width:100%;height:100%;object-fit:contain;padding:8px;" onerror="this.style.display='none'" alt="${escapeHtml(name)}">${fallbackOverlay}`;
  }

  return plainFallback;
}

// Build best-available Amazon URL with affiliate tag.
// Uses ASIN for direct PRODUCT PAGE link if available, else falls back to a search URL.
function buildAmazonUrl(product, config) {
  const asin = String(product.amazon_asin || '').trim();

  if (asin) {
    return `${AMAZON_DOMAIN}/dp/${encodeURIComponent(asin)}?tag=${AMAZON_AFFILIATE_TAG}`;
  }

  const query = [getBrand(product, config), getName(product, config)]
    .filter(Boolean)
    .join(' ')
    .trim();

  return `${AMAZON_DOMAIN}/s?k=${encodeURIComponent(query)}&tag=${AMAZON_AFFILIATE_TAG}`;
}

function makeProductNameSet(products, config) {
  const names = new Set();

  products.forEach(product => {
    const mainName = getName(product, config);
    if (mainName) names.add(mainName.toLowerCase().trim());

    if (Array.isArray(product.aliases)) {
      product.aliases.forEach(alias => {
        if (alias) names.add(String(alias).toLowerCase().trim());
      });
    }

    if (Array.isArray(product.reddit_search_terms)) {
      product.reddit_search_terms.forEach(term => {
        if (term) names.add(String(term).toLowerCase().trim());
      });
    }
  });

  return names;
}

// ─── Main entry point — pages call this once ──────────────────────────
window.initComparePage = function(config) {
  const defaults = {
    table: 'products',

    nameField: 'name',
    brandField: 'brand',
    scoreField: 'score',
    mentionCountField: 'mention_count',
    positiveCountField: 'positive_count',
    negativeCountField: 'negative_count',
    imageField: 'image_url',
    affiliateField: 'affiliate_url',
    updatedField: 'updated_at',

    typeField: 'product_category',
    skinTypeField: 'skin_type',
    priceTierField: 'price_tier',

    useMentionsTable: true
  };

  config = {
    ...defaults,
    ...config
  };

  const required = ['title', 'slug', 'emoji'];

  for (const key of required) {
    if (!config[key]) {
      throw new Error(`initComparePage: missing required config "${key}"`);
    }
  }

  // Old pages using the products table still need filter.
  // New catalog pages like cleansers do not need filter.
  if (config.table === 'products' && !config.filter) {
    throw new Error('initComparePage: products table pages require a "filter" config');
  }

  const supabase = createClient(SUPABASE_URL, SUPABASE_KEY);
  let productsGlobal = [];

  // ─── PAGINATION STATE ───────────────────────────────────────────────
  const PAGE_SIZE = 15;
  let visibleProducts = PAGE_SIZE;

  function matchesCategory(p) {
    if (config.table !== 'products') return true;

    const cat = String(p.category || '').toLowerCase();
    const pcat = String(p.product_category || '').toLowerCase();

    return cat === 'skincare' && config.filter.test(pcat);
  }

  async function loadProducts() {
    let query = supabase
      .from(config.table)
      .select('*')
      .order(config.scoreField, { ascending: false, nullsFirst: false })
      .order(config.mentionCountField, { ascending: false, nullsFirst: false })
      .order(config.nameField, { ascending: true });

    // New catalog tables like cleansers/fragrances have is_active.
    if (config.table !== 'products') {
      query = query.eq('is_active', true);
    }

    const res = await query;

    if (res.error) {
      throw res.error;
    }

    return res.data || [];
  }

  async function loadMentions() {
    if (config.useMentionsTable === false) return [];

    const res = await supabase
      .from('mentions')
      .select('*')
      .order('created_at', { ascending: false });

    if (res.error) {
      console.warn('Mentions load failed:', res.error);
      return [];
    }

    return res.data || [];
  }

  function filterMentionsForProducts(allMentions, products) {
    if (!allMentions.length || !products.length) return [];

    const ids = new Set(products.map(p => String(p.id)));
    const nameSet = makeProductNameSet(products, config);

    return allMentions.filter(m => {
      if (m.product_id && ids.has(String(m.product_id))) return true;
      if (m.cleanser_id && ids.has(String(m.cleanser_id))) return true;

      const productName = String(m.product_name || '').toLowerCase().trim();

      if (productName && nameSet.has(productName)) return true;

      return false;
    });
  }

  async function loadAll() {
    const [allProducts, allMentions] = await Promise.all([
      loadProducts(),
      loadMentions()
    ]);

    productsGlobal = allProducts.filter(matchesCategory);

    const mentions = filterMentionsForProducts(allMentions, productsGlobal);

    renderHeader(mentions);
    renderSubreddits(mentions);
    renderProductList(productsGlobal);

    if (productsGlobal.length > 0) {
      renderFeatured(productsGlobal[0], 0);
    } else {
      renderFeatured(null, 0);
    }
  }

  // ─── FIXED: select by data-idx value, not DOM position ─────────────
  window.selectProduct = function(index) {
    document.querySelectorAll('.product-row[data-idx]').forEach(row => {
      const rowIdx = parseInt(row.dataset.idx, 10);
      const isFeatured = rowIdx === index;

      row.classList.toggle('featured', isFeatured);

      const rank = row.querySelector('.product-rank');
      if (rank) {
        rank.classList.toggle('rank-featured', isFeatured);
      }
    });

    renderFeatured(productsGlobal[index], index);
  };

  function renderHeader(mentions) {
    const metaCount = document.getElementById('metaCount');
    const metaPlural = document.getElementById('metaPlural');
    const metaUpdated = document.getElementById('metaUpdated');

    const totalMentionsFromProducts = productsGlobal.reduce((sum, product) => {
      return sum + getMentionCount(product, config);
    }, 0);

    const displayMentionCount = mentions.length > 0
      ? mentions.length
      : totalMentionsFromProducts;

    const latestMentionDate = mentions.length > 0
      ? mentions[0].created_at
      : null;

    const latestProductDate = productsGlobal
      .map(product => getUpdatedAt(product, config))
      .filter(Boolean)
      .sort()
      .at(-1);

    if (metaCount) {
      metaCount.textContent = displayMentionCount.toLocaleString('en-IN');
    }

    if (metaPlural) {
      metaPlural.textContent = displayMentionCount === 1 ? '' : 's';
    }

    if (metaUpdated) {
      metaUpdated.textContent = latestMentionDate
        ? timeAgo(latestMentionDate)
        : latestProductDate
          ? timeAgo(latestProductDate)
          : 'no mentions yet';
    }
  }

  function renderSubreddits(mentions) {
    const el = document.getElementById('subredditList');

    if (!el) return;

    const counts = {};

    mentions.forEach(m => {
      if (m.subreddit) {
        counts[m.subreddit] = (counts[m.subreddit] || 0) + 1;
      }
    });

    const sorted = Object.entries(counts).sort((a, b) => b[1] - a[1]);

    if (!sorted.length) {
      el.innerHTML = '<div class="skeleton-text">No Reddit mentions in this category yet. Catalog products are ready for matching when the scraper runs.</div>';
      return;
    }

    el.innerHTML = sorted.slice(0, 6).map(([sub, count]) => `
      <div class="subreddit-item">
        <div class="subreddit-icon">r/</div>
        <div class="subreddit-name">r/${escapeHtml(sub)}</div>
        <div class="subreddit-count">${count}</div>
      </div>
    `).join('');

    if (sorted.length > 6) {
      el.innerHTML += `<a class="view-all-link">Showing 6 of ${sorted.length} subreddits · View all</a>`;
    }
  }

  // ─── UPDATED: renders only visibleProducts slice + Show More button ─
  function renderProductList(products) {
    const el = document.getElementById('productList');

    if (!el) return;

    const lowerTitle = config.title.toLowerCase();

    if (!products.length) {
      el.innerHTML = `
        <div style="text-align:center;padding:40px 20px;color:var(--text-dim);">
          <div style="font-size:36px;margin-bottom:12px;">${config.emoji}</div>
          <strong style="color:var(--text);display:block;margin-bottom:6px;font-size:16px;">No ${escapeHtml(lowerTitle)} found yet</strong>
          <p style="font-size:13px;max-width:320px;margin:0 auto;">Check your Supabase table, RLS policy, and is_active values.</p>
        </div>
      `;
      return;
    }

    const visible = products.slice(0, visibleProducts);
    let html = visible.map((p, i) => productRow(p, i + 1, i === 0, i)).join('');

    // Skeleton padding only when total products < 5 AND we're showing all of them
    if (products.length < 5 && visibleProducts >= products.length) {
      for (let i = 0; i < 5 - products.length; i++) {
        html += `
          <div class="product-row skeleton">
            <div class="product-rank">${products.length + i + 1}</div>
            <div class="product-info">
              <div class="product-row-name skeleton-text">More products coming</div>
              <div class="product-row-meta">As we scan more Reddit reviews</div>
            </div>
            <div class="product-img">
              <div style="width:100%;height:100%;display:flex;align-items:center;justify-content:center;color:var(--text-muted);font-size:16px;">?</div>
            </div>
          </div>
        `;
      }
    }

    // Show More button
    if (visibleProducts < products.length) {
      const remaining = products.length - visibleProducts;
      html += `
        <button class="show-more-btn" onclick="showMoreProducts()">
          Show More (${remaining} remaining)
        </button>
      `;
    }

    el.innerHTML = html;
  }

  // ─── Show More handler ───────────────────────────────────────────────
  window.showMoreProducts = function() {
    visibleProducts += PAGE_SIZE;
    renderProductList(productsGlobal);
  };

  function productRow(p, rank, isFeatured, idx) {
    const pos = getPositiveCount(p, config);
    const neg = getNegativeCount(p, config);
    const total = getMentionCount(p, config);
    const neu = Math.max(0, total - pos - neg);
    const denom = pos + neu + neg;
    const pct = denom > 0 ? Math.round((pos / denom) * 100) : 0;

    const name = getName(p, config);
    const brand = getBrand(p, config);
    const category = getCategoryLabel(p, config);

    return `
      <div class="product-row${isFeatured ? ' featured' : ''}" data-idx="${idx}" onclick="selectProduct(${idx})">
        <div class="product-rank${isFeatured ? ' rank-featured' : ''}">${rank}</div>

        <div class="product-info">
          <div class="product-row-name">
            <div class="product-row-name-text">${escapeHtml(name || 'Unknown')}</div>
          </div>

          ${denom > 0 ? `
            <div class="sentiment-summary">
              <span class="positive-pill">${pct}% positive</span>
              <span class="user-count">of ${total} mention${total === 1 ? '' : 's'}</span>
            </div>
            <div class="sentiment-bar">
              <div class="pos" style="width:${(pos / denom) * 100}%"></div>
              <div class="neu" style="width:${(neu / denom) * 100}%"></div>
              <div class="neg" style="width:${(neg / denom) * 100}%"></div>
            </div>
          ` : `
            <div class="sentiment-summary">
              <span class="user-count">${total} mention${total === 1 ? '' : 's'} · awaiting sentiment</span>
            </div>
          `}

          <div class="product-row-meta">
            ${brand ? escapeHtml(brand) : ''}
            ${brand && category ? ' · ' : ''}
            ${category ? escapeHtml(category) : ''}
          </div>
        </div>

        <div class="product-img">${buildProductImg(p, 'small', config)}</div>
      </div>
    `;
  }

  function renderFeatured(product, rank) {
    const panel = document.getElementById('featuredPanel');

    if (!panel) return;

    if (!product) {
      panel.innerHTML = `
        <div class="empty-featured">
          <h3>No products yet</h3>
          <p>Check your Supabase table and public read policy.</p>
        </div>
      `;
      return;
    }

    const pos = getPositiveCount(product, config);
    const neg = getNegativeCount(product, config);
    const total = getMentionCount(product, config);
    const neu = Math.max(0, total - pos - neg);
    const denom = pos + neu + neg;

    const posPct = denom > 0 ? Math.round((pos / denom) * 100) : 0;
    const neuPct = denom > 0 ? Math.round((neu / denom) * 100) : 0;
    const negPct = denom > 0 ? Math.round((neg / denom) * 100) : 0;

    const pros = String(product.pros || '').split('\n').filter(x => x.trim());
    const cons = String(product.cons || '').split('\n').filter(x => x.trim());

    const name = getName(product, config);
    const brand = getBrand(product, config);
    const category = getCategoryLabel(product, config);
    const skinType = getSkinType(product, config);
    const priceTier = getPriceTier(product, config);
    const productSlug = product.slug || slugify(name);

    const affiliateUrl = getField(product, config.affiliateField, 'affiliate_url');

    const amazonUrl = affiliateUrl || buildAmazonUrl(product, config);
    const hasAsin = !!(product.amazon_asin && String(product.amazon_asin).trim());

    const ctaTitle = affiliateUrl ? 'View Product' : 'Buy on Amazon';
    const ctaSubtext = affiliateUrl
      ? 'View product →'
      : hasAsin
        ? 'View on Amazon →'
        : 'Find on Amazon →';

    panel.innerHTML = `
      <div class="featured-card">
        <div class="featured-top">
          <div class="featured-top-info">
            <div class="featured-rank-tag">Rank <strong>#${rank + 1}</strong></div>

            <div class="featured-name">${escapeHtml(name)}</div>

            <div class="featured-tags">
              ${category ? `<span class="featured-tag">${escapeHtml(category)}</span>` : ''}
              ${skinType ? `<span class="featured-tag neutral">${escapeHtml(skinType)}</span>` : '<span class="featured-tag neutral">All Skin Types</span>'}
              ${priceTier ? `<span class="featured-tag neutral">${escapeHtml(priceTier)}</span>` : ''}
            </div>

            ${brand ? `
              <div class="featured-desc">
                By <strong style="color:var(--text);">${escapeHtml(brand)}</strong> · ${total} Reddit mention${total === 1 ? '' : 's'} analyzed
              </div>
            ` : ''}
          </div>

          <div class="featured-img-wrap">${buildProductImg(product, 'large', config)}</div>
        </div>

        <div class="sentiment-card">
          <div class="sentiment-card-head">
            <div class="sentiment-card-title">Sentiment Score</div>
            <div class="sentiment-card-help">ⓘ How it works</div>
          </div>

          ${denom > 0 ? `
            <div class="sentiment-row">
              <span class="sentiment-emoji">👍</span>
              <div class="sentiment-bar-wrap">
                <div class="sentiment-bar-fill positive" style="width:${posPct}%"></div>
              </div>
              <span class="sentiment-count"><strong>${pos}</strong> (${posPct}%)</span>
            </div>

            <div class="sentiment-row">
              <span class="sentiment-emoji">😐</span>
              <div class="sentiment-bar-wrap">
                <div class="sentiment-bar-fill neutral" style="width:${neuPct}%"></div>
              </div>
              <span class="sentiment-count"><strong>${neu}</strong> (${neuPct}%)</span>
            </div>

            <div class="sentiment-row">
              <span class="sentiment-emoji">👎</span>
              <div class="sentiment-bar-wrap">
                <div class="sentiment-bar-fill negative" style="width:${negPct}%"></div>
              </div>
              <span class="sentiment-count"><strong>${neg}</strong> (${negPct}%)</span>
            </div>
          ` : `
            <div style="color:var(--text-muted);font-size:12px;text-align:center;">
              Sentiment data will appear as the scraper finds Reddit mentions.
            </div>
          `}
        </div>

        <div class="pros-cons-grid">
          <div class="pc-card">
            <div class="pc-title pros">Top Pros</div>
            ${
              pros.length > 0
                ? pros.map(p => `<div class="pc-quote pros">${escapeHtml(p)}</div>`).join('')
                : '<div class="pc-empty">AI summary generating soon.</div>'
            }
          </div>

          <div class="pc-card">
            <div class="pc-title cons">Top Cons</div>
            ${
              cons.length > 0
                ? cons.map(c => `<div class="pc-quote cons">${escapeHtml(c)}</div>`).join('')
                : '<div class="pc-empty">AI summary generating soon.</div>'
            }
          </div>
        </div>

        <div class="cta-row">
          <a href="${escapeHtml(amazonUrl)}" target="_blank" rel="sponsored nofollow noopener" class="amazon-cta">
            <div class="amazon-cta-icon">🛒</div>
            <div class="amazon-cta-text">
              <div class="amazon-cta-title">${ctaTitle}</div>
              <div class="amazon-cta-sub">${ctaSubtext}</div>
            </div>
          </a>

          <a href="/skincare/${config.slug}/${productSlug}" class="cta-primary">View full analysis →</a>
        </div>

        <p class="affiliate-disclosure">
          As an Amazon Associate, IndiaRecs earns from qualifying purchases. This doesn't affect our Reddit-based rankings.
        </p>
      </div>
    `;
  }

  loadAll().catch(err => {
    console.error('Load failed:', err);

    const productList = document.getElementById('productList');
    const featuredPanel = document.getElementById('featuredPanel');

    if (productList) {
      productList.innerHTML = `
        <div style="text-align:center;padding:40px;color:var(--text-dim);">
          Couldn't load data. Check console, Supabase RLS, table name, and field names.
        </div>
      `;
    }

    if (featuredPanel) {
      featuredPanel.innerHTML = `
        <div class="empty-featured">
          <h3>Could not load featured product</h3>
          <p>Check Supabase access and browser console.</p>
        </div>
      `;
    }
  });
};
