# GenWise AI/ML Classroom Handoff

Use this file to continue work in a new chat/thread.

## Project

Repository:

```text
https://github.com/aaravgpodar-bot/genwise-aiml-classroom
```

Local workspace:

```text
C:\Users\Aarav\Desktop\GenWise Folder\genwise-aiml-classroom
```

Permanent app URL:

```text
https://AaravG13.pythonanywhere.com
```

Temporary/testing URLs used earlier:

```text
http://127.0.0.1:8777/
https://subsequent-workout-probe-officer.trycloudflare.com
```

The temporary Cloudflare URL is not permanent. The PythonAnywhere URL is the one intended for camp use.

## App Goal

This app is for a summer camp AI/ML classroom. It should let students and instructors:

- sign in and use the same global app
- see a dashboard
- receive assignments
- upload and share files/resources
- see files uploaded by other apps/students/instructors through Supabase Storage
- send messages or inbox-style updates
- comment on work or submissions
- save useful items
- reset passwords

No teacher approval is required for either students or teachers.

## Current Architecture

The app is a Flask app.

Important files:

```text
genwise_classroom/app.py
genwise_classroom/supabase_integration.py
genwise_classroom/static/app.js
genwise_classroom/static/styles.css
genwise_classroom/templates/index.html
pythonanywhere_wsgi.py
README.md
.env.example
```

The main classroom database is still SQLite on the deployed host. Supabase is currently used for uploaded/shared files in Storage, not for hosting the whole app and not for the whole app database.

## Supabase Details

Supabase project URL:

```text
https://lccnubtvrjlihvyrowgq.supabase.co
```

Project ref:

```text
lccnubtvrjlihvyrowgq
```

Storage bucket:

```text
class-resources
```

Important environment variables:

```text
SUPABASE_URL
SUPABASE_ANON_KEY
SUPABASE_PROJECT_REF
SUPABASE_STORAGE_BUCKET
APP_SLUGS
SUPABASE_SHARED_RESOURCE_PREFIXES
VITE_SUPABASE_URL
VITE_SUPABASE_ANON_KEY
RESEND_API_KEY
RESEND_FROM_EMAIL
```

Do not commit real secrets. Put real values in `.env` locally or PythonAnywhere environment/WSGI config.

Known app slugs:

```text
aarav-genwise-aiml-classroom
akshaan-class-resource-hub
parnika-class-resource-hub
sohum-code-the-future-dashboard
prayan-genwise-camp
aara
```

Current shared resource folder outside app slugs:

```text
class_transcripts
```

Recommended value:

```text
SUPABASE_SHARED_RESOURCE_PREFIXES=class_transcripts
```

## What Was Changed

Recent commits pushed to GitHub:

```text
e62ffed Redesign classroom sharing flow
dc232a7 Sync uploaded files with Supabase storage
839346a Add PythonAnywhere permanent deployment entrypoint
1f15755 Add pg8000 deployment dependency
2cdb7f9 Make PostgreSQL driver optional
a0c7188 Show Supabase resources on dashboard
ced95b7 Email reset codes and improve dashboard uploads
eca4fc4 Show shared transcript uploads from Supabase
```

Main changes:

- Instant signup/no approval for students or teachers.
- Uploads save locally and mirror into Supabase Storage.
- Resources page includes cloud-only files from Supabase.
- Dashboard includes cloud resources, local resources, stats, and a cleaner layout.
- Shared pages auto-refresh every 60 seconds.
- Forgot password flow was added.
- Password reset emails use Resend if configured.
- If Resend is not configured, local development falls back to showing a reset code on screen.
- Supabase resources scanner now includes:
  - each configured app slug root
  - each configured app slug `resources/` folder
  - shared folders from `SUPABASE_SHARED_RESOURCE_PREFIXES`, currently `class_transcripts`

## Full Bucket Check Result

The entire `class-resources` Supabase Storage bucket was checked directly.

At the time of checking, the bucket had 30 total files.

The 4 newest files were in:

```text
class_transcripts/
```

Files:

```text
class_transcripts/16 June 2026 - class beat-by-beat.md
class_transcripts/16th June.txt
class_transcripts/17th June part 1.txt
class_transcripts/18th June.txt
```

Before the latest fix, the app missed them because it was only looking inside app slug folders. After commit `eca4fc4`, the app resource loader sees those transcript files.

After the fix, the app's resource loader found 9 shared Supabase resources:

```text
class_transcripts/16 June 2026 - class beat-by-beat.md
class_transcripts/16th June.txt
class_transcripts/17th June part 1.txt
class_transcripts/18th June.txt
parnika-class-resource-hub/resources/1781767308676-supabase-student-env-handoff-1-copy.md
akshaan-class-resource-hub/res_3d7799e615fe0a66-preview-test.html
akshaan-class-resource-hub/res_a1810ddcebe2358e-html_to_md_converter.html
prayan-genwise-camp/mqj53cfa-1janak-crystallization-from-hcl-2.html
prayan-genwise-camp/resources/mqj4lfxi-cv69ml-ai-learning-playground.html
```

The bucket also contains app build files under folders like:

```text
parnika-class-resource-hub/app-v2/
parnika-class-resource-hub/app-v3/
parnika-class-resource-hub/site/
```

Those are intentionally not shown as class resources.

## Deployment Status

The live app health endpoint was checked and returned OK:

```text
https://AaravG13.pythonanywhere.com/health
```

Expected health response shape:

```json
{
  "app": "GenWise AI/ML Classroom",
  "database_mode": "sqlite",
  "ok": true,
  "supabase_configured": true
}
```

Important: the newest GitHub code may not appear on PythonAnywhere until the web app is reloaded from the PythonAnywhere Web tab.

To deploy latest code on PythonAnywhere:

1. Open PythonAnywhere.
2. Go to the Web tab.
3. Open `AaravG13.pythonanywhere.com`.
4. Click Reload.
5. Hard refresh the app page.

The WSGI file on PythonAnywhere was previously set up to pull from GitHub on startup/reload, but if the live UI looks unchanged, reload is the first thing to check.

## UI Notes

The dashboard UI was updated in code. It should include:

- a Live Classroom hero area
- stats strip
- cloud resources card
- recent local resources card
- inbox updates
- saved items

If the UI still looks the same on the permanent site, likely causes are:

- PythonAnywhere has not reloaded the newest commit
- browser cache needs a hard refresh
- static files are cached

## Forgot Password / Email

Forgot password support exists in code.

For real email reset codes, configure:

```text
RESEND_API_KEY
RESEND_FROM_EMAIL
```

If `RESEND_API_KEY` is missing, reset codes may only appear in local fallback mode and will not actually email users.

## Next Useful Tasks

High priority:

- Reload PythonAnywhere so commit `eca4fc4` is live.
- Verify the dashboard UI changed on the permanent site.
- Verify the Resources tab shows the 4 `class_transcripts` uploads.
- Configure Resend if real forgot-password emails are required.

Medium priority:

- Add clearer labels/filtering for Supabase cloud files.
- Add a manual refresh button near Resources.
- Add a teacher-only view for all storage uploads.
- Decide whether the SQLite classroom database should eventually migrate to Supabase Postgres.

Useful commands:

```powershell
cd "C:\Users\Aarav\Desktop\GenWise Folder\genwise-aiml-classroom"
git status --short
git log --oneline -5
```

To inspect app-visible Supabase resources locally:

```powershell
$env:PYTHONPATH='.'
python -c "from genwise_classroom.app import supabase_shared_files; files, errors = supabase_shared_files('resources'); print(len(files)); print([f['title'] for f in files[:10]]); print(errors)"
```

## Notes For Future Chat

The user wants Codex to take action directly rather than only explain steps. They want the app to be global/permanent and to keep Supabase uploads visible across everyone else's apps. They also want commits pushed to GitHub regularly when code changes are made.

Do not expose the real Supabase anon key or other secrets in chat or committed files.
