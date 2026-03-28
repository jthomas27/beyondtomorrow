"""Audit all subscribe/sign-in triggers on the homepage."""
from playwright.sync_api import sync_playwright

JS = """() => {
    const selectors = [
        '[data-portal]',
        '[data-members-form]',
        'a[href*="#/portal"]',
        '.gh-portal-trigger',
        'button[data-members-link]',
        'a[data-members-link]',
        'button',
        'a'
    ];
    const seen = new Set();
    const results = [];
    for (const sel of selectors) {
        for (const el of document.querySelectorAll(sel)) {
            if (seen.has(el)) continue;
            const text = (el.textContent || '').trim().toLowerCase();
            const href = el.getAttribute('href') || '';
            const dataPortal = el.getAttribute('data-portal') || '';
            const membersLink = el.getAttribute('data-members-link') || '';
            const membersForm = el.getAttribute('data-members-form') || '';
            const isRelevant = (
                dataPortal || membersForm || membersLink ||
                href.includes('#/portal') ||
                text.includes('subscribe') || text.includes('sign in') ||
                text.includes('login') || text.includes('sign up') ||
                text.includes('join') || text === 'free'
            );
            if (isRelevant) {
                seen.add(el);
                results.push({
                    tag: el.tagName,
                    text: text.slice(0, 80),
                    href: href,
                    dataPortal: dataPortal,
                    membersForm: membersForm,
                    membersLink: membersLink,
                    id: el.id || '',
                    className: (el.className || '').toString().slice(0, 100)
                });
            }
        }
    }
    return results;
}"""

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    ctx = b.new_context(viewport={"width": 1280, "height": 900})
    pg = ctx.new_page()
    pg.goto("https://beyondtomorrow.world", wait_until="networkidle", timeout=30000)
    pg.wait_for_timeout(2000)
    triggers = pg.evaluate(JS)
    b.close()

print(f"Found {len(triggers)} trigger(s):\n")
for i, t in enumerate(triggers, 1):
    print(f"  [{i}] <{t['tag'].lower()}> text='{t['text']}'")
    if t['dataPortal']:   print(f"       data-portal='{t['dataPortal']}'")
    if t['membersForm']:  print(f"       data-members-form='{t['membersForm']}'")
    if t['membersLink']:  print(f"       data-members-link='{t['membersLink']}'")
    if t['href']:         print(f"       href='{t['href']}'")
    if t['id']:           print(f"       id='{t['id']}'")
    if t['className']:    print(f"       class='{t['className']}'")
    print()
