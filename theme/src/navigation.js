
document.addEventListener('DOMContentLoaded', function () {
    // ── Brand: keep "BeyondTomorrow" on the gradient, render the trailing
    //    ".World" summary in solid white ──────────────────────────────
    (function styleBrandSuffix() {
        var brand = document.querySelector('.gh-head-brand a, .site-title, .gh-head-logo');
        if (!brand || brand.querySelector('.bt-brand-suffix')) return;
        var text = brand.textContent.trim();
        var marker = 'beyondtomorrow';
        var idx = text.toLowerCase().indexOf(marker);
        if (idx === -1) return;
        var splitAt = idx + marker.length;
        var prefix = text.slice(0, splitAt);
        var suffix = text.slice(splitAt);
        if (!suffix) return;
        brand.textContent = '';
        brand.appendChild(document.createTextNode(prefix));
        var span = document.createElement('span');
        span.className = 'bt-brand-suffix';
        span.textContent = suffix;
        brand.appendChild(span);
    })();

    var headActions = document.querySelector('.gh-head-actions')
                   || document.querySelector('.gh-head-inner');
    if (!headActions) return;

    // Collect existing nav links before CSS hides them
    var navLinks = [];
    document.querySelectorAll('.gh-head-menu .nav li a, .gh-head-menu a').forEach(function (a) {
        navLinks.push({ href: a.getAttribute('href'), text: a.textContent.trim() });
    });
    if (!navLinks.length) {
        navLinks = [{ href: '/', text: 'Home' }, { href: '/about/', text: 'About' }];
    }

    // Append burger to gh-head-actions so it stays on the right side of the header.
    // .gh-burger (Ghost's own hamburger) is hidden via CSS so there's no collision.
    var burgerParent = headActions;

    // Find the Ghost-rendered Sign In href
    var signInEl = document.querySelector(
        '.gh-head-link[href*="signin"], .gh-head-members a[href*="signin"], .gh-head-actions a[href*="signin"]'
    );
    var signInHref = signInEl ? signInEl.getAttribute('href') : '#/portal/signin';

    // Find the Ghost-rendered Sign Up href
    var signUpEl = document.querySelector(
        '.gh-head-link[href*="signup"], .gh-head-members a[href*="signup"], .gh-head-actions a[href*="signup"]'
    );
    var signUpHref = signUpEl ? signUpEl.getAttribute('href') : '#/portal/signup';

    // ── Hamburger button ──────────────────────────────────────────
    var burgerBtn = document.createElement('button');
    burgerBtn.className = 'bt-burger-btn';
    burgerBtn.setAttribute('aria-label', 'Open menu');
    burgerBtn.setAttribute('aria-expanded', 'false');
    burgerBtn.innerHTML = '<span></span><span></span><span></span>';
    headActions.appendChild(burgerBtn);

    // ── Backdrop ──────────────────────────────────────────────────
    var backdrop = document.createElement('div');
    backdrop.className = 'bt-drawer-backdrop';
    document.body.appendChild(backdrop);

    // ── Drawer ────────────────────────────────────────────────────
    var drawer = document.createElement('div');
    drawer.className = 'bt-drawer';
    var navHtml = navLinks.map(function (l) {
        return '<a href="' + l.href + '">' + l.text + '</a>';
    }).join('');
    drawer.innerHTML =
        '<div class="bt-drawer-header">' +
        '<button class="bt-drawer-close" aria-label="Close menu">&#x2715;</button>' +
        '</div>' +
        '<nav class="bt-drawer-nav">' +
        navHtml +
        '<div class="bt-drawer-divider"></div>' +
        '<a href="' + signInHref + '" class="bt-drawer-signin">Sign In</a>' +
        '<a href="' + signUpHref + '" class="bt-drawer-signup">Sign Up</a>' +
        '</nav>';
    document.body.appendChild(drawer);

    // ── Open / close ──────────────────────────────────────────────
    function openDrawer() {
        drawer.classList.add('open');
        backdrop.classList.add('open');
        document.body.style.overflow = 'hidden';
        burgerBtn.setAttribute('aria-expanded', 'true');
    }
    function closeDrawer() {
        drawer.classList.remove('open');
        backdrop.classList.remove('open');
        document.body.style.overflow = '';
        burgerBtn.setAttribute('aria-expanded', 'false');
    }

    burgerBtn.addEventListener('click', openDrawer);
    backdrop.addEventListener('click', closeDrawer);
    drawer.querySelector('.bt-drawer-close').addEventListener('click', closeDrawer);
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') closeDrawer();
    });
});
