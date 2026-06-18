# GenWise AI/ML Classroom

GenWise AI/ML Classroom is a classroom portal for AI/ML learning. It includes:

- Email/password accounts with teacher approval
- Student and teacher role selection at signup
- Teacher-posted resources
- Student resource uploads for teacher review
- Shared classroom inbox
- Private student submissions with teacher comments
- Teacher-only room
- Saved resources
- Local research assistant that searches classroom resources

## Run Locally

```powershell
python -m pip install -r requirements.txt
python genwise_classroom\app.py
```

Open:

```text
http://127.0.0.1:8777
```

## First Teacher Account

On a fresh database, the first person to sign up becomes the first approved teacher automatically. Everyone after that waits for teacher approval.

## Deployment

This repo includes `render.yaml` for Render deployment.

Use these settings if configuring manually:

- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn genwise_classroom.app:app --bind 0.0.0.0:$PORT`
- Health check: `/health`
- Environment variables:
  - `GENWISE_SECRET_KEY`: a long random secret
  - `GENWISE_DATA_DIR`: persistent data directory, such as `/var/data`

For real classroom use, choose hosting with persistent disk/storage because uploads and the SQLite database must survive restarts.

## Current No-Supabase Mode

The app currently runs without Supabase. It uses:

- SQLite for accounts, assignments, posts, saved items, submissions, comments, and notifications
- Local upload folders under `GENWISE_DATA_DIR`
- Flask sessions for login

This is fine for the camp prototype as long as the deployed host keeps `GENWISE_DATA_DIR` persistent. When Supabase credentials are available, the main migration targets are the database tables first, then file storage if the instructor wants Supabase Storage too.

## Supabase Variables

Keep real Supabase values in `.env`; that file is intentionally ignored by Git. Use `.env.example` as the safe template for deployment setup.

Required values from the instructor:

```text
SUPABASE_URL
SUPABASE_ANON_KEY
SUPABASE_PROJECT_REF
SUPABASE_STORAGE_BUCKET
APP_SLUGS
```

If a frontend build later uses Vite directly, mirror the public values with:

```text
VITE_SUPABASE_URL
VITE_SUPABASE_ANON_KEY
```

Multiple app slugs should be stored as one comma-separated value:

```text
APP_SLUGS=akshaan-class-resource-hub,parnika-class-resource-hub,sohum-code-the-future-dashboard,prayan-genwise-camp,aara
```

## Permanent Free URL Options

For this Flask app, the most practical free permanent URL is PythonAnywhere's free web app subdomain:

```text
yourusername.pythonanywhere.com
```

Cloudflare Tunnel links are useful for testing but can change. GitHub Pages and Cloudflare Pages provide stable free subdomains, but they are designed for static sites, so they would only host a future frontend unless the Flask backend lives somewhere else.
