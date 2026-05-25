// ═══════════════════════════════════════════════════════════════
// NAVIGATION LINKS — This is the ONLY place you edit links
// When you add a new page, just add one line here.
// ═══════════════════════════════════════════════════════════════

const SKINCARE_LINKS = [
  { name: 'Cleanser', href: '/skincare/cleansers' },
  { name: 'Moisturizer', href: '/skincare/moisturizers' },
  { name: 'Sunscreen', href: '/skincare/sunscreens' },
  { name: 'Serum', href: '/skincare/serums' },
];

const HAIRCARE_LINKS = [
  { name: 'Shampoo', href: '/haircare/shampoos' },
  { name: 'Conditioner', href: '/haircare/conditioners' },
];

// Single fragrance link (no sub-categories or price tiers anymore)
const FRAGRANCES_HREF = '/fragrances/fragrances';

const AUDIO_LINKS = [
  { name: 'Wireless Earbuds', href: '/audio/wireless-earbuds' },
  { name: 'Headphones', href: '/audio/headphones' },
  { name: 'IEMs', href: '/audio/iems' },
];


// ═══════════════════════════════════════════════════════════════
// EVERYTHING BELOW BUILDS THE NAV AUTOMATICALLY
// You don't need to touch anything below this line.
// ═══════════════════════════════════════════════════════════════

function getCurrentPath() {
  return window.location.pathname.replace(/\.html$/, '').replace(/\/$/, '') || '/';
}

function buildDropdownItems(links) {
  const currentPath = getCurrentPath();
  return links.map(function(link) {
    if (link.soon) {
      return '<a class="dropdown-item coming">' + link.name + ' &middot; Soon</a>';
    }
    var isActive = currentPath === link.href;
    return '<a href="' + link.href + '" class="dropdown-item' + (isActive ? ' active' : '') + '">' + link.name + '</a>';
  }).join('');
}

// Builds a single standalone dropdown link (used for Fragrances)
function buildStandaloneDropdownItem(name, href) {
  var isActive = getCurrentPath() === href;
  return '<a href="' + href + '" class="dropdown-item dropdown-item-standalone' + (isActive ? ' active' : '') + '">' + name + '</a>';
}

function buildMobileLinks(links) {
  var currentPath = getCurrentPath();
  return links.map(function(link) {
    if (link.soon) {
      return '<a class="coming">' + link.name + ' &middot; Soon</a>';
    }
    var isActive = currentPath === link.href;
    var style = isActive ? ' style="color:var(--accent);font-weight:bold;"' : '';
    return '<a href="' + link.href + '"' + style + '>' + link.name + '</a>';
  }).join('');
}

// Builds a single standalone mobile link (used for Fragrances)
function buildStandaloneMobileLink(name, href) {
  var isActive = getCurrentPath() === href;
  var style = isActive ? ' style="color:var(--accent);font-weight:bold;"' : '';
  return '<a href="' + href + '"' + style + '>' + name + '</a>';
}

function renderNav() {
  var navEl = document.getElementById('mainNav');
  if (!navEl) return;

  navEl.innerHTML = ''
    + '<div class="nav-inner">'
    + '  <a href="/" class="logo">'
    + '    <div class="logo-flag"></div>'
    + '    IndiaRecs'
    + '  </a>'
    // ─── Beauty & Personal Care: Skincare + Hair Care + Fragrances (single link) ───
    + '  <div class="nav-dropdown">'
    + '    <button class="nav-dropdown-btn">Beauty &amp; Personal Care <span class="arrow">▼</span></button>'
    + '    <div class="dropdown-menu">'
    + '      <div class="dropdown-section">Skincare</div>'
    +        buildDropdownItems(SKINCARE_LINKS)
    + '      <div class="dropdown-divider"></div>'
    + '      <div class="dropdown-section">Hair Care</div>'
    +        buildDropdownItems(HAIRCARE_LINKS)
    + '      <div class="dropdown-divider"></div>'
    // Fragrances is now a single clickable item, no section header or sub-items
    +        buildStandaloneDropdownItem('Fragrances', FRAGRANCES_HREF)
    + '    </div>'
    + '  </div>'
    // ─── Tech & Lifestyle: Audio ───
    + '  <div class="nav-dropdown">'
    + '    <button class="nav-dropdown-btn">Tech &amp; Lifestyle <span class="arrow">▼</span></button>'
    + '    <div class="dropdown-menu">'
    + '      <div class="dropdown-section">Audio</div>'
    +        buildDropdownItems(AUDIO_LINKS)
    + '    </div>'
    + '  </div>'
    + '  <div class="nav-search">'
    + '    <input id="navSearch" type="text" placeholder="Search products, brands, categories..." />'
    + '  </div>'
    + '  <a href="/#about" class="nav-link">About</a>'
    + '  <a href="/#contact" class="nav-link">Contact Us</a>'
    + '  <button class="nav-mobile-btn" id="mobileBtn" aria-label="Open menu">☰</button>'
    + '</div>';

  // Mobile menu
  var mobileContainer = document.getElementById('mobileMenuContainer');
  if (mobileContainer) {
    mobileContainer.innerHTML = ''
      + '<div class="mobile-menu-overlay" id="mobileOverlay"></div>'
      + '<div class="mobile-menu" id="mobileMenu">'
      + '  <button class="mobile-menu-close" id="mobileClose">&times;</button>'
      + '  <h4>Skincare</h4>'
      +    buildMobileLinks(SKINCARE_LINKS)
      + '  <h4>Hair Care</h4>'
      +    buildMobileLinks(HAIRCARE_LINKS)
      // Fragrances: single link, no sub-section
      + '  <h4>Fragrances</h4>'
      +    buildStandaloneMobileLink('Browse Fragrances', FRAGRANCES_HREF)
      + '  <h4>Audio</h4>'
      +    buildMobileLinks(AUDIO_LINKS)
      + '  <h4>Account</h4>'
      + '  <a href="/#about">About</a>'
      + '  <a href="/#contact">Contact Us</a>'
      + '</div>';

    // Wire up mobile menu toggle
    var overlay = document.getElementById('mobileOverlay');
    var menu = document.getElementById('mobileMenu');
    var closeBtn = document.getElementById('mobileClose');
    var openBtn = document.getElementById('mobileBtn');

    function toggleMobile() {
      menu.classList.toggle('show');
      overlay.classList.toggle('show');
    }

    openBtn.addEventListener('click', toggleMobile);
    overlay.addEventListener('click', toggleMobile);
    closeBtn.addEventListener('click', toggleMobile);
  }
}

// Run when page is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', renderNav);
} else {
  renderNav();
}
