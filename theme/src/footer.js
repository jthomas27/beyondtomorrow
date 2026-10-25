
(function () {
  'use strict';

  // ── Remove any subscribe / sign-up sections from footer ──────────────
  function removeFooterSubscribe() {
    var footerRoots = [
      document.querySelector('.gh-foot'),
      document.querySelector('.site-footer'),
      document.querySelector('footer')
    ].filter(Boolean);

    footerRoots.forEach(function (footer) {
      footer.querySelectorAll('.site-footer-social-links').forEach(function (social) {
        social.remove();
      });
      footer.querySelectorAll('*').forEach(function (el) {
        var cls = (el.className || '').toLowerCase();
        var id  = (el.id || '').toLowerCase();
        var txt = (el.textContent || '').toLowerCase().trim();
        if (
          cls.includes('footer-cta') || cls.includes('gh-foot-cta') ||
          cls.includes('site-footer-cta') ||
          id.includes('subscribe')  || id.includes('signup')  ||
          el.hasAttribute('data-members-form') ||
          (el.tagName === 'SECTION' && (txt.startsWith('subscribe') || txt.startsWith('sign up')))
        ) {
          el.style.setProperty('display', 'none', 'important');
        }
      });
    });

    // Also nuke the floating Ghost Portal trigger button
    document.querySelectorAll(
      '.gh-portal-triggerbtn-container, .gh-portal-triggerbtn-iframe'
    ).forEach(function (el) {
      el.style.setProperty('display', 'none', 'important');
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', removeFooterSubscribe);
  } else {
    removeFooterSubscribe();
  }
})();
