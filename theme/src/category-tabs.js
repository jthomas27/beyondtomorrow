
/* ─── Category Tab Bar ─────────────────────────────────────────────────────
   Injects All | Climate | Technology | Geopolitics | Economics tabs above
   the post feed on the homepage and tag pages. Each tab is a real <a> link
   so Ghost's pagination is fully respected and every tab always shows posts.
   The active tab is determined by matching window.location.pathname.
   Guard: exits silently on individual post/page routes (no feed present).
──────────────────────────────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', function () {

    // ── Locate the post feed container ───────────────────────────
    var feed = document.querySelector('.post-feed')
            || document.querySelector('.gh-feed')
            || document.querySelector('.site-main > .post-feed')
            || document.querySelector('.site-main > .gh-feed')
            || (function () {
                   var m = document.querySelector('.site-main');
                   if (!m) return null;
                   var first = m.querySelector('.post-card, .gh-card');
                   return first ? first.parentElement : null;
               }());

    // Only inject on pages that render a feed of post cards.
    // This theme uses <article class="feed post"> instead of .post-card / .gh-card.
    if (!feed) return;
    var hasCards = feed.querySelector('.post-card, .gh-card, article.feed.post, article.post');
    if (!hasCards) return;

    // ── Tab definitions ───────────────────────────────────────────
    var tabs = [
        { label: 'All',         href: '/' },
        { label: 'Climate',     href: '/tag/climate/' },
        { label: 'Technology',  href: '/tag/technology/' },
        { label: 'Geopolitics', href: '/tag/geopolitics/' },
        { label: 'Economics',   href: '/tag/economics/' }
    ];

    // ── Determine active tab from current URL ─────────────────────
    var path = window.location.pathname;
    function isActive(href) {
        if (href === '/') {
            // "All" is active only on the exact homepage (and its pagination)
            return path === '/' || /^\/page\/\d+\/?$/.test(path);
        }
        // Tag pages: /tag/climate/ and /tag/climate/page/2/ etc.
        return path === href || path.indexOf(href) === 0;
    }

    // ── Build the tab bar ─────────────────────────────────────────
    var tabBar = document.createElement('div');
    tabBar.className = 'bt-category-tabs';
    tabBar.setAttribute('role', 'navigation');
    tabBar.setAttribute('aria-label', 'Browse by category');

    tabs.forEach(function (tab) {
        var a = document.createElement('a');
        a.href = tab.href;
        a.className = 'bt-tab-btn' + (isActive(tab.href) ? ' active' : '');
        a.textContent = tab.label;
        if (isActive(tab.href)) {
            a.setAttribute('aria-current', 'page');
        }
        tabBar.appendChild(a);
    });
    // ── Expanded card layout on tag pages ──────────────────────────────────
    // The theme hides .feed-image on feeds without the 'expanded' class.
    // Adding it triggers the theme's own card layout: image on top, title below.
    if (/^\/tag\//.test(path)) {
        feed.classList.add('expanded');
    }
    feed.parentNode.insertBefore(tabBar, feed);
});
