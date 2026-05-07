# Deploying to GitHub Pages

## Step 1: Initialize Git Repository (if not already done)

```bash
cd ~/ubik2
git init
git add docs/
git commit -m "Initial commit: iMessage stats dashboard"
```

## Step 2: Create GitHub Repository

1. Go to https://github.com/new
2. Name your repository (e.g., `imessage-stats`)
3. Make it **Private** (your personal message data!)
4. Don't initialize with README/gitignore
5. Click "Create repository"

## Step 3: Push to GitHub

```bash
# Replace YOUR_USERNAME and YOUR_REPO with your details
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git branch -M main
git push -u origin main
```

## Step 4: Enable GitHub Pages

1. Go to your repository on GitHub
2. Click **Settings** → **Pages** (in left sidebar)
3. Under "Source", select **Deploy from a branch**
4. Under "Branch", select **main** and **/docs** folder
5. Click **Save**

## Step 5: Access Your Site

After a few minutes, your site will be live at:
```
https://YOUR_USERNAME.github.io/YOUR_REPO/
```

## Updating Your Stats

Whenever you want to refresh your stats:

```bash
cd ~/ubik2
python3 generate_report.py  # Regenerate data.json
git add docs/data.json
git commit -m "Update stats"
git push
```

GitHub Pages will automatically rebuild (takes 1-2 minutes).

## Privacy Note

- Keep your repository **PRIVATE** to protect your personal message data
- Only the `docs/` folder is deployed (no source code or database access)
- Consider adding password protection via GitHub Pages settings if needed

## Local Preview

To preview locally before deploying:

```bash
cd ~/ubik2/docs
python3 -m http.server 8000
# Open http://localhost:8000 in your browser
```
