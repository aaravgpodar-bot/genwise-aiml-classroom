# GenWise AI/ML Classroom

GenWise AI/ML Classroom is a classroom portal for AI/ML learning. It includes:

- Email/password accounts with instant student/teacher access
- Student and teacher role selection at signup
- Teacher and student shared resources
- Shared classroom inbox
- Private or class-shared submissions with teacher/class comments
- Teacher-only room
- Saved resources
- Local research assistant that searches classroom resources
- Forgot-password reset codes by email when Resend is configured

## Run Locally

```powershell
python -m pip install -r requirements.txt
python genwise_classroom\app.py
```

Open:

```text
http://127.0.0.1:8777
```

## Accounts

Students and teachers can sign up and enter the classroom right away. Teachers can still change roles, disable accounts, or clean up test accounts from the People view.

Forgot-password emails a reset code when Resend is configured. If `RESEND_API_KEY` is missing, local development falls back to showing the reset code on screen.

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

This is fine for the camp prototype as long as the deployed host keeps `GENWISE_DATA_DIR` persistent.

Supabase is now partially wired in:

- `.env` is loaded automatically when the Flask app starts
- `/api/supabase/status` checks the configured Supabase project and storage bucket
- file uploads are saved locally first, then mirrored to Supabase Storage when bucket policies allow the anon key to upload
- shared files from configured `APP_SLUGS` and shared resource folders are listed from Supabase Storage in Resources and Submissions
- the main app database still uses SQLite until a database password, direct connection string, or service-role key is provided for a safe migration

## Supabase Variables

Keep real Supabase values in `.env`; that file is intentionally ignored by Git. Use `.env.example` as the safe template for deployment setup.

Required values from the instructor:

```text
SUPABASE_URL
SUPABASE_ANON_KEY
SUPABASE_PROJECT_REF
SUPABASE_STORAGE_BUCKET
APP_SLUGS
SUPABASE_SHARED_RESOURCE_PREFIXES
```

Optional values needed for a full Supabase database migration:

```text
SUPABASE_DB_URL
SUPABASE_SERVICE_ROLE_KEY
SUPABASE_DB_PASSWORD
```

If a frontend build later uses Vite directly, mirror the public values with:

```text
VITE_SUPABASE_URL
VITE_SUPABASE_ANON_KEY
```

Multiple app slugs should be stored as one comma-separated value:

```text
APP_SLUGS=aarav-genwise-aiml-classroom,akshaan-class-resource-hub,parnika-class-resource-hub,sohum-code-the-future-dashboard,prayan-genwise-camp,aara
```

Shared class folders outside app slugs can be listed too:

```text
SUPABASE_SHARED_RESOURCE_PREFIXES=class_transcripts
```

## Email Reset Variables

Set these for real forgot-password emails:

```text
RESEND_API_KEY
RESEND_FROM_EMAIL
```

`RESEND_FROM_EMAIL` must be a sender allowed by your Resend account, for example a verified domain sender or Resend's test sender.

## Permanent PythonAnywhere URL

The permanent free URL for this app should be the PythonAnywhere subdomain:

```text
https://AaravG13.pythonanywhere.com
```

Cloudflare Tunnel links are useful for testing but can change. Use PythonAnywhere for the permanent camp link.

### PythonAnywhere Setup

In the PythonAnywhere Web tab:

1. Set the source code directory to the cloned repo folder, for example:

```text
/home/AaravG13/genwise-aiml-classroom
```

2. Edit the WSGI configuration file and use the contents of `pythonanywhere_wsgi.py`.

3. Add these environment variables in the WSGI file before importing the app, or in PythonAnywhere's environment variable UI if available:

```text
GENWISE_SECRET_KEY=<long-random-secret>
GENWISE_DATA_DIR=/home/AaravG13/genwise_data
SUPABASE_URL=https://lccnubtvrjlihvyrowgq.supabase.co
SUPABASE_ANON_KEY=<anon-key>
SUPABASE_PROJECT_REF=lccnubtvrjlihvyrowgq
SUPABASE_STORAGE_BUCKET=class-resources
APP_SLUGS=aarav-genwise-aiml-classroom,akshaan-class-resource-hub,parnika-class-resource-hub,sohum-code-the-future-dashboard,prayan-genwise-camp,aara
SUPABASE_SHARED_RESOURCE_PREFIXES=class_transcripts
```

4. Run this once in a PythonAnywhere Bash console:

```bash
cd /home/AaravG13/genwise-aiml-classroom
python -m pip install --user -r requirements.txt
mkdir -p /home/AaravG13/genwise_data
```

5. Reload the web app from the PythonAnywhere Web tab.

After reload, `/health` should return JSON instead of the default PythonAnywhere page.
