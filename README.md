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
