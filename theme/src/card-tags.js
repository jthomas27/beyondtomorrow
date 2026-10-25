
/* ─── Post card: inject all available tags from article CSS classes ─────────
   Ghost renders only the primary tag in .post-card-primary-tag. All tags are
   also encoded as tag-{slug} classes on the <article> element. This script
   reads those classes and appends any additional tags as .bt-post-tag spans.
──────────────────────────────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', function () {
    function toLabel(slug) {
        return slug.split('-').map(function (w) {
            return w.charAt(0).toUpperCase() + w.slice(1);
        }).join(' ');
    }
    document.querySelectorAll('article[class*="tag-"]').forEach(function (article) {
        var tagContainer = article.querySelector('.post-card-tags');
        if (!tagContainer) return;
        var primaryEl = tagContainer.querySelector('.post-card-primary-tag');
        var primaryText = primaryEl ? primaryEl.textContent.trim().toLowerCase() : '';
        var seen = new Set([primaryText]);
        article.classList.forEach(function (cls) {
            if (!cls.startsWith('tag-') || cls.startsWith('tag-hash-')) return;
            var slug = cls.slice(4);
            var label = toLabel(slug);
            if (seen.has(label.toLowerCase())) return;
            seen.add(label.toLowerCase());
            var span = document.createElement('span');
            span.className = 'bt-post-tag';
            span.textContent = label;
            tagContainer.appendChild(span);
        });
    });
});
