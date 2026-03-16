# Subscribe Popup — Verification & Test Reference

Status of the welcome modal + confetti feature triggered when a new visitor subscribes on BeyondTomorrow.World. Use this document before opening any bug investigation to avoid re-testing already resolved issues.

**Last verified:** 16 March 2026  
**Code location:** `theme/footer.txt` (deployed to Ghost via `scripts/inject-code.js`)

---

## Feature Overview

When a visitor submits their email via the Ghost Portal subscribe button:

1. Ghost Portal sends them a magic-link confirmation email
2. Portal transitions its iframe to a "check your inbox" success page
3. Our code detects this DOM change and triggers:
   - Confetti burst (canvas-confetti, two-sided + centre burst at 400ms)
   - Welcome modal overlay ("Welcome Aboard! / Got it!" button)

---

## Verified Issues — Do Not Re-Test

These bugs were found and fixed in March 2026. The fixes are in `theme/footer.txt` (commit `9f8752d`).

### BUG-01 — Modal never appeared for new subscribers ✅ FIXED

**Root cause:** `scanIframeForSuccess()` only checked `.gh-portal-notification-icon.success` and `.gh-portal-notification p` — the *toast notification* selectors used for already logged-in member actions. A new free subscriber never sees those elements. Ghost Portal shows a completely different *success page* instead.

**Fix:** Added primary detection against `.gh-portal-main-title` (Ghost 5.x Portal 2.x) and `h1/h2/h3` heading text for "inbox" / "check your email" as a resilient fallback.

### BUG-02 — Heading fallback missed h1 ✅ FIXED

**Root cause:** Fallback heading scan used `h2, h3` only. Ghost Portal renders its main-title as an `h1`.

**Fix:** Selector updated to `h1, h2, h3`.

### BUG-03 — Escape key did not close modal ✅ FIXED

**Root cause:** No `keydown` listener was registered.

**Fix:** `keydown` listener added to `showModal()`; self-removes on close to prevent listener accumulation.

---

## CSP / Cloudflare Verification ✅ PASSED (16 March 2026)

Live headers checked via `curl -sI https://beyondtomorrow.world`. No rules block the feature.

| Check | CSP Directive | Result |
|---|---|---|
| canvas-confetti CDN (`cdn.jsdelivr.net`) | `script-src` includes `https://cdn.jsdelivr.net` | ✅ Allowed |
| Inline `<script>` block | `script-src` includes `'unsafe-inline'` | ✅ Allowed |
| Inline `<style>` block | `style-src` includes `'unsafe-inline'` | ✅ Allowed |
| Ghost Portal iframe (same-origin `about:blank`) | `frame-src 'self'` covers same-origin | ✅ Allowed |
| `iframe.contentDocument` DOM access | Same-origin browser policy; `try/catch` handles exceptions | ✅ Allowed |
| Ghost magic-link API (`/members/api/send-magic-link/`) | `connect-src 'self'` | ✅ Allowed |

---

## Current Detection Logic

Detection runs in three layers inside `scanIframeForSuccess(iframe)`:

```
1. .gh-portal-main-title  →  text contains "inbox" | "check your email" | "sent you"
        ↓ (if class not found)
2. h1, h2, h3 (any heading)  →  text contains "inbox" | "check your email"
        ↓ (last resort)
3. .gh-portal-notification-icon.success   (logged-in member toast)
   .gh-portal-notification p  →  "Check your email"
```

Layer 1 targets the **new subscriber success page** in Ghost 5.x Portal 2.x.  
Layer 2 is a resilient fallback if Ghost changes its CSS class names.  
Layer 3 covers logged-in member profile-update toasts.

---

## Remaining Test Scope (not yet verified by automated test)

These must still be verified manually in a real browser after any future changes to `theme/footer.txt`:

| # | Test | How to test | Expected result |
|---|---|---|---|
| T-01 | **New subscriber happy path** | Open site in incognito, click Subscribe, enter a valid email, submit | Confetti fires + welcome modal appears |
| T-02 | **Modal close — button** | After T-01, click "Got it!" | Modal disappears, no confetti re-fire |
| T-03 | **Modal close — backdrop** | After T-01, click outside the modal card | Modal disappears |
| T-04 | **Modal close — Escape key** | After T-01, press Escape | Modal disappears |
| T-05 | **No double-fire** | Wait 15 s after T-01, reopen Portal, submit same email | Confetti fires once only per 15 s window |
| T-06 | **Already subscribed / logged in** | Log in as existing member, update profile | No confetti, no modal (toast detection only — no false positive) |
| T-07 | **Mobile viewport** | T-01 on a phone screen | Modal fits viewport, not overflowing |

---

## How to Re-Deploy After Changes

```bash
# Edit theme/footer.txt, then:
GHOST_ADMIN_PASSWORD=$(railway variables --service 0daf496c-e14f-41d4-b89b-3624a778c99d --json | python3 -c "import json,sys; print(json.load(sys.stdin).get('GHOST_ADMIN_PASSWORD',''))") \
GHOST_ADMIN_EMAIL=admin@beyondtomorrow.world \
node scripts/inject-code.js

# Commit and push
git add theme/footer.txt
git commit -m "fix|feat: description"
git push origin main
```

---

## Re-Checking CSP After Cloudflare Rule Changes

If Cloudflare Transform Rules are modified, re-run:

```bash
curl -sI https://beyondtomorrow.world | grep -i "content-security-policy"
```

Verify the output contains:
- `script-src` — `'unsafe-inline'` and `https://cdn.jsdelivr.net`
- `style-src` — `'unsafe-inline'`
- `frame-src` — `'self'`
- `connect-src` — `'self'`
