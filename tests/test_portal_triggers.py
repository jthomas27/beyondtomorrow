"""Read-only browser checks for the current drawer and native Ghost Portal forms.

The former inline cover form has been removed. No sign-in or subscription
request is submitted; all non-read requests are aborted by the page fixture.
"""

import pytest
from playwright.sync_api import sync_playwright, Page, expect

pytestmark = pytest.mark.integration

BASE_URL = "https://beyondtomorrow.world"

# How long to wait for the Portal iframe to appear after a click (ms)
PORTAL_TIMEOUT = 6000


# ── Helpers ───────────────────────────────────────────────────────────────────

def _wait_for_portal(page: Page, timeout: int = PORTAL_TIMEOUT) -> bool:
    """Return True if the Ghost Portal iframe opens and renders content."""
    try:
        # 1. Wait for the portal root div to appear
        page.wait_for_selector("#ghost-portal-root iframe[data-testid='portal-popup-frame']", timeout=timeout)
        # 2. Give the iframe a moment to render
        page.wait_for_timeout(800)
        # 3. Confirm the iframe has content (not blank)
        has_content = page.evaluate("""() => {
            const root = document.getElementById('ghost-portal-root');
            if (!root) return false;
            const iframe = root.querySelector("iframe[data-testid='portal-popup-frame']");
            if (!iframe) return false;
            try {
                const body = iframe.contentDocument && iframe.contentDocument.body;
                return body && body.children.length > 0;
            } catch (e) {
                // Cross-origin iframe — presence alone is sufficient
                return true;
            }
        }""")
        return bool(has_content)
    except Exception:
        return False


def _close_portal(page: Page) -> None:
    """Close the Portal if open, so the next test starts clean."""
    page.keyboard.press("Escape")
    page.wait_for_timeout(500)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


@pytest.fixture
def page(browser):
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    # These are read-only UI checks; never send a real sign-in/subscription request.
    ctx.route("**/*", lambda route: route.continue_() if route.request.method in {"GET", "HEAD", "OPTIONS"} else route.abort())
    pg = ctx.new_page()
    pg.goto(BASE_URL, wait_until="networkidle", timeout=30000)
    pg.wait_for_timeout(1500)
    yield pg
    ctx.close()


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestNavTriggers:
    """Navigation bar sign-in and subscribe buttons must open Ghost Portal."""

    def test_signin_link_opens_portal(self, page: Page):
        """Nav 'Sign in' link (data-portal=signin) must open the Ghost Portal."""
        page.locator(".bt-burger-btn").click()
        signin = page.locator(".bt-drawer-signin")
        expect(signin).to_be_visible()
        signin.click()
        opened = _wait_for_portal(page)
        assert opened, (
            "Ghost Portal did not open after clicking the 'Sign in' nav link"
        )
        _close_portal(page)

    def test_subscribe_button_opens_portal(self, page: Page):
        """Nav 'Subscribe' button (data-portal=signup) must open the Ghost Portal."""
        page.locator(".bt-burger-btn").click()
        subscribe = page.locator(".bt-drawer-signup")
        expect(subscribe).to_be_visible()
        subscribe.click()
        opened = _wait_for_portal(page)
        assert opened, (
            "Ghost Portal did not open after clicking the 'Subscribe' nav button"
        )
        _close_portal(page)


class TestSignUpLink:
    """'Sign up' link in the page must open Ghost Portal."""

    def test_signup_link_opens_portal(self, page: Page):
        """'Sign up' link (href=#/portal/) must open the Ghost Portal."""
        signup = page.locator("a[href='#/portal/']").first
        expect(signup).to_be_visible()
        signup.click()
        opened = _wait_for_portal(page)
        assert opened, (
            "Ghost Portal did not open after clicking the 'Sign up' link"
        )
        _close_portal(page)


class TestPortalSubscribeForm:
    """The native Portal owns the subscription form; no obsolete inline form is required."""

    @pytest.fixture
    def portal(self, page):
        page.locator(".bt-burger-btn").click()
        page.locator(".bt-drawer-signup").click()
        assert _wait_for_portal(page)
        return page.frame_locator("#ghost-portal-root iframe[data-testid='portal-popup-frame']")

    def test_signup_screen_has_heading(self, portal):
        # Ghost renders the signup controls in React containers rather than a <form>.
        expect(portal.get_by_role("heading").first).to_be_visible()

    def test_form_has_email_input(self, portal):
        expect(portal.locator("input[type='email']").first).to_be_editable()

    def test_form_has_submit_button(self, portal):
        expect(portal.locator("button[type='submit']").first).to_be_visible()

    def test_email_can_be_entered_without_submitting(self, portal):
        field = portal.locator("input[type='email']").first
        field.fill("portal-test@example.com")
        expect(field).to_have_value("portal-test@example.com")
