# Railway ↔ Hostinger SMTP Issue

**Date:** 8 February 2026
**Resolved:** 10 February 2026 — Upgraded to Railway Pro plan. SMTP ports unblocked. Tested and confirmed working.
**Project:** caring-alignment (BeyondTomorrow.World)
**Affected Service:** Ghost CMS on Railway

> **Status:** ✅ **RESOLVED** — Railway Pro plan unblocks SMTP ports 25, 465, 587. Hostinger SMTP is fully operational from Railway. `security__staffDeviceVerification` re-enabled.

---

## Problem (Historical)

Ghost CMS could not send emails from Railway's infrastructure on the Hobby plan. All outbound SMTP connections to `smtp.hostinger.com` timed out with `ETIMEDOUT`, causing:

- Staff login failures (HTTP 500) when device verification is enabled
- Staff invite emails failing to send
- Password reset emails not delivered
- Member signup/login emails non-functional
- Newsletter delivery impossible via SMTP

---

## Observations

### What We Tested

| Test | From | Result |
|------|------|--------|
| SMTP credentials (nodemailer) | Local machine | ✅ Email sent successfully |
| TCP port 465 (SSL) | Local machine | ✅ Open (20ms) |
| TCP port 587 (STARTTLS) | Local machine | ✅ Open (9ms) |
| TLS handshake on 465 | Local machine | ✅ Connected (101ms), cipher TLS_AES_256_GCM_SHA384 |
| Ghost admin login (API) | Railway | ❌ HTTP 500 — `ETIMEDOUT` sending device verification email |
| Ghost staff invite (API) | Railway | ❌ HTTP 500 — `Connection timeout` sending invite email |
| Ghost login with device verification disabled | Railway | ✅ HTTP 201 — login succeeds when no email is triggered |
| SMTP to Hostinger port 465 | Railway | ❌ Connection timeout |
| SMTP to Hostinger port 587 | Railway | ❌ Connection timeout |
| Direct mail transport | Railway | ❌ Failed (port 25 also blocked) |

### Root Cause

**Railway blocks all outbound SMTP ports (25, 465, 587) on Free, Trial, and Hobby plans.**

From [Railway's documentation](https://docs.railway.com/networking/outbound-networking):

> *"SMTP is only available on the Pro plan and above. Free, Trial, and Hobby plans must use transactional email services with HTTPS APIs. SMTP is disabled on these plans to prevent spam and abuse."*

This is a platform-level network restriction — not a misconfiguration. The Hostinger SMTP credentials are valid and work correctly from any non-Railway environment.

### Temporary Fix Applied

To restore admin login functionality, device verification was disabled:

```
security__staffDeviceVerification = false
```

This prevents Ghost from attempting to send the new-device auth code email on login. Login now returns HTTP 201 successfully. However, all other email-dependent features remain broken.

---

## Key Constraint: How Ghost Sends Email

Ghost CMS uses [Nodemailer](https://github.com/nodemailer/nodemailer) internally to send all emails. This is server-side code baked into Ghost's core — it runs inside the Ghost Docker container on Railway. There is no way to redirect Ghost's email sending to a client-side call, a frontend trigger, or an external worker without modifying Ghost's source code.

This means:
- **Ghost must connect to an SMTP server or API-based mail service from within Railway's network**
- Hostinger email is SMTP/IMAP only — it does not offer an HTTP sending API
- Since Railway (Hobby plan) blocks outbound SMTP, Ghost cannot reach `smtp.hostinger.com` at all
- **You can still use Hostinger email for receiving** (IMAP) and for manual sending via webmail or a desktop client (Gmail, Outlook, etc.) — the block only affects outbound SMTP from Railway's servers

### What Still Works with Hostinger

| Use Case | Works? | How |
|----------|--------|-----|
| Sending email from Hostinger webmail | ✅ | Uses Hostinger's own servers, not Railway |
| Reading email in Gmail/Outlook via IMAP | ✅ | IMAP is inbound to your client, not affected |
| Sending from Gmail/Outlook via Hostinger SMTP | ✅ | Sends from your computer/phone, not Railway |
| Ghost sending via Hostinger SMTP | ❌ | Blocked — Ghost runs inside Railway's network |
| Agent worker fetching email via IMAP | ❓ | Depends on whether Railway blocks IMAP port 993 — needs testing |

---

## Solutions

### Option 1: Upgrade to Railway Pro Plan

Upgrade the Railway account to the Pro plan, which unblocks outbound SMTP on all ports. Keep the existing Hostinger SMTP configuration unchanged.

| Pros | Cons |
|------|------|
| No code changes required | Costs ~$20/month (minimum) |
| Existing Hostinger SMTP config works immediately | Pro plan pricing is usage-based, could increase with scale |
| Full SMTP support on all ports (25, 465, 587) | Still dependent on Hostinger SMTP reliability |
| Enables SMTP for all future Railway services | Hostinger SMTP has no delivery analytics or bounce tracking |
| Can re-enable `staffDeviceVerification` | Hostinger shared SMTP may have lower deliverability than dedicated services |
| Keeps everything on two providers (Railway + Hostinger) | Only need to redeploy Ghost after upgrade |

### Option 2: Use Mailgun (Ghost's Native Integration)

Replace Hostinger SMTP with Mailgun. Ghost has **native built-in Mailgun support** — no custom code needed. Ghost uses Mailgun's HTTPS API for newsletters and its SMTP relay for transactional emails. When configured with the `service: Mailgun` option, Nodemailer routes through Mailgun's API-compatible endpoints.

| Pros | Cons |
|------|------|
| Works on any Railway plan (uses HTTPS, not SMTP) | Requires a Mailgun account |
| Ghost has native Mailgun integration (zero code) | No free tier — Flex plan is pay-as-you-go |
| Handles both transactional AND newsletter/bulk emails | Requires DNS verification (SPF/DKIM records for your domain) |
| Delivery analytics, bounce tracking, spam reports | Cost: ~$0.80 per 1,000 emails (Flex) or $35/mo (Foundation) |
| Industry-standard email deliverability | Another third-party dependency to manage |
| Can send from your own domain (`beyondtomorrow.world`) | Initial setup takes 30-60 minutes |
| Ghost's officially recommended email provider | — |

**Ghost configuration (env vars only):**
```
mail__transport                = SMTP
mail__options__service         = Mailgun
mail__options__auth__user      = postmaster@mg.beyondtomorrow.world
mail__options__auth__pass      = <mailgun-smtp-password>
mail__from                     = admin@beyondtomorrow.world
```

### Option 3: Use Resend (HTTPS API)

Use Resend, Railway's recommended email service. Resend uses HTTPS API calls instead of SMTP, so it works on all Railway plans.

| Pros | Cons |
|------|------|
| Works on any Railway plan (HTTPS API) | No native Ghost integration — requires custom Nodemailer transport |
| Railway's officially recommended email provider | Ghost doesn't support Resend out of the box |
| Modern developer experience, clean API | Modifying Ghost's mail transport may not survive upgrades |
| Free tier: 100 emails/day, 3,000/month | No newsletter/bulk email support for Ghost |
| Simple API key authentication | Requires DNS verification (SPF/DKIM) |
| Good deliverability | Paid plans start at $20/month |

### Option 4: Use SendGrid (HTTPS API)

Use SendGrid's SMTP relay or HTTPS API.

| Pros | Cons |
|------|------|
| Well-established email platform | Free tier limited to 100 emails/day |
| Works via HTTPS API on any Railway plan | More complex setup than Mailgun for Ghost |
| Detailed analytics and deliverability tools | No native Ghost integration |
| Can also work via SMTP on Railway Pro | Paid plans start at $19.95/month |
| Scales well for newsletters | Can be overkill for low-volume blog |
| Template and scheduling features | Another third-party dependency |

### Option 5: External SMTP Relay Worker

Deploy a lightweight email-sending service on a host that allows SMTP (e.g., a small VPS, Cloudflare Worker, or serverless function). Ghost sends to this relay over HTTPS, and the relay forwards via `smtp.hostinger.com`.

| Pros | Cons |
|------|------|
| Keeps using Hostinger email — no new email provider | Requires building and maintaining a custom relay service |
| No additional email service cost | Adds architectural complexity and a point of failure |
| Works on any Railway plan | Ghost doesn't natively support HTTP-to-SMTP relay — needs custom transport |
| Full control over the relay logic | Relay host may also have SMTP restrictions (e.g., Cloudflare Workers) |
| Could run on a free-tier VPS or serverless platform | Security: relay must authenticate and validate requests |

### Option 6: Keep Current Setup (No Email)

Leave SMTP broken and keep `staffDeviceVerification` disabled. Accept that Ghost will not send any emails. Use Hostinger webmail or a desktop client for any manual emails.

| Pros | Cons |
|------|------|
| Zero cost | No password reset emails |
| No additional services to manage | No staff invite emails (must share direct signup links) |
| Admin login works with verification disabled | No member signup/login magic link emails |
| Simplest option — no changes needed | No newsletter delivery from Ghost |
| Can still publish via Ghost Admin API | Reduced security (no device verification) |
| Can still send manually via Hostinger webmail | Breaks Ghost's member/subscription features entirely |

---

## Recommendation

**→ Option 2: Mailgun** is the best choice for this project.

### Why Mailgun?

1. **Native Ghost support** — Ghost has built-in Mailgun integration. Configuration is just environment variables, no custom code, adapters, or relay services needed.

2. **Works on any Railway plan** — Mailgun's integration with Ghost uses HTTPS API for bulk/newsletter emails, completely bypassing Railway's SMTP block. The `service: Mailgun` option in Nodemailer handles routing automatically.

3. **Ghost's official recommendation** — The Ghost documentation specifically recommends Mailgun for both transactional and newsletter emails. It's the only email provider with first-class Ghost support.

4. **Cost-effective** — For a blog with low email volume (admin notifications, occasional member signups), the Flex plan at ~$0.80 per 1,000 emails will cost pennies per month.

5. **Future-proof** — When the blog adds member subscriptions and newsletters (part of the architecture plan), Mailgun handles both transactional and bulk email in a single integration. Other options would require separate solutions.

6. **Better deliverability** — Dedicated email service with proper DKIM/SPF records on your domain delivers far more reliably than Hostinger's shared SMTP servers.

7. **No custom code** — Options like Resend, SendGrid, or an external relay worker all require custom Nodemailer transports or relay services that add complexity and may break on Ghost upgrades. Mailgun is the only option that works with Ghost out of the box.

### Why Not the Others?

| Option | Reason to Pass |
|--------|---------------|
| Railway Pro | $20+/mo just to unblock SMTP, and still using Hostinger's shared SMTP with no analytics |
| Resend | No native Ghost integration — requires custom transport that may break on Ghost updates |
| SendGrid | No native Ghost integration, expensive paid plans, overkill for this use case |
| External Relay | Custom service to build and maintain, adds complexity and failure points |
| No Email | Breaks core Ghost features (members, password reset, newsletters) |

### Hostinger Email Going Forward

Even after switching Ghost's outbound email to Mailgun, Hostinger email remains useful:
- **Receiving emails** via IMAP (for the agent email-trigger workflow)
- **Manual correspondence** via webmail or Gmail/Outlook
- **Reply-to address** — set `mail__from` to `admin@beyondtomorrow.world` so replies go to your Hostinger inbox

### Implementation Steps

1. Create a Mailgun account at [mailgun.com](https://www.mailgun.com/)
2. Add and verify the domain `mg.beyondtomorrow.world` (or `beyondtomorrow.world`)
3. Add DNS records (SPF, DKIM, CNAME) at your domain registrar
4. Get SMTP credentials from Mailgun dashboard
5. Update Railway environment variables for Ghost
6. Redeploy Ghost on Railway
7. Re-enable `security__staffDeviceVerification = true`
8. Test by sending a staff invite email from Ghost admin

---

## Current Environment Variables (Email-Related)

```
mail__transport                    = SMTP
mail__from                         = admin@beyondtomorrow.world
mail__options__host                = smtp.hostinger.com
mail__options__port                = 465
mail__options__secure              = true
mail__options__requireTLS          = true
mail__options__auth__user          = admin@beyondtomorrow.world
mail__options__auth__pass          = ********
security__staffDeviceVerification  = true   ← re-enabled 10 Feb 2026
```

✅ **Resolved** — Upgraded to Railway Pro plan on 10 Feb 2026. SMTP ports unblocked. Test email sent successfully from Railway's network via `smtp.hostinger.com:465` (TLS_AES_256_GCM_SHA384).
