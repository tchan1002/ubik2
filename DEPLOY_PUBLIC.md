# Deploying to Public GitHub Pages (Safe)

## ⚠️ IMPORTANT: Privacy Protection

This guide helps you deploy the **visualization** publicly while keeping your **personal data private**.

## What Gets Committed (Safe for Public)

✅ HTML/CSS/JS code (`docs/index.html`)
✅ Documentation (`README.md`, `CLAUDE.md`)
✅ Source code (`src/` folder - just analysis logic, no data)
✅ Sample anonymized data (`docs/data.sample.json`)

## What NEVER Gets Committed (Private Data)

❌ Your actual message data (`docs/data.json`) - **GITIGNORED**
❌ Contact names (`contact_names.json`, `*.vcf`) - **GITIGNORED**
❌ iMessage database (`*.db`) - **GITIGNORED**
❌ Debug scripts with phone numbers - **GITIGNORED**

## Step 1: Verify .gitignore is Working

```bash
cd ~/ubik2

# Check what would be committed
git status

# You should NOT see:
# - docs/data.json
# - *.vcf files
# - contact_names.json
# - *.db files

# If you see any of these, they're NOT properly gitignored!
```

## Step 2: Initialize Git (First Time Only)

```bash
cd ~/ubik2
git init
git add .
git commit -m "Initial commit: iMessage analysis tool"
```

## Step 3: Create PUBLIC GitHub Repository

1. Go to https://github.com/new
2. Repository name: `imessage-stats` (or your choice)
3. **Set to PUBLIC** ✅
4. Don't initialize with README
5. Click "Create repository"

## Step 4: Push to GitHub

```bash
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git branch -M main
git push -u origin main
```

## Step 5: Setup GitHub Pages

1. Go to repository → **Settings** → **Pages**
2. Source: **Deploy from a branch**
3. Branch: **main** → **/docs**
4. Click **Save**

## Step 6: Use Sample Data or Your Own

### Option A: Use Anonymized Sample Data (Safe for Public)
```bash
cd ~/ubik2/docs
cp data.sample.json data.json
git add data.json
git commit -m "Add sample data"
git push
```

### Option B: Host Your Real Data Elsewhere (Recommended)

Keep your real `data.json` private and host it separately:

1. **Host on private server** (e.g., Dropbox, Google Drive with direct link)
2. **Update `index.html`** to fetch from your private URL:

```javascript
// In docs/index.html, change:
const response = await fetch('data.json');

// To:
const response = await fetch('https://your-private-url.com/data.json');
```

3. Enable CORS on your private hosting

### Option C: Password-Protect Your Page

Use a service like:
- **Cloudflare Pages** (with Access)
- **Vercel** (with password protection)
- **Netlify** (with password protection)

## Step 7: Verify Privacy

Before making public, double-check:

```bash
# See exactly what files are tracked
git ls-files

# Verify docs/data.json is NOT in this list
# Verify *.vcf files are NOT in this list
# Verify contact_names.json is NOT in this list
```

## Updating Your Private Stats

Your workflow:
1. Generate new stats: `python3 generate_report.py` (creates `docs/data.json` locally)
2. View locally: Open `http://localhost:8000`
3. **DON'T commit `data.json`** - it's gitignored!
4. Only push code changes, never data

## Emergency: If You Accidentally Committed Sensitive Data

```bash
# Remove file from git history
git filter-branch --force --index-filter \
  "git rm --cached --ignore-unmatch docs/data.json" \
  --prune-empty --tag-name-filter cat -- --all

# Force push (WARNING: destructive!)
git push origin --force --all
```

## Best Practice: Two Repos

Consider using two separate repos:
1. **Private repo**: Full codebase + your real data
2. **Public repo**: Just the visualization code + sample data
