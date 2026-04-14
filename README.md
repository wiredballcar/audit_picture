# Koramangala Footpath Audit — 2026
Flask + Supabase + Render

## Local setup

```bash
cd koramangala-audit
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py
# open http://localhost:5000
```

## Deploy to Render (free)

### Step 1 — Push to GitHub
```bash
git init
git add .
git commit -m "Initial commit"
# create a new repo on github.com, then:
git remote add origin https://github.com/YOUR_USERNAME/koramangala-audit.git
git push -u origin main
```

### Step 2 — Create Web Service on Render
1. Go to **render.com** → New → **Web Service**
2. Connect your GitHub repo
3. Settings:
   - **Runtime:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app --workers 2 --bind 0.0.0.0:$PORT`
4. Click **Advanced** → Add Environment Variables:
   ```
   SUPABASE_URL   = https://jvbifpnkqtxktyguzhhw.supabase.co
   SUPABASE_KEY   = eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
   STADIA_API_KEY = 9bc66456-b7ec-4cad-8848-5b5210d8a2d6
   ```
5. Click **Create Web Service** — deploy takes ~2 min

### Step 3 — Set up Supabase tables (first time only)
Run `supabase_setup.sql` in Supabase Dashboard → SQL Editor

Your site will be live at `https://koramangala-audit.onrender.com`

## Supabase tables
- `roads` — road details + GPS coords
- `photos` — metadata + public URL (files in Storage bucket `audit-photos`)
- `complaints` — complaints per road
- `drive_links` — Google Drive / Form links per road

## Notes
- `.env` is gitignored — never commit it
- Free Render tier spins down after 15 min inactivity (first load ~30s)
- Upgrade to Render Starter ($7/mo) for always-on
