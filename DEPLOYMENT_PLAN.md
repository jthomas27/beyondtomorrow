# BeyondTomorrow.World - Deployment Plan

A step-by-step guide to create a simple one-page blog website and deploy it on Railway with your custom domain.

---

## Part 1: Create the One-Page Website

### Step 1: Set Up Project Structure
Create a simple static website with the following files:
- `index.html` - Main blog page
- `styles.css` - Styling
- `package.json` - For serving the static site (optional, for Railway)

### Step 2: Create the HTML Page
Build a clean, responsive one-page blog layout with:
- Header with "BeyondTomorrow" branding
- Hero section with blog introduction
- Blog posts/content section
- Footer with links and copyright

### Step 3: Style the Website
Create modern, responsive CSS with:
- Typography and color scheme
- Mobile-friendly responsive design
- Clean, readable blog layout

### Step 4: Test Locally
Open `index.html` in a browser to verify everything looks correct.

---

## Part 2: Deploy to Railway

### Step 5: Create a Railway Account
1. Go to [railway.app](https://railway.app)
2. Sign up with GitHub, GitLab, or email
3. Verify your account

### Step 6: Prepare Your Project for Railway
**Static Site with Nginx**:
Create a `Dockerfile`:
```dockerfile
FROM nginx:alpine
COPY . /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
```

### Step 7: Push Code to GitHub
**Repository:** https://github.com/jthomas27/beyondtomorrow.git

1. Initialize git: `git init`
2. Add files: `git add .`
3. Commit: `git commit -m "Initial blog setup"`
4. Add remote: `git remote add origin https://github.com/jthomas27/beyondtomorrow.git`
5. Push to GitHub: `git push -u origin main`

### Step 8: Deploy to Railway
1. Log in to [railway.app](https://railway.app)
2. Click **"New Project"**
3. Select **"Deploy from GitHub repo"**
4. Authorize Railway to access your GitHub
5. Select your blog repository
6. Railway will auto-detect and deploy your project

---

## Part 3: Configure Custom Domain (beyondtomorrow.world)

### Step 9: Add Custom Domain in Railway
1. In your Railway project dashboard, click on your **deployed service**
2. Go to the **"Settings"** tab
3. Scroll to **"Domains"** section
4. Click **"+ Custom Domain"**
5. Enter: `beyondtomorrow.world`
6. Click **"Add Domain"**
7. Railway will display the required DNS records

### Step 10: Copy Railway's DNS Configuration
Railway will show you one of the following:
- **CNAME record** pointing to something like `your-project.up.railway.app`
- Or specific instructions for your setup

Write down/copy:
- Record Type (usually CNAME)
- Host/Name (usually `@` or `www`)
- Value/Target (Railway's provided domain)

### Step 11: Configure DNS at Your Domain Registrar
Go to your domain registrar where `beyondtomorrow.world` is registered (e.g., Namecheap, GoDaddy, Cloudflare, Google Domains, etc.)

1. Log in to your domain registrar
2. Navigate to **DNS Settings** or **DNS Management**
3. Find existing A or CNAME records for the root domain

### Step 12: Add/Update DNS Records

#### For Root Domain (beyondtomorrow.world):
| Type | Host/Name | Value/Target | TTL |
|------|-----------|--------------|-----|
| CNAME | @ | `your-project.up.railway.app` | 3600 |

> ⚠️ **Note:** Some registrars don't allow CNAME on root domain. In that case, use Railway's provided IP addresses as A records, or use a service like Cloudflare that supports CNAME flattening.

#### For WWW subdomain (www.beyondtomorrow.world):
| Type | Host/Name | Value/Target | TTL |
|------|-----------|--------------|-----|
| CNAME | www | `your-project.up.railway.app` | 3600 |

### Step 13: Remove Conflicting Records
Delete any existing A records or other records that might conflict with your new CNAME records for `@` and `www`.

### Step 14: Save DNS Changes
1. Save/Apply your DNS configuration
2. DNS propagation can take **5 minutes to 48 hours** (usually under 1 hour)

### Step 15: Verify Domain in Railway
1. Return to Railway dashboard
2. Go to your service → Settings → Domains
3. Railway will show a checkmark ✓ once DNS is verified
4. Railway automatically provisions **SSL/HTTPS** for your domain

### Step 16: Test Your Domain
1. Wait for DNS propagation (check with [dnschecker.org](https://dnschecker.org))
2. Visit `https://beyondtomorrow.world` in your browser
3. Verify SSL certificate is active (padlock icon)
4. Test `https://www.beyondtomorrow.world` as well

---

## Quick Reference: DNS Records Summary

| Purpose | Type | Name | Value |
|---------|------|------|-------|
| Root domain | CNAME or A | @ | Railway's target |
| WWW subdomain | CNAME | www | Railway's target |

---

## Troubleshooting

### Domain Not Working
- Wait up to 48 hours for DNS propagation
- Verify no typos in DNS records
- Check Railway dashboard for verification status
- Clear browser cache and try incognito mode

### SSL Certificate Not Active
- Railway auto-provisions SSL after DNS verification
- Can take up to 24 hours after DNS propagates
- Check Railway logs for any errors

### "This site can't be reached"
- DNS records may not have propagated yet
- Verify CNAME target is exactly as Railway provided
- Check if old A records are conflicting

---

## Timeline Estimate

| Task | Time |
|------|------|
| Create website | 1-2 hours |
| Deploy to Railway | 15-30 minutes |
| Configure DNS | 10-15 minutes |
| DNS propagation | 5 min - 48 hours |
| **Total** | **~2-4 hours** (plus propagation wait) |

---

## Next Steps After Launch
- [ ] Add more blog posts
- [ ] Set up analytics (Plausible, Fathom, or Google Analytics)
- [ ] Add RSS feed
- [ ] Consider a CMS for easier content management
- [ ] Set up email with custom domain (optional)
