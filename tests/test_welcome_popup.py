"""
Browser tests - Subscribe confirmation popup behaviour.

Ghost Portal's native 'Now check your email!' modal handles both subscribe
and sign-in confirmation. The custom Welcome Aboard overlay has been removed.

These tests verify:
  1. The custom #bt-welcome-overlay is NOT present on the page at all.
  2. Ghost Portal is still active and functional.

Run:
    source .venv/bin/activate
    pytest tests/test_welcome_popup.py -v
"""

import pytest
from playwright.sync_api import sync_playwright, Page

BASE_URL = 'https://beyondtomorrow.world'


@pytest.fixture(scope='module')
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


@pytest.fixture
def page(browser):
    ctx = browser.new_context()
    pg = ctx.new_page()
    pg.goto(BASE_URL, wait_until='domcontentloaded', timeout=30000)
    pg.wait_for_timeout(1500)
    yield pg
    ctx.close()


class TestCustomPopupRemoved:
    """The custom Welcome Aboard overlay must be completely absent."""

    def test_custom_overlay_not_in_dom(self, page: Page):
        """#bt-welcome-overlay must not exist anywhere in the DOM."""
        overlay = page.query_selector("#bt-welcome-overlay")
        assert overlay is None, (
            '#bt-welcome-overlay found in DOM - custom popup was not fully removed'
        )

    def test_custom_popup_css_not_injected(self, page: Page):
        """No bt-welcome-* CSS rules should be present in the page."""
        has_css = page.evaluate(
            '() => {'
            '  for (const sheet of document.styleSheets) {'
            '    try {'
            '      for (const rule of sheet.cssRules) {'
            "        if (rule.selectorText && rule.selectorText.includes('bt-welcome')) return true;"
            '      }'
            '    } catch (e) {}'
            '  }'
            '  return false;'
            '}'
        )
        assert not has_css, (
            'bt-welcome-* CSS rules still present - custom popup styles not removed'
        )

    def test_confetti_script_not_loaded(self, page: Page):
        """canvas-confetti must not be loaded."""
        has_confetti = page.evaluate(
            "() => typeof window.confetti !== 'undefined'"
        )
        assert not has_confetti, (
            'canvas-confetti is still loaded - popup script not fully removed'
        )

    def test_no_overlay_after_wait(self, page: Page):
        """Overlay remains absent after 3 seconds (no deferred injection)."""
        page.wait_for_timeout(3000)
        overlay = page.query_selector("#bt-welcome-overlay")
        assert overlay is None, (
            '#bt-welcome-overlay appeared after page load - deferred injection detected'
        )


class TestGhostPortalIntact:
    """Ghost Portal must still be present and functional."""

    def test_portal_script_loaded(self, page: Page):
        """Ghost Portal script must be referenced in the page source."""
        content = page.content()
        assert 'portal' in content.lower(), (
            'Ghost Portal script not found in page - Portal may be broken'
        )

    def test_portal_trigger_present(self, page: Page):
        """At least one subscribe/portal trigger element must be on the page."""
        triggers = page.query_selector_all(
            '[data-portal], [data-members-form], a[href*="#/portal"], '
            '.gh-portal-trigger, button[data-members-link]'
        )
        assert len(triggers) > 0, (
            'No subscribe/portal trigger elements found on the page'
        )
