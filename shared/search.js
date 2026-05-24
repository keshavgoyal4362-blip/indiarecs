// ═══════════════════════════════════════════════════════════════
// SHARED SEARCH MODULE
// Used by: every page that includes the nav (homepage, category pages,
// product pages). Powers the nav search bar (.nav-search input) and
// optionally a hero search bar if one exists on the page.
//
// Usage: <script type="module" src="/shared/search.js"></script>
//        Place AFTER <script src="/shared/nav.js"></script>
// ═══════════════════════════════════════════════════════════════

import { createClient } from 'https://esm.sh/@supabase/supabase-js@2';

const SUPABASE_URL = 'https://hrhhznjfpstwuxdlwyhz.supabase.co';
const SUPABASE_KEY = 'sb_publishable_SG22UKcXlKJcDlX0QfEOiQ__0sCg5Lc';
const supabase = createClient(SUPABASE_URL, SUPABASE_KEY);

// Single source of truth for categories. Must stay aligned with
// homepage and compare-page filters so all pages agree.
const CATEGORIES = [
  { name: 'Cleanser',         icon: '🧴', cls: 'skincare',  href: '/skincare/cleansers',     filter: /cleans|face\s?wash/ },
  { name: 'Moisturizer',      icon: '💧', cls: 'skincare',  href: '/skincare/moisturizers',  filter: /moistur|cream|lotion|hydrat/ },
  { name: 'Sunscreen',        icon: '☀️', cls: 'suncare',   href: '/skincare/sunscreens',    filter: /sunscreen|spf|sun\s?block/ },
  { name: 'Serum',            icon: '✨', cls: 'skincare',  href: '/skincare/serums',        filter: /serum|essence|ampoule|concentrate/ },
  { name: 'Shampoo',          icon: '🫧', cls: 'haircare',  href: '/haircare/shampoos',      filter: /shampoo/ },
  { name: 'Conditioner',      icon: '💆', cls: 'haircare',  href: '/haircare/conditioners',  filter: /conditioner/ },
  { name: 'Wireless Earbuds', icon: '🎧', cls: 'audio',     href: '/audio/wireless-earbuds', filter: /earbud|tws/ },
  { name: 'Headphones',       icon: '🎶', cls: 'audio',     href: '/audio/headphones',       filter: /headphone|over[\s-]?ear/ },
  { name: 'IEMs',             icon: '🎵', cls: 'audio',     href: '/audio/iems',             filter: /iem|in[\s-]?ear/ },
  { name: 'Fragrances',       icon: '🌸', cls: 'fragrance', href: '/fragrances/under-2000',  filter: /fragrance|perfume|cologne|edp|edt/ }
];

// Module-scope cache so search runs against in-memory data
// (no DB round-trip per keystroke).
let ALL_PRODUCTS = [];
let productsLoaded = false;

// Inject minimal CSS for the dropdown so this works on any page
// even if the page-specific stylesheet doesn't define these classes.
function injectStyles() {
  if (document.getElementById('shared-search-styles')) return;
  const style = document.createElement('style');
  style.id = 'shared-search-styles';
  style.textContent = `
    .search-dropdown{display:none;position:absolute;top:100%;left:0;right:0;margin-top:6px;background:var(--nav-surface,#141414);border:1px solid var(--nav-border,#222);border-radius:12px;padding:6px;max-height:420px;overflow-y:auto;z-index:250;box-shadow:0 12px 40px rgba(0,0,0,.5)}
    .search-dropdown.show{display:block}
    .search-dropdown-section{padding:8px 12px 4px;font-size:10px;color:var(--nav-text-muted,#666);text-transform:uppercase;letter-spacing:.7px;font-weight:bold}
    .search-result{display:flex;align-items:center;gap:12px;padding:8px 10px;border-radius:8px;cursor:pointer;transition:background .1s}
    .search-result:hover,.search-result.kb-active{background:var(--nav-surface-2,#1a1a1a)}
    .search-result-img{width:34px;height:34px;border-radius:8px;flex-shrink:0;overflow:hidden;display:flex;align-items:center;justify-content:center;background:var(--nav-surface-2,#1a1a1a)}
    .search-result-img img{width:100%;height:100%;object-fit:cover}
    .search-result-img-fallback{width:100%;height:100%;display:flex;align-items:center;justify-content:center;font-size:14px;font-weight:bold;color:white;background:linear-gradient(135deg,#ff6b35,#a855f7)}
    .search-result-img-cat{width:100%;height:100%;display:flex;align-items:center;justify-content:center;font-size:16px}
    .search-result-info{min-width:0;flex:1}
    .search-result-name{font-size:12.5px;font-weight:bold;color:var(--nav-text,#f5f5f5);margin-bottom:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .search-result-meta{font-size:10.5px;color:var(--nav-text-dim,#999);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .search-empty{padding:24px 16px;text-align:center;color:var(--nav-text-muted,#666);font-size:12px}
    .search-loading{padding:20px;text-align:center;color:var(--nav-text-muted,#666);font-size:12px}
  `;
  document.head.appendChild(style);
}

// Lazy-load products on first search interaction so we don't hit the
// DB on pages where the user never touches the search bar.
async function ensureProductsLoaded() {
  if (productsLoaded) return;
  const { data, error } = await supabase
    .from('products')
    .select('*')
    .order('score', { ascending: false });
  if (error) {
    console.error('Search: failed to load products', error);
    return;
  }
  ALL_PRODUCTS = data || [];
  productsLoaded = true;
}

// Find which category a product belongs to (used for routing clicks).
function findCategoryForProduct(p) {
  const haystack = `${p.product_category || ''} ${p.category || ''}`.toLowerCase();
  return CATEGORIES.find(c => c.filter.test(haystack));
}

// Resolve product click destination. No product detail pages yet,
// so we route to the product's category page.
function productLink(p) {
  const cat = findCategoryForProduct(p);
  return cat ? cat.href : '#';
}

function initial(n) { return (n || '?').trim().charAt(0).toUpperCase(); }

// Always escape user-controlled strings before innerHTML.
function escapeHtml(s) {
  return String(s || '').replace(/[&<>"']/g, c =>
    ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c])
  );
}

// Build combined results: categories first, then products.
// Products ranked: name-prefix > name-contains > brand-contains.
function buildResults(q) {
  const catMatches = CATEGORIES
    .filter(c => c.name.toLowerCase().includes(q))
    .map(c => ({ type: 'category', data: c }));

  const scored = [];
  for (const p of ALL_PRODUCTS) {
    const name = (p.name || '').toLowerCase();
    const brand = (p.brand || '').toLowerCase();
    let rank = -1;
    if (name.startsWith(q)) rank = 0;
    else if (name.includes(q)) rank = 1;
    else if (brand.includes(q)) rank = 2;
    if (rank >= 0) scored.push({ rank, product: p });
  }
  scored.sort((a, b) => {
    if (a.rank !== b.rank) return a.rank - b.rank;
    return (b.product.score || 0) - (a.product.score || 0);
  });

  return {
    categories: catMatches.slice(0, 5),
    products: scored.slice(0, 8).map(s => ({ type: 'product', data: s.product }))
  };
}

function renderCategoryResult(cat) {
  return `<div class="search-result" data-href="${cat.href}">
    <div class="search-result-img"><div class="search-result-img-cat">${cat.icon}</div></div>
    <div class="search-result-info">
      <div class="search-result-name">${escapeHtml(cat.name)}</div>
      <div class="search-result-meta">Browse category</div>
    </div>
  </div>`;
}

function renderProductResult(p) {
  const href = productLink(p);
  const img = p.image_url
    ? `<img src="${escapeHtml(p.image_url)}" alt="${escapeHtml(p.brand || '')}">`
    : `<div class="search-result-img-fallback">${initial(p.name)}</div>`;
  const meta = [p.brand, p.product_category || p.category]
    .filter(Boolean).map(escapeHtml).join(' · ');
  return `<div class="search-result" data-href="${href}">
    <div class="search-result-img">${img}</div>
    <div class="search-result-info">
      <div class="search-result-name">${escapeHtml(p.name || 'Unknown')}</div>
      <div class="search-result-meta">${meta || 'Product'}</div>
    </div>
  </div>`;
}

function renderResults(dropdown, results, q) {
  const hasAny = results.categories.length || results.products.length;
  if (!hasAny) {
    dropdown.innerHTML = `<div class="search-empty">No matches for "<strong>${escapeHtml(q)}</strong>"</div>`;
    return;
  }
  let html = '';
  if (results.categories.length) {
    html += `<div class="search-dropdown-section">Categories</div>`;
    html += results.categories.map(r => renderCategoryResult(r.data)).join('');
  }
  if (results.products.length) {
    html += `<div class="search-dropdown-section">Products</div>`;
    html += results.products.map(r => renderProductResult(r.data)).join('');
  }
  dropdown.innerHTML = html;

  // Wire clicks via addEventListener (avoids escaping pitfalls in URLs).
  dropdown.querySelectorAll('.search-result').forEach(el => {
    el.addEventListener('click', () => {
      const href = el.getAttribute('data-href');
      if (href && href !== '#') window.location.href = href;
    });
  });
}

// Attach search behavior to a single input/dropdown pair.
// Debouncing avoids re-running the filter on every keystroke.
function attachSearch(input, dropdown) {
  if (input.dataset.searchAttached === 'true') return; // idempotent
  input.dataset.searchAttached = 'true';

  let timer = null;
  let activeIdx = -1;

  const run = async () => {
    const q = input.value.trim().toLowerCase();
    if (!q) { dropdown.classList.remove('show'); dropdown.innerHTML = ''; return; }

    // Show loading state on first interaction while products load.
    if (!productsLoaded) {
      dropdown.innerHTML = `<div class="search-loading">Searching…</div>`;
      dropdown.classList.add('show');
      await ensureProductsLoaded();
      // User may have changed input during load — re-read.
      if (input.value.trim().toLowerCase() !== q) return;
    }

    const results = buildResults(q);
    activeIdx = -1;
    renderResults(dropdown, results, q);
    dropdown.classList.add('show');
  };

  input.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(run, 150);
  });

  input.addEventListener('focus', () => {
    if (input.value.trim()) run();
  });

  input.addEventListener('keydown', (e) => {
    const items = dropdown.querySelectorAll('.search-result');
    if (!items.length) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      activeIdx = Math.min(activeIdx + 1, items.length - 1);
      updateActive(items);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      activeIdx = Math.max(activeIdx - 1, 0);
      updateActive(items);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const target = activeIdx >= 0 ? items[activeIdx] : items[0];
      if (target) {
        const href = target.getAttribute('data-href');
        if (href && href !== '#') window.location.href = href;
      }
    } else if (e.key === 'Escape') {
      dropdown.classList.remove('show');
      input.blur();
    }
  });

  function updateActive(items) {
    items.forEach((it, i) => it.classList.toggle('kb-active', i === activeIdx));
    if (activeIdx >= 0) items[activeIdx].scrollIntoView({ block: 'nearest' });
  }
}

// Find any search input on the page and attach behavior. Polls briefly
// because nav.js may inject the nav DOM asynchronously.
function init() {
  injectStyles();

  // Click outside any open dropdown closes it.
  document.addEventListener('click', (e) => {
    document.querySelectorAll('.search-dropdown.show').forEach(dd => {
      if (!dd.contains(e.target) && !dd.parentElement.contains(e.target)) {
        dd.classList.remove('show');
      }
    });
  });

  // Attach to every .nav-search input (works whether nav.js is sync or async).
  let tries = 0;
  const tryAttach = () => {
    let attached = 0;
    document.querySelectorAll('.nav-search').forEach(wrap => {
      const input = wrap.querySelector('input');
      if (!input) return;
      let dropdown = wrap.querySelector('.search-dropdown');
      if (!dropdown) {
        dropdown = document.createElement('div');
        dropdown.className = 'search-dropdown';
        wrap.appendChild(dropdown);
      }
      attachSearch(input, dropdown);
      attached++;
    });

    // Also attach to any explicit hero search on the page (e.g. homepage).
    const heroInput = document.getElementById('heroSearch');
    const heroDropdown = document.getElementById('heroSearchDropdown');
    if (heroInput && heroDropdown) {
      attachSearch(heroInput, heroDropdown);
      attached++;
    }

    // Keep polling for ~2 seconds in case nav.js is slow to inject DOM.
    if (attached === 0 && tries++ < 20) setTimeout(tryAttach, 100);
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', tryAttach);
  } else {
    tryAttach();
  }
}

init();
