"""
Browser tests - Ghost Portal opens for every subscribe/sign-in trigger on the homepage.

Five triggers are verified:
  1. Nav "Sign in"    link  (data-portal=signin)
  2. Nav "Subscribe"  button (data-portal=signup)
  3. "Sign up"        link  (href=#/portal/)
  4. Inline subscribe form  (form.cover-form with email input)
  5. Form submit button     (button.form-button inside the inline form)

For click-based triggers: verifies Ghost Portal iframe opens and renders content.
For the inline form:      verifies it contains a live email input and submit button.

Run:
    source .venv/bin/activate
    pytest tests/test_portal_triggers.py -v
"""

import pytest
from playwright.sync_api import sync_playwright, Page, expect

BASE_URL = "https://beyondtomorrow.world"

# How long to wait for the Portal iframe to appear after a click (ms)
PORTAL_TIMEOUT = 6000


# ── Helpers ───────────────────────────────────────────────────────────────────

def _wait_for_portal(page: Page, timeout: int = PORTAL_TIMEOUT) -> bool:
    """Return True if the Ghost Portal iframe opens and renders content."""
    try:
        # 1. Wait for the portal root div to appear
        page.wait_for_selector("#ghost-portal-root iframe", timeout=timeout)
        # 2. Give the iframe a moment to render
        page.wait_for_timeout(800)
        # 3. Confirm the iframe has content (not blank)
        has_content = page.evaluate("""() => {
            const root = document.getElementById('ghost-portal-root');
            if (!root) return false;
            const iframe = root.querySelector('iframe');
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
        signin = page.locator("a[data-portal='signin']").first
        expect(signin).to_be_visible()
        signin.click()
        opened = _wait_for_portal(page)
        assert opened, (
            "Ghost Portal did not open after clicking the 'Sign in' nav link"
        )
        _close_portal(page)

    def test_subscribe_button_opens_portal(self, page: Page):
        """Nav 'Subscribe' button (data-portal=signup) must open the Ghost Portal."""
        subscribe = page.locator("a[data-portal='signup']").first
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


class TestInlineSubscribeForm:
    """The inline subscribe form on the homepage must be functional."""

    def test_form_is_present(self, page: Page):
        """Inline subscribe form must exist on the page."""
        form = page.locator("form.cover-form, form[data-members-form]").first
        expect(form).to_be_visible()

    def test_form_has_email_input(self, page: Page):
        """Inline form must contain a visible email input field."""
        email_input = page.locator(
            "form.cover-form input[type='email'], "
            "form[data-members-form] input[type='email'], "
            "form.form-wrapper input[type='email']"
        ).first
        expect(email_input).to_be_visible()
        # Input must be enabled and editable
        assert not email_input.is_disabled(), (
            "Email input in subscribe form is disabled"
        )

    def test_form_has_submit_button(self, page: Page):
        """Inline form must contain a visible, enabled submit button."""
        btn = page.locator("button.form-button").first
        expect(btn).to_be_visible()
        assert not btn.is_disabled(), (
            "Form submit button is disabled"
        )

    def test_form_submit_opens_portal(self, page: Page):
        """Submitting the inline form with a test email must open Ghost Portal."""
        email_input = page.locator(
            "form.cover-form input[type='email'], "
            "form[data-members-form] input[type='email'], "
            "form.form-wrapper input[type='email']"
        ).first
        expect(email_input).to_be_visible()
        # Type a test email — Ghost Portal intercepts this, no real email is sent
        # because the Portal handles validation/submission client-side before proceeding
        email_input.fill("portal-test@example.com")
        btn = page.locator("button.form-button").first
        btn.click()
        opened = _wait_for_portal(page)
        assert opened, (
            "Ghost Portal did not open after submitting the inline subscribe form"
        )
        _close_portal(page)
