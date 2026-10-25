
(function () {
  'use strict';
  function setupArchive() {
    var feed = document.querySelector('.post-feed');
    var nav = feed && feed.parentElement.querySelector('nav.pagination');
    var older = nav && nav.querySelector('a.older-posts');
    if (!feed || !older) return;

    nav.setAttribute('aria-label', 'Article archive');
    var status = document.createElement('p');
    status.className = 'bt-archive-status';
    status.setAttribute('role', 'status');
    nav.insertAdjacentElement('afterend', status);
    var busy = false;
    var finished = false;
    var observer;
    var visited = new Set();
    older.textContent = 'Load more articles';

    async function loadMore(event) {
      if (event) {
        if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
      }
      if (busy || finished) return;
      busy = true;
      if (observer) observer.disconnect();
      older.setAttribute('aria-disabled', 'true');
      feed.setAttribute('aria-busy', 'true');
      status.textContent = 'Loading older articles…';
      var timeout = new AbortController();
      var timer = setTimeout(function () { timeout.abort(); }, 20000);
      try {
        var target = new URL(older.href, location.href);
        if (target.origin !== location.origin) throw new Error('Unexpected archive origin');
        if (visited.has(target.href)) throw new Error('Repeated archive page');
        var response = await fetch(target.href, { signal: timeout.signal });
        if (!response.ok || new URL(response.url).origin !== location.origin) throw new Error('Archive unavailable');
        var page = new DOMParser().parseFromString(await response.text(), 'text/html');
        var cards = page.querySelectorAll('.post-feed > article.post-card');
        if (!cards.length) throw new Error('No article cards found');
        var firstNew;
        var added = 0;
        var seen = new Set(Array.from(feed.querySelectorAll('.post-card-title a, a.post-card-content-link')).map(function (a) { return a.href; }));
        cards.forEach(function (card) {
          var link = card.querySelector('.post-card-title a, a.post-card-content-link');
          if (link && seen.has(link.href)) return;
          if (link) seen.add(link.href);
          var copy = document.importNode(card, true);
          // Only append cards; never execute scripts from fetched archive pages.
          copy.querySelectorAll('script').forEach(function (script) { script.remove(); });
          feed.appendChild(copy);
          if (!firstNew) firstNew = copy;
          added += 1;
        });
        var next = page.querySelector('nav.pagination a.older-posts');
        var nextURL = next && new URL(next.getAttribute('href'), response.url);
        if (nextURL && (nextURL.origin !== location.origin || nextURL.href === target.href)) throw new Error('Invalid next page');
        var number = nav.querySelector('.page-number');
        var newNumber = page.querySelector('nav.pagination .page-number');
        if (number && newNumber) number.textContent = newNumber.textContent;
        visited.add(target.href);
        if (nextURL) older.href = nextURL.href;
        else {
          finished = true;
          older.remove();
        }
        status.textContent = added + ' more articles loaded.' + (nextURL ? '' : ' You have reached the end of the archive.');
        if (event && firstNew) {
          firstNew.setAttribute('tabindex', '-1');
          firstNew.focus({ preventScroll: true });
        }
      } catch (error) {
        // The same link now opens the archive normally, including after timeout.
        finished = true;
        nav.classList.remove('bt-auto-archive');
        older.removeEventListener('click', loadMore);
        older.textContent = 'Open older articles';
        status.textContent = 'Could not load articles here. Use “Open older articles” to continue.';
      } finally {
        clearTimeout(timer);
        busy = false;
        older.removeAttribute('aria-disabled');
        feed.removeAttribute('aria-busy');
        if (observer && !finished) observer.observe(status);
      }
    }
    older.addEventListener('click', loadMore);
    if ('IntersectionObserver' in window) {
      observer = new IntersectionObserver(function (entries) {
        if (entries.some(function (entry) { return entry.isIntersecting; })) loadMore();
      }, { rootMargin: '600px 0px' });
      nav.classList.add('bt-auto-archive');
      observer.observe(status);
    }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', setupArchive);
  else setupArchive();
})();
