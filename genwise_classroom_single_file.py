# GenWise AI/ML Classroom - single-file version
# Run with: python genwise_classroom_single_file.py

import json
import os
import secrets
import shutil
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from flask import (
    Flask,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename


ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("GENWISE_DATA_DIR", str(ROOT_DIR / "instance")))
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "genwise.db"

STUDENT_UPLOAD_LIMIT = 200 * 1024 * 1024
TEACHER_UPLOAD_LIMIT = 600 * 1024 * 1024
APP_UPLOAD_LIMIT = TEACHER_UPLOAD_LIMIT + (5 * 1024 * 1024)

BLOCKED_EXTENSIONS = {
    ".apk",
    ".app",
    ".bat",
    ".cmd",
    ".com",
    ".dmg",
    ".exe",
    ".jar",
    ".lnk",
    ".msi",
    ".ps1",
    ".reg",
    ".scr",
    ".vbs",
}

PREVIEW_MIME_PREFIXES = ("image/", "text/")
PREVIEW_EXTENSIONS = {".pdf", ".md", ".csv", ".json", ".html", ".css", ".js", ".py", ".txt"}


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = APP_UPLOAD_LIMIT


def load_secret_key() -> str:
    env_secret = os.getenv("GENWISE_SECRET_KEY", "").strip()
    if env_secret:
        return env_secret
    ensure_dirs()
    secret_path = DATA_DIR / "secret_key.txt"
    if secret_path.exists():
        return secret_path.read_text(encoding="utf-8").strip()
    secret = secrets.token_urlsafe(48)
    secret_path.write_text(secret, encoding="utf-8")
    return secret


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_dirs() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    for bucket in ("resources", "resource_reviews", "submissions", "inbox", "teacher_room"):
        (UPLOAD_DIR / bucket).mkdir(parents=True, exist_ok=True)


app.config["SECRET_KEY"] = load_secret_key()


INDEX_HTML = '<!doctype html>\n<html lang="en">\n<head>\n  <meta charset="utf-8">\n  <meta name="viewport" content="width=device-width, initial-scale=1">\n  <title>GenWise AI/ML Classroom</title>\n  <style>\n:root {\n  color-scheme: light;\n  --bg: #f3f7f7;\n  --surface: #ffffff;\n  --surface-soft: #eaf2f1;\n  --ink: #172221;\n  --muted: #5f706f;\n  --line: #c9d9d6;\n  --primary: #147d76;\n  --primary-strong: #0b5f5a;\n  --accent: #cb7a14;\n  --coral: #bd4c5c;\n  --blue: #276da8;\n  --good: #1f8a54;\n  --shadow: 0 18px 40px rgba(24, 45, 47, 0.12);\n  --radius: 8px;\n}\n\nbody.dark {\n  color-scheme: dark;\n  --bg: #101416;\n  --surface: #182022;\n  --surface-soft: #202d2f;\n  --ink: #edf6f4;\n  --muted: #a8bbb7;\n  --line: #35494a;\n  --primary: #4cc5b8;\n  --primary-strong: #86ddd5;\n  --accent: #e5a342;\n  --coral: #ff7b8a;\n  --blue: #78b7ed;\n  --good: #78d69e;\n  --shadow: 0 18px 44px rgba(0, 0, 0, 0.32);\n}\n\n* {\n  box-sizing: border-box;\n}\n\nbody {\n  margin: 0;\n  min-height: 100vh;\n  font-family: "Segoe UI", Arial, sans-serif;\n  color: var(--ink);\n  background:\n    linear-gradient(90deg, color-mix(in srgb, var(--primary) 9%, transparent) 1px, transparent 1px),\n    linear-gradient(color-mix(in srgb, var(--primary) 8%, transparent) 1px, transparent 1px),\n    var(--bg);\n  background-size: 34px 34px;\n}\n\nbutton,\ninput,\nselect,\ntextarea {\n  font: inherit;\n}\n\nbutton {\n  min-height: 40px;\n  border: 1px solid var(--line);\n  border-radius: var(--radius);\n  color: var(--ink);\n  background: var(--surface);\n  cursor: pointer;\n  font-weight: 750;\n  padding: 9px 12px;\n}\n\nbutton:hover {\n  border-color: var(--primary);\n  color: var(--primary-strong);\n}\n\nbutton:disabled {\n  cursor: not-allowed;\n  opacity: 0.58;\n}\n\n.primary {\n  color: #ffffff;\n  background: var(--primary);\n  border-color: var(--primary-strong);\n}\n\n.primary:hover {\n  color: #ffffff;\n  background: var(--primary-strong);\n}\n\n.danger {\n  color: var(--coral);\n  border-color: color-mix(in srgb, var(--coral) 45%, var(--line));\n}\n\n.soft-button {\n  background: var(--surface-soft);\n}\n\n.link-button {\n  min-height: 0;\n  padding: 0;\n  border: 0;\n  border-radius: 0;\n  color: var(--blue);\n  background: transparent;\n  font-weight: 900;\n  text-decoration: underline;\n}\n\n.link-button:hover {\n  color: var(--primary-strong);\n  background: transparent;\n}\n\na {\n  color: var(--blue);\n  font-weight: 700;\n}\n\nh1,\nh2,\nh3,\np {\n  margin-top: 0;\n}\n\nlabel {\n  display: grid;\n  gap: 7px;\n  color: var(--muted);\n  font-size: 13px;\n  font-weight: 800;\n}\n\ninput,\nselect,\ntextarea {\n  width: 100%;\n  border: 1px solid var(--line);\n  border-radius: var(--radius);\n  color: var(--ink);\n  background: var(--surface);\n  outline: none;\n}\n\ninput,\nselect {\n  min-height: 42px;\n  padding: 0 11px;\n}\n\ntextarea {\n  resize: vertical;\n  min-height: 82px;\n  padding: 11px;\n  line-height: 1.45;\n}\n\ninput:focus,\nselect:focus,\ntextarea:focus {\n  border-color: var(--primary);\n  box-shadow: 0 0 0 3px color-mix(in srgb, var(--primary) 18%, transparent);\n}\n\n.hidden {\n  display: none !important;\n}\n\n#toast {\n  position: fixed;\n  right: 18px;\n  top: 18px;\n  z-index: 10;\n  display: grid;\n  gap: 8px;\n}\n\n.toast {\n  max-width: min(420px, calc(100vw - 36px));\n  padding: 12px 14px;\n  border-radius: var(--radius);\n  background: var(--surface);\n  border: 1px solid var(--line);\n  box-shadow: var(--shadow);\n  font-weight: 700;\n}\n\n.toast.error {\n  border-color: var(--coral);\n  color: var(--coral);\n}\n\n.auth-shell {\n  width: min(1120px, calc(100vw - 28px));\n  margin: 0 auto;\n  min-height: 100vh;\n  display: grid;\n  align-content: center;\n  gap: 22px;\n  padding: 28px 0;\n}\n\n.auth-brand {\n  display: flex;\n  align-items: center;\n  gap: 16px;\n}\n\n.auth-brand h1 {\n  margin-bottom: 8px;\n  font-size: clamp(31px, 5vw, 54px);\n  letter-spacing: 0;\n}\n\n.auth-brand p {\n  max-width: 720px;\n  color: var(--muted);\n  font-size: 17px;\n  line-height: 1.5;\n}\n\n.brand-mark {\n  width: 54px;\n  height: 54px;\n  flex: 0 0 auto;\n  display: grid;\n  place-items: center;\n  border-radius: 8px;\n  color: #ffffff;\n  background:\n    linear-gradient(135deg, var(--primary), var(--blue) 54%, var(--accent));\n  font-weight: 900;\n  box-shadow: 0 14px 28px color-mix(in srgb, var(--primary) 24%, transparent);\n}\n\n.auth-grid {\n  display: grid;\n  grid-template-columns: repeat(2, minmax(0, 1fr));\n  gap: 18px;\n}\n\n.panel {\n  background: var(--surface);\n  border: 1px solid var(--line);\n  border-radius: var(--radius);\n  box-shadow: var(--shadow);\n}\n\n.auth-card {\n  padding: 18px;\n  display: grid;\n  gap: 14px;\n  align-self: start;\n}\n\n.panel-heading {\n  display: flex;\n  justify-content: space-between;\n  align-items: start;\n  gap: 12px;\n  padding-bottom: 12px;\n  border-bottom: 1px solid var(--line);\n}\n\n.panel-heading h2 {\n  margin: 0;\n  font-size: 18px;\n  line-height: 1.2;\n}\n\n.panel-heading span {\n  color: var(--muted);\n  font-size: 12px;\n  font-weight: 800;\n  text-align: right;\n}\n\n.hint {\n  margin: 0;\n  color: var(--muted);\n  font-size: 12px;\n  line-height: 1.45;\n}\n\n.app-shell {\n  min-height: 100vh;\n  display: grid;\n  grid-template-columns: 260px 1fr;\n}\n\n.sidebar {\n  position: sticky;\n  top: 0;\n  height: 100vh;\n  padding: 16px;\n  display: grid;\n  grid-template-rows: auto 1fr auto;\n  gap: 18px;\n  background: color-mix(in srgb, var(--surface) 92%, var(--primary) 8%);\n  border-right: 1px solid var(--line);\n}\n\n.brand-block {\n  display: flex;\n  align-items: center;\n  gap: 12px;\n}\n\n.brand-block strong {\n  display: block;\n  font-size: 20px;\n}\n\n.brand-block span {\n  color: var(--muted);\n  font-size: 12px;\n  font-weight: 800;\n}\n\n.nav-list {\n  display: grid;\n  align-content: start;\n  gap: 8px;\n}\n\n.nav-button {\n  width: 100%;\n  text-align: left;\n  background: transparent;\n  border-color: transparent;\n}\n\n.nav-button.active {\n  color: #ffffff;\n  background: var(--primary);\n  border-color: var(--primary-strong);\n}\n\n.main {\n  min-width: 0;\n  padding: 16px;\n  display: grid;\n  grid-template-rows: auto 1fr;\n  gap: 16px;\n}\n\n.topbar {\n  display: flex;\n  justify-content: space-between;\n  align-items: center;\n  gap: 16px;\n  padding: 14px 16px;\n  border: 1px solid var(--line);\n  border-radius: var(--radius);\n  background: var(--surface);\n  box-shadow: var(--shadow);\n}\n\n.topbar h1 {\n  margin: 0;\n  font-size: 28px;\n  letter-spacing: 0;\n}\n\n.eyebrow {\n  margin: 0 0 4px;\n  color: var(--accent);\n  font-size: 12px;\n  font-weight: 900;\n  text-transform: uppercase;\n  letter-spacing: 0.08em;\n}\n\n.top-actions {\n  display: flex;\n  align-items: center;\n  justify-content: flex-end;\n  gap: 10px;\n  flex-wrap: wrap;\n}\n\n.user-pill {\n  display: inline-flex;\n  align-items: center;\n  min-height: 40px;\n  padding: 0 12px;\n  border: 1px solid var(--line);\n  border-radius: 999px;\n  background: var(--surface-soft);\n  font-size: 13px;\n  font-weight: 800;\n  white-space: nowrap;\n}\n\n.view {\n  display: none;\n}\n\n.active-view {\n  display: grid;\n  gap: 16px;\n  align-content: start;\n}\n\n.dashboard-grid {\n  display: grid;\n  grid-template-columns: repeat(3, minmax(0, 1fr));\n  gap: 16px;\n}\n\n.dashboard-card {\n  padding: 16px;\n  display: grid;\n  gap: 12px;\n  align-content: start;\n  min-height: 190px;\n}\n\n.dashboard-card h2 {\n  font-size: 18px;\n  margin: 0;\n}\n\n.metric-row {\n  display: flex;\n  align-items: center;\n  justify-content: space-between;\n  gap: 12px;\n  padding: 10px 0;\n  border-bottom: 1px solid var(--line);\n}\n\n.metric-row:last-child {\n  border-bottom: 0;\n}\n\n.metric-row strong {\n  font-size: 22px;\n  color: var(--primary-strong);\n}\n\n.section-tools {\n  display: flex;\n  justify-content: space-between;\n  align-items: center;\n  gap: 12px;\n  flex-wrap: wrap;\n}\n\n.search-box {\n  flex: 1 1 420px;\n  display: flex;\n  gap: 8px;\n}\n\n.segmented {\n  display: flex;\n  gap: 6px;\n  padding: 5px;\n  border: 1px solid var(--line);\n  border-radius: var(--radius);\n  background: var(--surface-soft);\n}\n\n.segmented button {\n  border-color: transparent;\n  background: transparent;\n}\n\n.segmented button.active {\n  color: #ffffff;\n  background: var(--primary);\n}\n\n.form-grid {\n  padding: 16px;\n  display: grid;\n  grid-template-columns: repeat(2, minmax(0, 1fr));\n  gap: 14px;\n}\n\n.full-span {\n  grid-column: 1 / -1;\n}\n\n.check-line {\n  grid-template-columns: auto 1fr;\n  align-items: center;\n  align-content: center;\n  color: var(--ink);\n}\n\n.check-line input {\n  width: 18px;\n  height: 18px;\n}\n\n.role-picker {\n  margin: 0;\n  padding: 0;\n  border: 0;\n  display: grid;\n  grid-template-columns: repeat(2, minmax(0, 1fr));\n  gap: 8px;\n}\n\n.role-picker legend {\n  grid-column: 1 / -1;\n  margin-bottom: 7px;\n  color: var(--muted);\n  font-size: 13px;\n  font-weight: 900;\n}\n\n.role-picker label {\n  position: relative;\n  display: flex;\n  align-items: center;\n  justify-content: center;\n  min-height: 42px;\n  padding: 0 10px;\n  border: 1px solid var(--line);\n  border-radius: var(--radius);\n  color: var(--ink);\n  background: var(--surface-soft);\n  cursor: pointer;\n  font-weight: 850;\n}\n\n.role-picker input {\n  position: absolute;\n  opacity: 0;\n  pointer-events: none;\n}\n\n.role-picker label:has(input:checked) {\n  color: #ffffff;\n  border-color: var(--primary-strong);\n  background: var(--primary);\n}\n\n.item-grid {\n  display: grid;\n  grid-template-columns: repeat(3, minmax(0, 1fr));\n  gap: 14px;\n}\n\n.item-grid.list-mode {\n  display: grid;\n  grid-template-columns: 1fr;\n}\n\n.item-card {\n  padding: 15px;\n  display: grid;\n  gap: 12px;\n  align-content: start;\n  min-width: 0;\n}\n\n.list-mode .item-card {\n  grid-template-columns: minmax(0, 1.1fr) minmax(0, 1.6fr) auto;\n  align-items: center;\n}\n\n.item-title-row {\n  display: flex;\n  align-items: flex-start;\n  justify-content: space-between;\n  gap: 10px;\n}\n\n.item-card h3 {\n  margin: 0;\n  font-size: 18px;\n  line-height: 1.25;\n  overflow-wrap: anywhere;\n}\n\n.item-meta {\n  color: var(--muted);\n  font-size: 12px;\n  font-weight: 750;\n  line-height: 1.4;\n}\n\n.item-body {\n  color: var(--muted);\n  line-height: 1.45;\n  overflow-wrap: anywhere;\n}\n\n.badge-row {\n  display: flex;\n  flex-wrap: wrap;\n  gap: 6px;\n}\n\n.badge {\n  display: inline-flex;\n  align-items: center;\n  min-height: 24px;\n  padding: 3px 8px;\n  border-radius: 999px;\n  border: 1px solid var(--line);\n  background: var(--surface-soft);\n  color: var(--muted);\n  font-size: 12px;\n  font-weight: 850;\n}\n\n.pinned {\n  color: #ffffff;\n  border-color: var(--accent);\n  background: var(--accent);\n}\n\n.action-row {\n  display: flex;\n  gap: 8px;\n  flex-wrap: wrap;\n}\n\n.feed {\n  display: grid;\n  gap: 14px;\n}\n\n.feed-post {\n  padding: 16px;\n  display: grid;\n  gap: 12px;\n}\n\n.reply-list {\n  display: grid;\n  gap: 8px;\n  padding-left: 12px;\n  border-left: 3px solid var(--line);\n}\n\n.reply {\n  padding: 10px;\n  border-radius: var(--radius);\n  background: var(--surface-soft);\n}\n\n.reply p {\n  margin: 5px 0 0;\n  line-height: 1.45;\n}\n\n.reply-form,\n.chat-row {\n  display: flex;\n  gap: 8px;\n  align-items: end;\n}\n\n.reply-form textarea,\n.chat-row textarea {\n  min-height: 46px;\n}\n\n.table-wrap {\n  overflow-x: auto;\n}\n\ntable {\n  width: 100%;\n  border-collapse: collapse;\n  min-width: 760px;\n}\n\nth,\ntd {\n  padding: 12px;\n  border-bottom: 1px solid var(--line);\n  text-align: left;\n  vertical-align: top;\n}\n\nth {\n  color: var(--muted);\n  font-size: 12px;\n  text-transform: uppercase;\n  letter-spacing: 0.05em;\n}\n\n.ai-layout {\n  display: grid;\n  grid-template-columns: 340px 1fr;\n  gap: 16px;\n}\n\n.stacked {\n  padding: 16px;\n  display: grid;\n  gap: 14px;\n  align-content: start;\n}\n\n.ai-chat {\n  display: grid;\n  grid-template-rows: auto minmax(360px, 1fr) auto;\n  min-height: calc(100vh - 150px);\n}\n\n.ai-chat .panel-heading {\n  padding: 16px;\n}\n\n.ai-messages {\n  padding: 16px;\n  display: grid;\n  gap: 12px;\n  align-content: start;\n  overflow: auto;\n}\n\n.ai-bubble {\n  max-width: 82%;\n  padding: 12px 14px;\n  border-radius: var(--radius);\n  background: var(--surface-soft);\n  line-height: 1.48;\n  white-space: pre-wrap;\n}\n\n.ai-bubble.user {\n  justify-self: end;\n  color: #ffffff;\n  background: var(--primary);\n}\n\n.ai-bubble.assistant {\n  justify-self: start;\n}\n\n.ai-citations {\n  margin-top: 8px;\n  color: var(--muted);\n  font-size: 12px;\n  font-weight: 800;\n}\n\n.chat-row {\n  padding: 16px;\n  border-top: 1px solid var(--line);\n}\n\ndialog {\n  width: min(820px, calc(100vw - 28px));\n  max-height: min(760px, calc(100vh - 28px));\n  border: 1px solid var(--line);\n  border-radius: var(--radius);\n  color: var(--ink);\n  background: var(--surface);\n  box-shadow: var(--shadow);\n}\n\ndialog::backdrop {\n  background: rgba(0, 0, 0, 0.42);\n}\n\n.dialog-head {\n  display: flex;\n  align-items: center;\n  justify-content: space-between;\n  gap: 12px;\n  padding-bottom: 12px;\n  border-bottom: 1px solid var(--line);\n}\n\n.dialog-head h2 {\n  margin: 0;\n}\n\n.comment-thread {\n  display: grid;\n  gap: 10px;\n  margin-top: 14px;\n}\n\n.comment {\n  padding: 12px;\n  border-radius: var(--radius);\n  background: var(--surface-soft);\n}\n\n.empty-state {\n  padding: 18px;\n  color: var(--muted);\n  text-align: center;\n  border: 1px dashed var(--line);\n  border-radius: var(--radius);\n  background: color-mix(in srgb, var(--surface) 70%, transparent);\n}\n\n@media (max-width: 1100px) {\n  .dashboard-grid,\n  .item-grid {\n    grid-template-columns: repeat(2, minmax(0, 1fr));\n  }\n\n  .ai-layout {\n    grid-template-columns: 1fr;\n  }\n}\n\n@media (max-width: 820px) {\n  .auth-grid {\n    grid-template-columns: 1fr;\n  }\n\n  .app-shell {\n    grid-template-columns: 1fr;\n  }\n\n  .sidebar {\n    position: static;\n    height: auto;\n  }\n\n  .nav-list {\n    grid-template-columns: repeat(2, minmax(0, 1fr));\n  }\n\n  .topbar,\n  .section-tools,\n  .reply-form,\n  .chat-row {\n    align-items: stretch;\n    flex-direction: column;\n  }\n\n  .top-actions {\n    justify-content: flex-start;\n  }\n\n  .dashboard-grid,\n  .item-grid,\n  .form-grid {\n    grid-template-columns: 1fr;\n  }\n\n  .list-mode .item-card {\n    grid-template-columns: 1fr;\n  }\n}\n\n  </style>\n</head>\n<body>\n  <div id="toast" aria-live="polite"></div>\n\n  <section id="auth-view" class="auth-shell">\n      <div class="auth-brand">\n      <div class="brand-mark">GW</div>\n      <div>\n        <h1>GenWise AI/ML Classroom</h1>\n        <p>A focused classroom space for AI/ML resources, research questions, student work, and teacher feedback.</p>\n      </div>\n    </div>\n\n    <div class="auth-grid">\n      <form id="login-form" class="panel auth-card">\n        <div class="panel-heading">\n          <h2>Sign In</h2>\n          <span>Classroom account</span>\n        </div>\n        <label>Email\n          <input name="email" type="email" autocomplete="email" required>\n        </label>\n        <label>Password\n          <input name="password" type="password" autocomplete="current-password" required>\n        </label>\n        <button class="primary" type="submit">Sign in</button>\n        <p class="hint">No account yet? <button id="jump-to-signup" class="link-button" type="button">Sign up</button></p>\n        <p class="hint">New users can sign up, then wait for teacher approval.</p>\n      </form>\n\n      <form id="register-form" class="panel auth-card">\n        <div class="panel-heading">\n          <h2>Sign Up</h2>\n          <span>Teacher approval required</span>\n        </div>\n        <p class="hint">Use your own email address and choose your own password. Teachers approve accounts, but they cannot see passwords.</p>\n        <label>Name\n          <input name="name" type="text" autocomplete="name" required>\n        </label>\n        <label>Email\n          <input name="email" type="email" autocomplete="email" required>\n        </label>\n        <label>Password\n          <input name="password" type="password" autocomplete="new-password" minlength="8" required>\n        </label>\n        <fieldset class="role-picker">\n          <legend>Register as</legend>\n          <label>\n            <input name="role" value="student" type="radio" checked>\n            <span>Student</span>\n          </label>\n          <label>\n            <input name="role" value="teacher" type="radio">\n            <span>Teacher</span>\n          </label>\n        </fieldset>\n        <button type="submit">Sign up</button>\n      </form>\n    </div>\n  </section>\n\n  <div id="app-view" class="app-shell hidden">\n    <aside class="sidebar">\n      <div class="brand-block">\n        <div class="brand-mark">GW</div>\n        <div>\n          <strong>GenWise</strong>\n          <span>AI/ML Classroom</span>\n        </div>\n      </div>\n\n      <nav class="nav-list">\n        <button class="nav-button active" data-section="dashboard">Dashboard</button>\n        <button class="nav-button" data-section="resources">Resources</button>\n        <button class="nav-button" data-section="inbox">Inbox</button>\n        <button class="nav-button" data-section="submissions">Submissions</button>\n        <button class="nav-button teacher-only" data-section="teacher-room">Teacher Room</button>\n        <button class="nav-button teacher-only" data-section="people">People</button>\n        <button class="nav-button" data-section="ai">AI Assistant</button>\n        <button class="nav-button" data-section="saved">Saved</button>\n      </nav>\n\n      <button id="theme-toggle" class="soft-button" type="button">Toggle theme</button>\n    </aside>\n\n    <main class="main">\n      <header class="topbar">\n        <div>\n          <p class="eyebrow">Classroom Portal</p>\n          <h1 id="section-title">Dashboard</h1>\n        </div>\n        <div class="top-actions">\n          <button id="top-signup-button" class="soft-button" type="button">Sign up</button>\n          <button id="account-button" class="soft-button" type="button">Account</button>\n          <button id="notification-button" class="soft-button" type="button">Notifications <span id="notification-count">0</span></button>\n          <span id="user-pill" class="user-pill"></span>\n          <button id="logout-button" type="button">Sign out</button>\n        </div>\n      </header>\n\n      <section id="dashboard" class="view active-view">\n        <div id="dashboard-grid" class="dashboard-grid"></div>\n      </section>\n\n      <section id="resources" class="view">\n        <div class="section-tools">\n          <div class="search-box">\n            <input id="resource-search" type="search" placeholder="Search resources, tags, prompts, links, notes">\n            <button id="resource-search-button" type="button">Search</button>\n          </div>\n          <div class="segmented">\n            <button class="active" data-resource-view="cards" type="button">Cards</button>\n            <button data-resource-view="list" type="button">List</button>\n          </div>\n        </div>\n\n        <form id="resource-form" class="panel form-grid" enctype="multipart/form-data">\n          <div class="panel-heading full-span">\n            <h2>Add Resource</h2>\n            <span class="teacher-only">Published publicly by teachers</span>\n            <span class="student-only">Sent privately to teachers first</span>\n          </div>\n          <label>Title\n            <input name="title" type="text" required>\n          </label>\n          <label>Type\n            <select name="kind">\n              <option value="resource">Resource</option>\n              <option value="prompt">Prompt</option>\n              <option value="note">Class note</option>\n              <option value="fact">Fact</option>\n              <option value="link">Link</option>\n              <option value="interesting">Interesting info</option>\n            </select>\n          </label>\n          <label class="full-span">Description\n            <textarea name="description" rows="3"></textarea>\n          </label>\n          <label class="full-span">Text / Prompt / Notes\n            <textarea name="body" rows="4"></textarea>\n          </label>\n          <label>Link\n            <input name="url" type="url" placeholder="https://">\n          </label>\n          <label>Tags\n            <input name="tags" type="text" placeholder="Type your own tags">\n          </label>\n          <label>File\n            <input name="file" type="file">\n          </label>\n          <label class="check-line">\n            <input name="pinned" value="true" type="checkbox">\n            Pin resource\n          </label>\n          <button class="primary full-span" type="submit">Publish resource</button>\n        </form>\n\n        <div id="resource-reviews-panel" class="panel stacked">\n          <div class="panel-heading">\n            <h2 class="teacher-only">Student Resource Uploads</h2>\n            <h2 class="student-only">My Resource Uploads</h2>\n            <span class="teacher-only">Review before publishing</span>\n            <span class="student-only">Only you and teachers can see these</span>\n          </div>\n          <div id="resource-reviews-list" class="item-grid"></div>\n        </div>\n\n        <div id="resources-list" class="item-grid"></div>\n      </section>\n\n      <section id="inbox" class="view">\n        <form id="inbox-form" class="panel form-grid" enctype="multipart/form-data">\n          <div class="panel-heading full-span">\n            <h2>Post to Inbox</h2>\n            <span>Visible to everyone</span>\n          </div>\n          <label>Title\n            <input name="title" type="text" required>\n          </label>\n          <label>Link\n            <input name="url" type="url" placeholder="https://">\n          </label>\n          <label class="full-span">Message\n            <textarea name="body" rows="4"></textarea>\n          </label>\n          <label>Attachment\n            <input name="file" type="file">\n          </label>\n          <label class="check-line teacher-only">\n            <input name="pinned" value="true" type="checkbox">\n            Pin message\n          </label>\n          <button class="primary full-span" type="submit">Post message</button>\n        </form>\n        <div id="inbox-list" class="feed"></div>\n      </section>\n\n      <section id="submissions" class="view">\n        <form id="submission-form" class="panel form-grid student-only" enctype="multipart/form-data">\n          <div class="panel-heading full-span">\n            <h2>Upload Submission</h2>\n            <span>Private between you and teachers</span>\n          </div>\n          <label>Title\n            <input name="title" type="text" required>\n          </label>\n          <label>Link\n            <input name="url" type="url" placeholder="https://">\n          </label>\n          <label class="full-span">Description\n            <textarea name="description" rows="3"></textarea>\n          </label>\n          <label class="full-span">Text Entry\n            <textarea name="text_content" rows="5"></textarea>\n          </label>\n          <label>File\n            <input name="file" type="file">\n          </label>\n          <button class="primary full-span" type="submit">Send to teachers</button>\n        </form>\n        <div id="submissions-list" class="item-grid"></div>\n      </section>\n\n      <section id="teacher-room" class="view teacher-only">\n        <form id="teacher-room-form" class="panel form-grid" enctype="multipart/form-data">\n          <div class="panel-heading full-span">\n            <h2>Teacher Room Item</h2>\n            <span>Only teachers can see this</span>\n          </div>\n          <label>Title\n            <input name="title" type="text" required>\n          </label>\n          <label>Type\n            <select name="kind">\n              <option value="note">Note</option>\n              <option value="file">File</option>\n              <option value="link">Link</option>\n              <option value="plan">Planning</option>\n            </select>\n          </label>\n          <label class="full-span">Description\n            <textarea name="description" rows="3"></textarea>\n          </label>\n          <label class="full-span">Private Notes\n            <textarea name="body" rows="4"></textarea>\n          </label>\n          <label>Link\n            <input name="url" type="url" placeholder="https://">\n          </label>\n          <label>Tags\n            <input name="tags" type="text">\n          </label>\n          <label>File\n            <input name="file" type="file">\n          </label>\n          <label class="check-line">\n            <input name="pinned" value="true" type="checkbox">\n            Pin item\n          </label>\n          <button class="primary full-span" type="submit">Save teacher item</button>\n        </form>\n        <div id="teacher-room-list" class="item-grid"></div>\n      </section>\n\n      <section id="people" class="view teacher-only">\n        <div class="panel">\n          <div class="panel-heading">\n            <h2>People</h2>\n            <span>Approve signups and manage accounts</span>\n          </div>\n          <div id="people-list" class="table-wrap"></div>\n        </div>\n      </section>\n\n      <section id="ai" class="view">\n        <div class="ai-layout">\n          <form id="ai-profile-form" class="panel stacked">\n            <div class="panel-heading">\n              <h2>AI Assistant Settings</h2>\n              <span>Private to you</span>\n            </div>\n            <label>Tone\n              <input name="tone" type="text">\n            </label>\n            <label>Helpfulness style\n              <textarea name="helpfulness" rows="4"></textarea>\n            </label>\n            <label>Research focus\n              <textarea name="focus" rows="4"></textarea>\n            </label>\n            <label>Custom instructions\n              <textarea name="custom_instructions" rows="5"></textarea>\n            </label>\n            <button type="submit">Save settings</button>\n          </form>\n\n          <div class="panel ai-chat">\n            <div class="panel-heading">\n              <h2>AI Assistant</h2>\n              <span>Research and questions only</span>\n            </div>\n            <div id="ai-messages" class="ai-messages"></div>\n            <form id="ai-chat-form" class="chat-row">\n              <textarea name="message" rows="2" placeholder="Ask a research question about AI/ML or class resources"></textarea>\n              <button class="primary" type="submit">Ask</button>\n            </form>\n          </div>\n        </div>\n      </section>\n\n      <section id="saved" class="view">\n        <div id="saved-list" class="item-grid"></div>\n      </section>\n    </main>\n  </div>\n\n  <dialog id="submission-dialog">\n    <div class="dialog-head">\n      <h2 id="submission-dialog-title">Submission</h2>\n      <button id="close-submission-dialog" type="button">Close</button>\n    </div>\n    <div id="submission-dialog-body"></div>\n  </dialog>\n\n  <dialog id="notifications-dialog">\n    <div class="dialog-head">\n      <h2>Notifications</h2>\n      <button id="close-notifications-dialog" type="button">Close</button>\n    </div>\n    <div id="notifications-list"></div>\n  </dialog>\n\n  <dialog id="signup-dialog">\n    <div class="dialog-head">\n      <h2>Sign Up</h2>\n      <button id="close-signup-dialog" type="button">Close</button>\n    </div>\n    <form id="top-signup-form" class="stacked">\n      <p class="hint">Use the person\'s own email and let them choose their own password. New accounts wait for teacher approval before entering the classroom.</p>\n      <label>Name\n        <input name="name" type="text" autocomplete="name" required>\n      </label>\n      <label>Email\n        <input name="email" type="email" autocomplete="email" required>\n      </label>\n      <label>Password\n        <input name="password" type="password" autocomplete="new-password" minlength="8" required>\n      </label>\n      <fieldset class="role-picker">\n        <legend>Register as</legend>\n        <label>\n          <input name="role" value="student" type="radio" checked>\n          <span>Student</span>\n        </label>\n        <label>\n          <input name="role" value="teacher" type="radio">\n          <span>Teacher</span>\n        </label>\n      </fieldset>\n      <button class="primary" type="submit">Sign up</button>\n    </form>\n  </dialog>\n\n  <dialog id="account-dialog">\n    <div class="dialog-head">\n      <h2>Account</h2>\n      <button id="close-account-dialog" type="button">Close</button>\n    </div>\n    <div class="stacked">\n      <div>\n        <h3 id="account-name"></h3>\n        <p id="account-email" class="hint"></p>\n      </div>\n      <form id="password-form" class="stacked">\n        <label>Current password\n          <input name="current_password" type="password" autocomplete="current-password" required>\n        </label>\n        <label>New password\n          <input name="new_password" type="password" autocomplete="new-password" minlength="8" required>\n        </label>\n        <button class="primary" type="submit">Change password</button>\n      </form>\n    </div>\n  </dialog>\n\n  <script>\nconst state = {\n  user: null,\n  section: "dashboard",\n  resourceView: localStorage.getItem("genwise-resource-view") || "cards",\n  submissions: [],\n};\n\nconst titles = {\n  dashboard: "Dashboard",\n  resources: "Resources",\n  inbox: "Inbox",\n  submissions: "Submissions",\n  "teacher-room": "Teacher Room",\n  people: "People",\n  ai: "AI Assistant",\n  saved: "Saved",\n};\n\nconst $ = (selector, root = document) => root.querySelector(selector);\nconst $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));\n\nfunction toast(message, type = "ok") {\n  const wrap = $("#toast");\n  const note = document.createElement("div");\n  note.className = `toast ${type === "error" ? "error" : ""}`;\n  note.textContent = message;\n  wrap.appendChild(note);\n  setTimeout(() => note.remove(), 4200);\n}\n\nasync function api(path, options = {}) {\n  const response = await fetch(path, {\n    credentials: "same-origin",\n    ...options,\n    headers: options.body instanceof FormData\n      ? options.headers || {}\n      : { "Content-Type": "application/json", ...(options.headers || {}) },\n  });\n  const data = await response.json().catch(() => ({}));\n  if (!response.ok) {\n    throw new Error(data.error || "Something went wrong.");\n  }\n  return data;\n}\n\nfunction escapeHtml(value) {\n  return String(value ?? "")\n    .replaceAll("&", "&amp;")\n    .replaceAll("<", "&lt;")\n    .replaceAll(">", "&gt;")\n    .replaceAll(\'"\', "&quot;")\n    .replaceAll("\'", "&#039;");\n}\n\nfunction compactDate(value) {\n  if (!value) return "";\n  const date = new Date(value);\n  if (Number.isNaN(date.getTime())) return "";\n  return date.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });\n}\n\nfunction fileSize(bytes) {\n  if (!bytes) return "";\n  const units = ["B", "KB", "MB", "GB"];\n  let size = Number(bytes);\n  let unit = 0;\n  while (size >= 1024 && unit < units.length - 1) {\n    size /= 1024;\n    unit += 1;\n  }\n  return `${size.toFixed(unit ? 1 : 0)} ${units[unit]}`;\n}\n\nfunction tagsHtml(tags) {\n  const values = String(tags || "")\n    .split(",")\n    .map((tag) => tag.trim())\n    .filter(Boolean);\n  if (!values.length) return "";\n  return `<div class="badge-row">${values.map((tag) => `<span class="badge">${escapeHtml(tag)}</span>`).join("")}</div>`;\n}\n\nfunction itemLinks(item) {\n  const links = [];\n  if (item.url) {\n    links.push(`<a href="${escapeHtml(item.url)}" target="_blank" rel="noreferrer">Open link</a>`);\n  }\n  if (item.preview_url) {\n    links.push(`<a href="${escapeHtml(item.preview_url)}" target="_blank" rel="noreferrer">Preview file</a>`);\n  }\n  if (item.download_url) {\n    const label = item.original_filename ? `Download ${escapeHtml(item.original_filename)}` : "Download file";\n    links.push(`<a href="${escapeHtml(item.download_url)}">${label}</a>`);\n  }\n  return links.length ? `<div class="action-row">${links.join("")}</div>` : "";\n}\n\nfunction applyRoleVisibility() {\n  const isTeacher = state.user?.role === "teacher";\n  $$(".teacher-only").forEach((el) => el.classList.toggle("hidden", !isTeacher));\n  $$(".student-only").forEach((el) => el.classList.toggle("hidden", isTeacher));\n}\n\nfunction setSignedIn(user) {\n  state.user = user;\n  $("#auth-view").classList.add("hidden");\n  $("#app-view").classList.remove("hidden");\n  $("#user-pill").textContent = `${user.name} · ${user.role}`;\n  applyRoleVisibility();\n}\n\nfunction setSignedOut() {\n  state.user = null;\n  $("#auth-view").classList.remove("hidden");\n  $("#app-view").classList.add("hidden");\n}\n\nfunction setSection(section) {\n  if (!titles[section]) return;\n  state.section = section;\n  $$(".nav-button").forEach((button) => button.classList.toggle("active", button.dataset.section === section));\n  $$(".view").forEach((view) => view.classList.toggle("active-view", view.id === section));\n  $("#section-title").textContent = titles[section];\n  loadSection(section);\n}\n\nfunction emptyState(text) {\n  return `<div class="empty-state">${escapeHtml(text)}</div>`;\n}\n\nfunction resourceCard(item) {\n  const pinned = item.pinned ? `<span class="badge pinned">Pinned</span>` : "";\n  const saveButton = item.saved\n    ? `<button data-unsave="${item.id}" type="button">Saved</button>`\n    : `<button data-save="${item.id}" type="button">Save</button>`;\n  const teacherTools = state.user.role === "teacher"\n    ? `<button data-pin-resource="${item.id}" data-pinned="${item.pinned ? "1" : "0"}" type="button">${item.pinned ? "Unpin" : "Pin"}</button>\n       <button class="danger" data-delete-resource="${item.id}" type="button">Delete</button>`\n    : "";\n  const summary = item.description || item.body || item.url || "No description yet.";\n  return `\n    <article class="panel item-card">\n      <div>\n        <div class="item-title-row">\n          <h3>${escapeHtml(item.title)}</h3>\n          ${pinned}\n        </div>\n        <div class="item-meta">${escapeHtml(item.kind)} · ${escapeHtml(item.uploader_name || "Teacher")} · ${compactDate(item.created_at)}</div>\n      </div>\n      <div class="item-body">${escapeHtml(summary).replaceAll("\\n", "<br>")}</div>\n      ${tagsHtml(item.tags)}\n      ${itemLinks(item)}\n      <div class="action-row">${saveButton}${teacherTools}</div>\n    </article>\n  `;\n}\n\nfunction renderResources(items, target = $("#resources-list")) {\n  target.classList.toggle("list-mode", state.resourceView === "list");\n  target.innerHTML = items.length ? items.map(resourceCard).join("") : emptyState("No resources yet.");\n}\n\nfunction resourceReviewCard(item) {\n  const statusBadge = `<span class="badge ${item.status === "pending" ? "pinned" : ""}">${escapeHtml(item.status)}</span>`;\n  const summary = item.description || item.body || item.url || "No details added.";\n  const teacherActions = state.user.role === "teacher" && item.status !== "deleted"\n    ? `\n      <label class="full-span">Teacher comment\n        <textarea data-review-comment="${item.id}" rows="2" placeholder="Optional comment for the student">${escapeHtml(item.teacher_comment || "")}</textarea>\n      </label>\n      <div class="action-row">\n        <button data-review-action="${item.id}" data-action="publish" type="button">Publish publicly</button>\n        <button data-review-action="${item.id}" data-action="private" type="button">Keep private</button>\n        <button data-review-action="${item.id}" data-action="comment" type="button">Save comment</button>\n        <button class="danger" data-review-action="${item.id}" data-action="delete" type="button">Delete</button>\n      </div>\n    `\n    : "";\n  return `\n    <article class="panel item-card">\n      <div class="item-title-row">\n        <div>\n          <h3>${escapeHtml(item.title)}</h3>\n          <div class="item-meta">${escapeHtml(item.student_name || "Student")} · ${escapeHtml(item.kind)} · ${compactDate(item.created_at)}</div>\n        </div>\n        ${statusBadge}\n      </div>\n      <div class="item-body">${escapeHtml(summary).replaceAll("\\n", "<br>")}</div>\n      ${item.teacher_comment ? `<div class="reply"><strong>Teacher comment</strong><p>${escapeHtml(item.teacher_comment)}</p></div>` : ""}\n      ${tagsHtml(item.tags)}\n      ${itemLinks(item)}\n      ${teacherActions}\n    </article>\n  `;\n}\n\nasync function loadResourceReviews() {\n  const panel = $("#resource-reviews-panel");\n  if (!panel) return;\n  const data = await api("/api/resource-reviews");\n  const reviews = data.reviews || [];\n  panel.classList.toggle("hidden", reviews.length === 0);\n  $("#resource-reviews-list").innerHTML = reviews.length ? reviews.map(resourceReviewCard).join("") : emptyState("No student resource uploads yet.");\n}\n\nasync function loadResources(savedOnly = false) {\n  const q = savedOnly ? "" : $("#resource-search")?.value || "";\n  const params = new URLSearchParams();\n  if (q) params.set("q", q);\n  if (savedOnly) params.set("saved", "1");\n  const data = await api(`/api/resources?${params}`);\n  renderResources(data.resources || [], savedOnly ? $("#saved-list") : $("#resources-list"));\n  if (!savedOnly) await loadResourceReviews();\n}\n\nfunction dashboardList(items, renderer, empty) {\n  if (!items?.length) return emptyState(empty);\n  return items.map(renderer).join("");\n}\n\nfunction tinyResource(item) {\n  return `\n    <div class="metric-row">\n      <div>\n        <strong style="font-size:15px;color:var(--ink)">${escapeHtml(item.title)}</strong>\n        <div class="item-meta">${escapeHtml(item.kind || "resource")} · ${compactDate(item.created_at)}</div>\n      </div>\n      ${item.download_url ? `<a href="${escapeHtml(item.download_url)}">Download</a>` : ""}\n    </div>\n  `;\n}\n\nfunction tinyInbox(item) {\n  return `\n    <div class="metric-row">\n      <div>\n        <strong style="font-size:15px;color:var(--ink)">${escapeHtml(item.title)}</strong>\n        <div class="item-meta">${escapeHtml(item.author_name)} · ${compactDate(item.created_at)}</div>\n      </div>\n    </div>\n  `;\n}\n\nfunction renderDashboard(data) {\n  const grid = $("#dashboard-grid");\n  const sharedCards = `\n    <article class="panel dashboard-card">\n      <h2>Recent Resources</h2>\n      ${dashboardList(data.recent_resources, tinyResource, "No public resources yet.")}\n    </article>\n    <article class="panel dashboard-card">\n      <h2>Inbox Updates</h2>\n      ${dashboardList(data.recent_inbox, tinyInbox, "No inbox messages yet.")}\n    </article>\n    <article class="panel dashboard-card">\n      <h2>Saved Resources</h2>\n      ${dashboardList(data.saved_resources, tinyResource, "Saved items will appear here.")}\n    </article>\n  `;\n\n  if (state.user.role === "teacher") {\n    const pending = data.pending_users || [];\n    const submissions = data.recent_submissions || [];\n    const activity = data.student_activity || [];\n    const resourceReviews = data.resource_reviews || [];\n    grid.innerHTML = `\n      <article class="panel dashboard-card">\n        <h2>Account Requests</h2>\n        <div class="metric-row"><span>Waiting</span><strong>${pending.length}</strong></div>\n        ${pending.slice(0, 4).map((user) => `<div class="item-meta">${escapeHtml(user.name)} · ${escapeHtml(user.role)}</div>`).join("") || `<p class="hint">No pending accounts.</p>`}\n      </article>\n      <article class="panel dashboard-card">\n        <h2>Recent Submissions</h2>\n        ${dashboardList(submissions, (item) => `\n          <button data-open-submission="${item.id}" type="button" style="text-align:left">\n            ${escapeHtml(item.title)}<br><span class="item-meta">${escapeHtml(item.student_name)} · ${item.comment_count} comments</span>\n          </button>\n        `, "No student submissions yet.")}\n      </article>\n      <article class="panel dashboard-card">\n        <h2>Student Activity</h2>\n        ${dashboardList(activity, (student) => `\n          <div class="metric-row">\n            <span>${escapeHtml(student.name)}</span>\n            <strong>${student.submissions}</strong>\n          </div>\n        `, "No active students yet.")}\n      </article>\n      <article class="panel dashboard-card">\n        <h2>Student Resource Uploads</h2>\n        <div class="metric-row"><span>Pending review</span><strong>${resourceReviews.length}</strong></div>\n        ${dashboardList(resourceReviews, (item) => `\n          <button data-jump="resources" type="button" style="text-align:left">\n            ${escapeHtml(item.title)}<br><span class="item-meta">${escapeHtml(item.student_name)} · ${compactDate(item.created_at)}</span>\n          </button>\n        `, "No student resource uploads waiting.")}\n      </article>\n      ${sharedCards}\n    `;\n  } else {\n    const myResourceReviews = data.my_resource_reviews || [];\n    grid.innerHTML = `\n      <article class="panel dashboard-card">\n        <h2>Latest Teacher Comments</h2>\n        ${dashboardList(data.latest_teacher_comments, (comment) => `\n          <div class="reply">\n            <div class="item-meta">${escapeHtml(comment.submission_title)} · ${escapeHtml(comment.teacher_name)}</div>\n            <p>${escapeHtml(comment.body)}</p>\n          </div>\n        `, "Teacher feedback will appear here.")}\n      </article>\n      <article class="panel dashboard-card">\n        <h2>My Submissions</h2>\n        ${dashboardList(data.my_submissions, (item) => `\n          <button data-open-submission="${item.id}" type="button" style="text-align:left">\n            ${escapeHtml(item.title)}<br><span class="item-meta">${item.comment_count} teacher comments</span>\n          </button>\n        `, "Your private submissions will appear here.")}\n      </article>\n      <article class="panel dashboard-card">\n        <h2>AI Assistant</h2>\n        <p class="item-body">Ask research questions and search classroom resources without drafting classwork for you.</p>\n        <button type="button" data-jump="ai">Open assistant</button>\n      </article>\n      <article class="panel dashboard-card">\n        <h2>My Resource Uploads</h2>\n        ${dashboardList(myResourceReviews, (item) => `\n          <div class="metric-row">\n            <span>${escapeHtml(item.title)}</span>\n            <strong style="font-size:13px">${escapeHtml(item.status)}</strong>\n          </div>\n        `, "Your resource uploads will appear here.")}\n      </article>\n      ${sharedCards}\n    `;\n  }\n  $("#notification-count").textContent = data.unread_notifications || 0;\n}\n\nasync function loadDashboard() {\n  const data = await api("/api/dashboard");\n  renderDashboard(data);\n}\n\nfunction inboxPost(post) {\n  const teacherTools = state.user.role === "teacher"\n    ? `<button data-pin-inbox="${post.id}" data-pinned="${post.pinned ? "1" : "0"}" type="button">${post.pinned ? "Unpin" : "Pin"}</button>\n       <button class="danger" data-delete-inbox="${post.id}" type="button">Delete</button>`\n    : post.author_id === state.user.id\n      ? `<button class="danger" data-delete-inbox="${post.id}" type="button">Delete</button>`\n      : "";\n  return `\n    <article class="panel feed-post">\n      <div class="item-title-row">\n        <div>\n          <h3>${escapeHtml(post.title)}</h3>\n          <div class="item-meta">${escapeHtml(post.author_name)} · ${escapeHtml(post.author_role)} · ${compactDate(post.created_at)}</div>\n        </div>\n        ${post.pinned ? `<span class="badge pinned">Pinned</span>` : ""}\n      </div>\n      <div class="item-body">${escapeHtml(post.body || "").replaceAll("\\n", "<br>")}</div>\n      ${itemLinks(post)}\n      <div class="reply-list">\n        ${(post.replies || []).map((reply) => `\n          <div class="reply">\n            <div class="item-meta">${escapeHtml(reply.author_name)} · ${compactDate(reply.created_at)}</div>\n            <p>${escapeHtml(reply.body)}</p>\n          </div>\n        `).join("")}\n      </div>\n      <form class="reply-form" data-inbox-reply="${post.id}">\n        <textarea name="body" rows="2" placeholder="Reply to this inbox post"></textarea>\n        <button type="submit">Reply</button>\n      </form>\n      <div class="action-row">${teacherTools}</div>\n    </article>\n  `;\n}\n\nasync function loadInbox() {\n  const data = await api("/api/inbox");\n  $("#inbox-list").innerHTML = data.posts?.length ? data.posts.map(inboxPost).join("") : emptyState("No inbox posts yet.");\n}\n\nfunction submissionCard(item) {\n  const detail = item.description || item.text_content || item.url || "No details added.";\n  return `\n    <article class="panel item-card">\n      <div>\n        <h3>${escapeHtml(item.title)}</h3>\n        <div class="item-meta">${escapeHtml(item.student_name || state.user.name)} · ${compactDate(item.created_at)} · ${item.comment_count || 0} teacher comments</div>\n      </div>\n      <div class="item-body">${escapeHtml(detail).replaceAll("\\n", "<br>")}</div>\n      ${itemLinks(item)}\n      <div class="action-row">\n        <button data-open-submission="${item.id}" type="button">Open comments</button>\n      </div>\n    </article>\n  `;\n}\n\nasync function loadSubmissions() {\n  const data = await api("/api/submissions");\n  state.submissions = data.submissions || [];\n  $("#submissions-list").innerHTML = state.submissions.length\n    ? state.submissions.map(submissionCard).join("")\n    : emptyState(state.user.role === "teacher" ? "No student submissions yet." : "You have not sent any private submissions yet.");\n}\n\nasync function openSubmission(id) {\n  if (!state.submissions.length) {\n    await loadSubmissions();\n  }\n  const item = state.submissions.find((submission) => Number(submission.id) === Number(id));\n  if (!item) {\n    toast("Submission not found in the current list.", "error");\n    return;\n  }\n  const data = await api(`/api/submissions/${id}/comments`);\n  $("#submission-dialog-title").textContent = item.title;\n  $("#submission-dialog-body").innerHTML = `\n    <div class="item-meta">${escapeHtml(item.student_name || state.user.name)} · ${compactDate(item.created_at)}</div>\n    <p class="item-body">${escapeHtml(item.description || "").replaceAll("\\n", "<br>")}</p>\n    ${item.text_content ? `<div class="reply"><strong>Text entry</strong><p>${escapeHtml(item.text_content).replaceAll("\\n", "<br>")}</p></div>` : ""}\n    ${itemLinks(item)}\n    <div class="comment-thread">\n      <h3>Teacher Comments</h3>\n      ${(data.comments || []).length ? data.comments.map((comment) => `\n        <div class="comment">\n          <div class="item-meta">${escapeHtml(comment.teacher_name)} · ${compactDate(comment.created_at)}</div>\n          <p>${escapeHtml(comment.body)}</p>\n        </div>\n      `).join("") : emptyState("No teacher comments yet.")}\n    </div>\n    ${state.user.role === "teacher" ? `\n      <form id="teacher-comment-form" class="stacked" data-submission="${item.id}">\n        <label>New teacher comment\n          <textarea name="body" rows="4" required></textarea>\n        </label>\n        <button class="primary" type="submit">Add comment</button>\n      </form>\n    ` : ""}\n  `;\n  $("#submission-dialog").showModal();\n}\n\nfunction teacherRoomCard(item) {\n  return `\n    <article class="panel item-card">\n      <div class="item-title-row">\n        <div>\n          <h3>${escapeHtml(item.title)}</h3>\n          <div class="item-meta">${escapeHtml(item.kind)} · ${escapeHtml(item.uploader_name)} · ${compactDate(item.created_at)}</div>\n        </div>\n        ${item.pinned ? `<span class="badge pinned">Pinned</span>` : ""}\n      </div>\n      <div class="item-body">${escapeHtml(item.description || item.body || item.url || "").replaceAll("\\n", "<br>")}</div>\n      ${tagsHtml(item.tags)}\n      ${itemLinks(item)}\n      <div class="action-row">\n        <button data-pin-teacher-item="${item.id}" data-pinned="${item.pinned ? "1" : "0"}" type="button">${item.pinned ? "Unpin" : "Pin"}</button>\n        <button class="danger" data-delete-teacher-item="${item.id}" type="button">Delete</button>\n      </div>\n    </article>\n  `;\n}\n\nasync function loadTeacherRoom() {\n  const data = await api("/api/teacher-room");\n  $("#teacher-room-list").innerHTML = data.items?.length ? data.items.map(teacherRoomCard).join("") : emptyState("No teacher-only items yet.");\n}\n\nasync function loadPeople() {\n  const data = await api("/api/users");\n  const rows = data.users.map((user) => `\n    <tr>\n      <td><strong>${escapeHtml(user.name)}</strong><br><span class="item-meta">${escapeHtml(user.email)}</span></td>\n      <td>${escapeHtml(user.role)}</td>\n      <td>${user.approved ? "Approved" : "Waiting"}</td>\n      <td>${user.disabled ? "Disabled" : "Active"}</td>\n      <td>${compactDate(user.created_at)}</td>\n      <td>\n        <div class="action-row">\n          ${user.approved ? "" : `<button data-approve-user="${user.id}" type="button">Approve</button>`}\n          <button data-role-user="${user.id}" data-role="${user.role}" type="button">Make ${user.role === "teacher" ? "student" : "teacher"}</button>\n          <button data-disable-user="${user.id}" data-disabled="${user.disabled ? "1" : "0"}" type="button">${user.disabled ? "Enable" : "Disable"}</button>\n        </div>\n      </td>\n    </tr>\n  `).join("");\n  $("#people-list").innerHTML = `\n    <table>\n      <thead><tr><th>User</th><th>Role</th><th>Approval</th><th>Status</th><th>Created</th><th>Actions</th></tr></thead>\n      <tbody>${rows}</tbody>\n    </table>\n  `;\n}\n\nfunction renderAiMessages(messages) {\n  $("#ai-messages").innerHTML = messages.length ? messages.map((message) => {\n    let citations = [];\n    try {\n      citations = JSON.parse(message.citations_json || "[]");\n    } catch {\n      citations = [];\n    }\n    const cites = citations.length\n      ? `<div class="ai-citations">Sources used: ${citations.map((item) => escapeHtml(item.title)).join(", ")}</div>`\n      : "";\n    return `<div class="ai-bubble ${message.role}">${escapeHtml(message.content)}${cites}</div>`;\n  }).join("") : emptyState("Ask a research question to begin.");\n  $("#ai-messages").scrollTop = $("#ai-messages").scrollHeight;\n}\n\nasync function loadAi() {\n  const [profile, history] = await Promise.all([\n    api("/api/ai/profile"),\n    api("/api/ai/history"),\n  ]);\n  const form = $("#ai-profile-form");\n  form.tone.value = profile.profile.tone || "";\n  form.helpfulness.value = profile.profile.helpfulness || "";\n  form.focus.value = profile.profile.focus || "";\n  form.custom_instructions.value = profile.profile.custom_instructions || "";\n  renderAiMessages(history.messages || []);\n}\n\nasync function loadNotifications() {\n  const data = await api("/api/notifications");\n  $("#notifications-list").innerHTML = data.notifications?.length\n    ? data.notifications.map((note) => `\n      <div class="reply">\n        <div class="item-meta">${note.read_at ? "Read" : "Unread"} · ${compactDate(note.created_at)}</div>\n        <p>${escapeHtml(note.message)}</p>\n      </div>\n    `).join("")\n    : emptyState("No notifications yet.");\n}\n\nasync function loadSection(section) {\n  try {\n    if (section === "dashboard") await loadDashboard();\n    if (section === "resources") await loadResources();\n    if (section === "inbox") await loadInbox();\n    if (section === "submissions") await loadSubmissions();\n    if (section === "teacher-room") await loadTeacherRoom();\n    if (section === "people") await loadPeople();\n    if (section === "ai") await loadAi();\n    if (section === "saved") await loadResources(true);\n  } catch (error) {\n    toast(error.message, "error");\n  }\n}\n\nfunction formToJson(form) {\n  return Object.fromEntries(new FormData(form).entries());\n}\n\nfunction resetForm(form) {\n  form.reset();\n}\n\nasync function submitMultipart(form, path, success) {\n  const button = $("button[type=\'submit\']", form);\n  button.disabled = true;\n  try {\n    await api(path, { method: "POST", body: new FormData(form) });\n    toast(success);\n    resetForm(form);\n    await loadSection(state.section);\n  } catch (error) {\n    toast(error.message, "error");\n  } finally {\n    button.disabled = false;\n  }\n}\n\nasync function init() {\n  if (localStorage.getItem("genwise-theme") === "dark") {\n    document.body.classList.add("dark");\n  }\n  $$(".segmented button").forEach((button) => {\n    button.classList.toggle("active", button.dataset.resourceView === state.resourceView);\n  });\n\n  $("#login-form").addEventListener("submit", async (event) => {\n    event.preventDefault();\n    try {\n      const data = await api("/api/login", { method: "POST", body: JSON.stringify(formToJson(event.currentTarget)) });\n      setSignedIn(data.user);\n      setSection("dashboard");\n    } catch (error) {\n      toast(error.message, "error");\n    }\n  });\n\n  $("#register-form").addEventListener("submit", async (event) => {\n    event.preventDefault();\n    const form = event.currentTarget;\n    try {\n      const data = await api("/api/register", { method: "POST", body: JSON.stringify(formToJson(form)) });\n      toast(data.message || "Account requested.");\n      form.reset();\n    } catch (error) {\n      toast(error.message, "error");\n    }\n  });\n\n  $("#logout-button").addEventListener("click", async () => {\n    await api("/api/logout", { method: "POST", body: JSON.stringify({}) });\n    setSignedOut();\n  });\n\n  $("#theme-toggle").addEventListener("click", () => {\n    document.body.classList.toggle("dark");\n    localStorage.setItem("genwise-theme", document.body.classList.contains("dark") ? "dark" : "light");\n  });\n\n  $("#jump-to-signup").addEventListener("click", () => {\n    const nameInput = $("#register-form input[name=\\"name\\"]");\n    nameInput.scrollIntoView({ behavior: "smooth", block: "center" });\n    nameInput.focus();\n  });\n\n  $("#top-signup-button").addEventListener("click", () => {\n    $("#signup-dialog").showModal();\n    $("#top-signup-form input[name=\\"name\\"]").focus();\n  });\n\n  $("#close-signup-dialog").addEventListener("click", () => $("#signup-dialog").close());\n\n  $("#account-button").addEventListener("click", () => {\n    $("#account-name").textContent = state.user?.name || "Account";\n    $("#account-email").textContent = `${state.user?.email || ""} · ${state.user?.role || ""}`;\n    $("#account-dialog").showModal();\n  });\n\n  $("#close-account-dialog").addEventListener("click", () => $("#account-dialog").close());\n\n  $("#top-signup-form").addEventListener("submit", async (event) => {\n    event.preventDefault();\n    const form = event.currentTarget;\n    const button = $("button[type=\\"submit\\"]", form);\n    button.disabled = true;\n    try {\n      const data = await api("/api/register", { method: "POST", body: JSON.stringify(formToJson(form)) });\n      toast(data.message || "Account requested.");\n      form.reset();\n      $("#signup-dialog").close();\n      if (state.user?.role === "teacher" && state.section === "people") {\n        await loadPeople();\n      }\n      if (state.section === "dashboard") {\n        await loadDashboard();\n      }\n    } catch (error) {\n      toast(error.message, "error");\n    } finally {\n      button.disabled = false;\n    }\n  });\n\n  $("#password-form").addEventListener("submit", async (event) => {\n    event.preventDefault();\n    const form = event.currentTarget;\n    const data = formToJson(form);\n    const button = $("button[type=\\"submit\\"]", form);\n    button.disabled = true;\n    try {\n      const result = await api("/api/account/password", {\n        method: "POST",\n        body: JSON.stringify(data),\n      });\n      toast(result.message || "Password updated.");\n      form.reset();\n      $("#account-dialog").close();\n    } catch (error) {\n      toast(error.message, "error");\n    } finally {\n      button.disabled = false;\n    }\n  });\n\n  $$(".nav-button").forEach((button) => {\n    button.addEventListener("click", () => setSection(button.dataset.section));\n  });\n\n  $("#resource-form").addEventListener("submit", (event) => {\n    event.preventDefault();\n    submitMultipart(\n      event.currentTarget,\n      "/api/resources",\n      state.user?.role === "teacher" ? "Resource published." : "Resource sent to teachers for review."\n    );\n  });\n\n  $("#resource-search-button").addEventListener("click", () => loadResources());\n  $("#resource-search").addEventListener("keydown", (event) => {\n    if (event.key === "Enter") {\n      event.preventDefault();\n      loadResources();\n    }\n  });\n\n  $$(".segmented button").forEach((button) => {\n    button.addEventListener("click", () => {\n      state.resourceView = button.dataset.resourceView;\n      localStorage.setItem("genwise-resource-view", state.resourceView);\n      $$(".segmented button").forEach((item) => item.classList.toggle("active", item === button));\n      loadSection(state.section);\n    });\n  });\n\n  $("#inbox-form").addEventListener("submit", (event) => {\n    event.preventDefault();\n    submitMultipart(event.currentTarget, "/api/inbox", "Inbox message posted.");\n  });\n\n  $("#submission-form").addEventListener("submit", (event) => {\n    event.preventDefault();\n    submitMultipart(event.currentTarget, "/api/submissions", "Submission sent to teachers.");\n  });\n\n  $("#teacher-room-form").addEventListener("submit", (event) => {\n    event.preventDefault();\n    submitMultipart(event.currentTarget, "/api/teacher-room", "Teacher room item saved.");\n  });\n\n  $("#ai-profile-form").addEventListener("submit", async (event) => {\n    event.preventDefault();\n    try {\n      await api("/api/ai/profile", { method: "POST", body: JSON.stringify(formToJson(event.currentTarget)) });\n      toast("AI Assistant settings saved.");\n    } catch (error) {\n      toast(error.message, "error");\n    }\n  });\n\n  $("#ai-chat-form").addEventListener("submit", async (event) => {\n    event.preventDefault();\n    const form = event.currentTarget;\n    const message = form.message.value.trim();\n    if (!message) return;\n    form.message.value = "";\n    const existing = $$(".ai-bubble", $("#ai-messages")).map((node) => ({\n      role: node.classList.contains("user") ? "user" : "assistant",\n      content: node.textContent,\n      citations_json: "[]",\n    }));\n    renderAiMessages([...existing, { role: "user", content: message, citations_json: "[]" }]);\n    try {\n      await api("/api/ai/chat", { method: "POST", body: JSON.stringify({ message }) });\n      await loadAi();\n    } catch (error) {\n      toast(error.message, "error");\n    }\n  });\n\n  $("#notification-button").addEventListener("click", async () => {\n    await loadNotifications();\n    $("#notifications-dialog").showModal();\n    await api("/api/notifications", { method: "POST", body: JSON.stringify({}) });\n    $("#notification-count").textContent = "0";\n  });\n  $("#close-notifications-dialog").addEventListener("click", () => $("#notifications-dialog").close());\n  $("#close-submission-dialog").addEventListener("click", () => $("#submission-dialog").close());\n\n  document.addEventListener("submit", async (event) => {\n    const replyForm = event.target.closest("[data-inbox-reply]");\n    if (replyForm) {\n      event.preventDefault();\n      const body = replyForm.body.value.trim();\n      if (!body) return;\n      try {\n        await api(`/api/inbox/${replyForm.dataset.inboxReply}/reply`, {\n          method: "POST",\n          body: JSON.stringify({ body }),\n        });\n        await loadInbox();\n      } catch (error) {\n        toast(error.message, "error");\n      }\n      return;\n    }\n\n    const commentForm = event.target.closest("#teacher-comment-form");\n    if (commentForm) {\n      event.preventDefault();\n      const body = commentForm.body.value.trim();\n      if (!body) return;\n      try {\n        await api(`/api/submissions/${commentForm.dataset.submission}/comments`, {\n          method: "POST",\n          body: JSON.stringify({ body }),\n        });\n        toast("Teacher comment added.");\n        $("#submission-dialog").close();\n        await loadSubmissions();\n        await openSubmission(commentForm.dataset.submission);\n      } catch (error) {\n        toast(error.message, "error");\n      }\n    }\n  });\n\n  document.addEventListener("click", async (event) => {\n    const button = event.target.closest("button");\n    if (!button) return;\n\n    try {\n      if (button.dataset.jump) setSection(button.dataset.jump);\n      if (button.dataset.openSubmission) await openSubmission(button.dataset.openSubmission);\n      if (button.dataset.save) {\n        await api(`/api/resources/${button.dataset.save}/save`, { method: "POST", body: JSON.stringify({}) });\n        await loadSection(state.section);\n      }\n      if (button.dataset.unsave) {\n        await api(`/api/resources/${button.dataset.unsave}/save`, { method: "DELETE" });\n        await loadSection(state.section);\n      }\n      if (button.dataset.deleteResource) {\n        if (!confirm("Delete this resource for everyone?")) return;\n        await api(`/api/resources/${button.dataset.deleteResource}`, { method: "DELETE" });\n        await loadSection(state.section);\n      }\n      if (button.dataset.pinResource) {\n        await api(`/api/resources/${button.dataset.pinResource}`, {\n          method: "PATCH",\n          body: JSON.stringify({ pinned: button.dataset.pinned !== "1" }),\n        });\n        await loadSection(state.section);\n      }\n      if (button.dataset.reviewAction) {\n        const reviewId = button.dataset.reviewAction;\n        const action = button.dataset.action;\n        if (action === "delete" && !confirm("Delete this student resource upload?")) return;\n        if (action === "publish" && !confirm("Publish this student upload for the whole class?")) return;\n        const comment = $(`[data-review-comment="${reviewId}"]`)?.value || "";\n        await api(`/api/resource-reviews/${reviewId}`, {\n          method: "PATCH",\n          body: JSON.stringify({ action, teacher_comment: comment }),\n        });\n        toast("Student resource upload updated.");\n        await loadSection(state.section);\n      }\n      if (button.dataset.deleteInbox) {\n        if (!confirm("Delete this inbox post?")) return;\n        await api(`/api/inbox/${button.dataset.deleteInbox}`, { method: "DELETE" });\n        await loadInbox();\n      }\n      if (button.dataset.pinInbox) {\n        await api(`/api/inbox/${button.dataset.pinInbox}`, {\n          method: "PATCH",\n          body: JSON.stringify({ pinned: button.dataset.pinned !== "1" }),\n        });\n        await loadInbox();\n      }\n      if (button.dataset.deleteTeacherItem) {\n        if (!confirm("Delete this teacher-room item?")) return;\n        await api(`/api/teacher-room/${button.dataset.deleteTeacherItem}`, { method: "DELETE" });\n        await loadTeacherRoom();\n      }\n      if (button.dataset.pinTeacherItem) {\n        await api(`/api/teacher-room/${button.dataset.pinTeacherItem}`, {\n          method: "PATCH",\n          body: JSON.stringify({ pinned: button.dataset.pinned !== "1" }),\n        });\n        await loadTeacherRoom();\n      }\n      if (button.dataset.approveUser) {\n        await api(`/api/users/${button.dataset.approveUser}`, {\n          method: "PATCH",\n          body: JSON.stringify({ approved: 1 }),\n        });\n        await loadPeople();\n        if (state.section === "dashboard") await loadDashboard();\n      }\n      if (button.dataset.disableUser) {\n        await api(`/api/users/${button.dataset.disableUser}`, {\n          method: "PATCH",\n          body: JSON.stringify({ disabled: button.dataset.disabled !== "1", approved: 1 }),\n        });\n        await loadPeople();\n      }\n      if (button.dataset.roleUser) {\n        await api(`/api/users/${button.dataset.roleUser}`, {\n          method: "PATCH",\n          body: JSON.stringify({ role: button.dataset.role === "teacher" ? "student" : "teacher", approved: 1 }),\n        });\n        await loadPeople();\n      }\n    } catch (error) {\n      toast(error.message, "error");\n    }\n  });\n\n  try {\n    const data = await api("/api/me");\n    if (data.user) {\n      setSignedIn(data.user);\n      setSection("dashboard");\n    } else {\n      setSignedOut();\n    }\n  } catch {\n    setSignedOut();\n  }\n}\n\ninit();\n\n  </script>\n</body>\n</html>\n'


@contextmanager
def get_db():
    ensure_dirs()
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    try:
        yield db
    finally:
        db.close()


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


def execute_db(sql: str, params: tuple = ()) -> int:
    with get_db() as db:
        cur = db.execute(sql, params)
        db.commit()
        return cur.lastrowid


def init_db() -> None:
    ensure_dirs()
    with get_db() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'student',
                approved INTEGER NOT NULL DEFAULT 0,
                disabled INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS ai_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE,
                tone TEXT NOT NULL DEFAULT 'friendly and clear',
                helpfulness TEXT NOT NULL DEFAULT 'explain ideas, ask useful follow-up questions, and avoid doing classwork for the student',
                focus TEXT NOT NULL DEFAULT 'AI and machine learning research questions',
                custom_instructions TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS resources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'resource',
                description TEXT NOT NULL DEFAULT '',
                body TEXT NOT NULL DEFAULT '',
                url TEXT NOT NULL DEFAULT '',
                tags TEXT NOT NULL DEFAULT '',
                original_filename TEXT NOT NULL DEFAULT '',
                stored_filename TEXT NOT NULL DEFAULT '',
                mime_type TEXT NOT NULL DEFAULT '',
                file_size INTEGER NOT NULL DEFAULT 0,
                uploaded_by INTEGER NOT NULL,
                pinned INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (uploaded_by) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS resource_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'resource',
                description TEXT NOT NULL DEFAULT '',
                body TEXT NOT NULL DEFAULT '',
                url TEXT NOT NULL DEFAULT '',
                tags TEXT NOT NULL DEFAULT '',
                original_filename TEXT NOT NULL DEFAULT '',
                stored_filename TEXT NOT NULL DEFAULT '',
                mime_type TEXT NOT NULL DEFAULT '',
                file_size INTEGER NOT NULL DEFAULT 0,
                student_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                teacher_comment TEXT NOT NULL DEFAULT '',
                reviewed_by INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (student_id) REFERENCES users(id),
                FOREIGN KEY (reviewed_by) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS teacher_room_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'note',
                description TEXT NOT NULL DEFAULT '',
                body TEXT NOT NULL DEFAULT '',
                url TEXT NOT NULL DEFAULT '',
                tags TEXT NOT NULL DEFAULT '',
                original_filename TEXT NOT NULL DEFAULT '',
                stored_filename TEXT NOT NULL DEFAULT '',
                mime_type TEXT NOT NULL DEFAULT '',
                file_size INTEGER NOT NULL DEFAULT 0,
                uploaded_by INTEGER NOT NULL,
                pinned INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (uploaded_by) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS saves (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                resource_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(user_id, resource_id),
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (resource_id) REFERENCES resources(id)
            );

            CREATE TABLE IF NOT EXISTS inbox_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                body TEXT NOT NULL DEFAULT '',
                url TEXT NOT NULL DEFAULT '',
                original_filename TEXT NOT NULL DEFAULT '',
                stored_filename TEXT NOT NULL DEFAULT '',
                mime_type TEXT NOT NULL DEFAULT '',
                file_size INTEGER NOT NULL DEFAULT 0,
                author_id INTEGER NOT NULL,
                pinned INTEGER NOT NULL DEFAULT 0,
                deleted_at TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (author_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS inbox_replies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id INTEGER NOT NULL,
                body TEXT NOT NULL,
                author_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (post_id) REFERENCES inbox_posts(id),
                FOREIGN KEY (author_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                text_content TEXT NOT NULL DEFAULT '',
                url TEXT NOT NULL DEFAULT '',
                original_filename TEXT NOT NULL DEFAULT '',
                stored_filename TEXT NOT NULL DEFAULT '',
                mime_type TEXT NOT NULL DEFAULT '',
                file_size INTEGER NOT NULL DEFAULT 0,
                student_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (student_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS submission_comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                submission_id INTEGER NOT NULL,
                teacher_id INTEGER NOT NULL,
                body TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (submission_id) REFERENCES submissions(id),
                FOREIGN KEY (teacher_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                message TEXT NOT NULL,
                link TEXT NOT NULL DEFAULT '',
                read_at TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS ai_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                citations_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
            """
        )
        db.commit()


def current_user() -> dict | None:
    user_id = session.get("user_id")
    if not user_id:
        return None
    with get_db() as db:
        row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    user = row_to_dict(row)
    if not user or user["disabled"] or not user["approved"]:
        session.clear()
        return None
    return user


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user():
            return jsonify({"error": "Please sign in first."}), 401
        return fn(*args, **kwargs)

    return wrapper


def teacher_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user:
            return jsonify({"error": "Please sign in first."}), 401
        if user["role"] != "teacher":
            return jsonify({"error": "Teacher access required."}), 403
        return fn(*args, **kwargs)

    return wrapper


def clean_text(value: str | None, limit: int = 8000) -> str:
    if not value:
        return ""
    return value.strip()[:limit]


def normalize_email(email: str) -> str:
    return clean_text(email, 240).lower()


def upload_limit_for(user: dict) -> int:
    return TEACHER_UPLOAD_LIMIT if user["role"] == "teacher" else STUDENT_UPLOAD_LIMIT


def save_upload(file, bucket: str, user: dict) -> dict:
    if not file or not file.filename:
        return {
            "original_filename": "",
            "stored_filename": "",
            "mime_type": "",
            "file_size": 0,
        }

    if request.content_length and request.content_length > upload_limit_for(user) + (1024 * 1024):
        abort(413, description="This upload is larger than the allowed limit for your role.")

    original = secure_filename(file.filename)
    ext = Path(original).suffix.lower()
    if ext in BLOCKED_EXTENSIONS:
        abort(400, description=f"{ext} files are blocked for classroom safety.")

    stored = f"{uuid.uuid4().hex}{ext}"
    bucket_dir = UPLOAD_DIR / bucket
    bucket_dir.mkdir(parents=True, exist_ok=True)
    path = bucket_dir / stored
    file.save(path)

    size = path.stat().st_size
    if size > upload_limit_for(user):
        path.unlink(missing_ok=True)
        abort(413, description="This upload is larger than the allowed limit for your role.")

    return {
        "original_filename": original,
        "stored_filename": stored,
        "mime_type": file.mimetype or "application/octet-stream",
        "file_size": size,
    }


def can_preview(item: dict) -> bool:
    if not item.get("stored_filename"):
        return False
    mime = item.get("mime_type") or ""
    ext = Path(item.get("original_filename", "")).suffix.lower()
    return mime.startswith(PREVIEW_MIME_PREFIXES) or ext in PREVIEW_EXTENSIONS


def with_file_links(item: dict, bucket: str) -> dict:
    item["has_file"] = bool(item.get("stored_filename"))
    item["download_url"] = url_for("download_file", bucket=bucket, item_id=item["id"]) if item["has_file"] else ""
    item["preview_url"] = (
        url_for("download_file", bucket=bucket, item_id=item["id"], inline="1")
        if item["has_file"] and can_preview(item)
        else ""
    )
    return item


def create_notification(user_id: int, message: str, link: str = "") -> None:
    execute_db(
        "INSERT INTO notifications (user_id, message, link, read_at, created_at) VALUES (?, ?, ?, '', ?)",
        (user_id, message, link, now_iso()),
    )


def require_submission_access(submission_id: int) -> dict:
    user = current_user()
    with get_db() as db:
        row = db.execute(
            """
            SELECT s.*, u.name AS student_name
            FROM submissions s
            JOIN users u ON u.id = s.student_id
            WHERE s.id = ?
            """,
            (submission_id,),
        ).fetchone()
    item = row_to_dict(row)
    if not item:
        abort(404)
    if user["role"] != "teacher" and item["student_id"] != user["id"]:
        abort(403)
    return item


@app.errorhandler(400)
@app.errorhandler(403)
@app.errorhandler(404)
@app.errorhandler(413)
@app.errorhandler(500)
def json_error(error):
    message = getattr(error, "description", None) or str(error)
    status = getattr(error, "code", 500)
    if request.path.startswith("/api/"):
        return jsonify({"error": message}), status
    return message, status


@app.route("/")
def index():
    return INDEX_HTML


@app.route("/api/me")
def api_me():
    user = current_user()
    return jsonify({"user": user})


@app.route("/api/register", methods=["POST"])
def api_register():
    data = request.get_json(force=True)
    name = clean_text(data.get("name"), 120)
    email = normalize_email(data.get("email"))
    password = data.get("password") or ""
    requested_role = clean_text(data.get("role"), 20)
    role = "teacher" if requested_role == "teacher" else "student"

    if not name or not email or len(password) < 8:
        return jsonify({"error": "Enter a name, email, and password with at least 8 characters."}), 400

    with get_db() as db:
        user_count = db.execute("SELECT COUNT(*) AS count FROM users").fetchone()["count"]
    is_first_user = user_count == 0
    if is_first_user:
        role = "teacher"

    try:
        execute_db(
            """
            INSERT INTO users (name, email, password_hash, role, approved, disabled, created_at)
            VALUES (?, ?, ?, ?, ?, 0, ?)
            """,
            (name, email, generate_password_hash(password), role, 1 if is_first_user else 0, now_iso()),
        )
    except sqlite3.IntegrityError:
        return jsonify({"error": "An account with that email already exists."}), 400

    if is_first_user:
        return jsonify({"ok": True, "message": "First teacher account created. You can sign in now."})

    return jsonify({"ok": True, "message": "Account requested. A teacher needs to approve it."})


@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json(force=True)
    email = normalize_email(data.get("email"))
    password = data.get("password") or ""
    with get_db() as db:
        row = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    user = row_to_dict(row)
    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "Email or password is incorrect."}), 400
    if user["disabled"]:
        return jsonify({"error": "This account is disabled."}), 403
    if not user["approved"]:
        return jsonify({"error": "This account is waiting for teacher approval."}), 403
    session["user_id"] = user["id"]
    return jsonify({"ok": True, "user": user})


@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/account/password", methods=["POST"])
@login_required
def api_change_password():
    user = current_user()
    data = request.get_json(force=True)
    current_password = data.get("current_password") or ""
    new_password = data.get("new_password") or ""

    if len(new_password) < 8:
        return jsonify({"error": "New password must be at least 8 characters."}), 400

    with get_db() as db:
        row = db.execute("SELECT password_hash FROM users WHERE id = ?", (user["id"],)).fetchone()
        if not row or not check_password_hash(row["password_hash"], current_password):
            return jsonify({"error": "Current password is incorrect."}), 400
        db.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (generate_password_hash(new_password), user["id"]),
        )
        db.commit()

    return jsonify({"ok": True, "message": "Password updated."})


@app.route("/api/dashboard")
@login_required
def api_dashboard():
    user = current_user()
    with get_db() as db:
        recent_resources = [
            with_file_links(row_to_dict(row), "resources")
            for row in db.execute(
                """
                SELECT r.*, u.name AS uploader_name,
                       EXISTS(SELECT 1 FROM saves s WHERE s.resource_id = r.id AND s.user_id = ?) AS saved
                FROM resources r
                JOIN users u ON u.id = r.uploaded_by
                ORDER BY r.pinned DESC, r.created_at DESC
                LIMIT 5
                """,
                (user["id"],),
            )
        ]
        recent_inbox = [
            with_file_links(row_to_dict(row), "inbox")
            for row in db.execute(
                """
                SELECT p.*, u.name AS author_name
                FROM inbox_posts p
                JOIN users u ON u.id = p.author_id
                WHERE p.deleted_at = ''
                ORDER BY p.pinned DESC, p.created_at DESC
                LIMIT 5
                """
            )
        ]
        saved_resources = [
            with_file_links(row_to_dict(row), "resources")
            for row in db.execute(
                """
                SELECT r.*, u.name AS uploader_name, 1 AS saved
                FROM saves s
                JOIN resources r ON r.id = s.resource_id
                JOIN users u ON u.id = r.uploaded_by
                WHERE s.user_id = ?
                ORDER BY s.created_at DESC
                LIMIT 5
                """,
                (user["id"],),
            )
        ]
        unread_notifications = db.execute(
            "SELECT COUNT(*) AS count FROM notifications WHERE user_id = ? AND read_at = ''",
            (user["id"],),
        ).fetchone()["count"]

        payload = {
            "recent_resources": recent_resources,
            "recent_inbox": recent_inbox,
            "saved_resources": saved_resources,
            "unread_notifications": unread_notifications,
        }

        if user["role"] == "teacher":
            payload["pending_users"] = [
                row_to_dict(row)
                for row in db.execute(
                    "SELECT id, name, email, role, created_at FROM users WHERE approved = 0 ORDER BY created_at DESC"
                )
            ]
            payload["resource_reviews"] = [
                with_file_links(row_to_dict(row), "resource_reviews")
                for row in db.execute(
                    """
                    SELECT rr.*, u.name AS student_name
                    FROM resource_reviews rr
                    JOIN users u ON u.id = rr.student_id
                    WHERE rr.status = 'pending'
                    ORDER BY rr.created_at DESC
                    LIMIT 6
                    """
                )
            ]
            payload["recent_submissions"] = [
                with_file_links(row_to_dict(row), "submissions")
                for row in db.execute(
                    """
                    SELECT s.*, u.name AS student_name,
                           (SELECT COUNT(*) FROM submission_comments c WHERE c.submission_id = s.id) AS comment_count
                    FROM submissions s
                    JOIN users u ON u.id = s.student_id
                    ORDER BY s.updated_at DESC
                    LIMIT 6
                    """
                )
            ]
            payload["student_activity"] = [
                row_to_dict(row)
                for row in db.execute(
                    """
                    SELECT u.id, u.name,
                           (SELECT COUNT(*) FROM submissions s WHERE s.student_id = u.id) AS submissions,
                           (SELECT COUNT(*) FROM inbox_posts p WHERE p.author_id = u.id AND p.deleted_at = '') AS inbox_posts
                    FROM users u
                    WHERE u.role = 'student' AND u.approved = 1 AND u.disabled = 0
                    ORDER BY u.name
                    LIMIT 12
                    """
                )
            ]
        else:
            payload["my_resource_reviews"] = [
                with_file_links(row_to_dict(row), "resource_reviews")
                for row in db.execute(
                    """
                    SELECT rr.*, u.name AS student_name
                    FROM resource_reviews rr
                    JOIN users u ON u.id = rr.student_id
                    WHERE rr.student_id = ?
                    ORDER BY rr.updated_at DESC
                    LIMIT 5
                    """,
                    (user["id"],),
                )
            ]
            payload["latest_teacher_comments"] = [
                row_to_dict(row)
                for row in db.execute(
                    """
                    SELECT c.*, s.title AS submission_title, u.name AS teacher_name
                    FROM submission_comments c
                    JOIN submissions s ON s.id = c.submission_id
                    JOIN users u ON u.id = c.teacher_id
                    WHERE s.student_id = ?
                    ORDER BY c.created_at DESC
                    LIMIT 5
                    """,
                    (user["id"],),
                )
            ]
            payload["my_submissions"] = [
                with_file_links(row_to_dict(row), "submissions")
                for row in db.execute(
                    """
                    SELECT s.*, u.name AS student_name,
                           (SELECT COUNT(*) FROM submission_comments c WHERE c.submission_id = s.id) AS comment_count
                    FROM submissions s
                    JOIN users u ON u.id = s.student_id
                    WHERE s.student_id = ?
                    ORDER BY s.updated_at DESC
                    LIMIT 5
                    """,
                    (user["id"],),
                )
            ]

    return jsonify(payload)


@app.route("/api/users")
@teacher_required
def api_users():
    with get_db() as db:
        users = [
            row_to_dict(row)
            for row in db.execute(
                """
                SELECT id, name, email, role, approved, disabled, created_at
                FROM users
                ORDER BY approved ASC, disabled ASC, role DESC, name ASC
                """
            )
        ]
    return jsonify({"users": users})


@app.route("/api/users/<int:user_id>", methods=["PATCH"])
@teacher_required
def api_update_user(user_id: int):
    data = request.get_json(force=True)
    current = current_user()
    with get_db() as db:
        target = row_to_dict(db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())
        if not target:
            return jsonify({"error": "User not found."}), 404
        role = data.get("role", target["role"])
        role = "teacher" if role == "teacher" else "student"
        approved = 1 if data.get("approved", target["approved"]) else 0
        disabled = 1 if data.get("disabled", target["disabled"]) else 0
        if target["id"] == current["id"] and disabled:
            return jsonify({"error": "You cannot disable your own account."}), 400
        db.execute(
            "UPDATE users SET role = ?, approved = ?, disabled = ? WHERE id = ?",
            (role, approved, disabled, user_id),
        )
        db.commit()
    if approved and not target["approved"]:
        create_notification(user_id, "Your GenWise AI/ML Classroom account was approved.")
    return jsonify({"ok": True})


@app.route("/api/resources", methods=["GET", "POST"])
@login_required
def api_resources():
    user = current_user()
    if request.method == "POST":
        bucket = "resources" if user["role"] == "teacher" else "resource_reviews"
        meta = save_upload(request.files.get("file"), bucket, user)
        now = now_iso()
        title = clean_text(request.form.get("title"), 180) or "Untitled resource"
        kind = clean_text(request.form.get("kind"), 40) or "resource"
        description = clean_text(request.form.get("description"), 1200)
        body = clean_text(request.form.get("body"), 12000)
        url = clean_text(request.form.get("url"), 1000)
        tags = clean_text(request.form.get("tags"), 500)

        if user["role"] != "teacher":
            review_id = execute_db(
                """
                INSERT INTO resource_reviews
                (title, kind, description, body, url, tags, original_filename, stored_filename,
                 mime_type, file_size, student_id, status, teacher_comment, reviewed_by, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', '', NULL, ?, ?)
                """,
                (
                    title,
                    kind,
                    description,
                    body,
                    url,
                    tags,
                    meta["original_filename"],
                    meta["stored_filename"],
                    meta["mime_type"],
                    meta["file_size"],
                    user["id"],
                    now,
                    now,
                ),
            )
            with get_db() as db:
                teacher_ids = [
                    row["id"]
                    for row in db.execute(
                        "SELECT id FROM users WHERE role = 'teacher' AND approved = 1 AND disabled = 0"
                    )
                ]
            for teacher_id in teacher_ids:
                create_notification(teacher_id, f"New student resource upload: {title}.", "#resources")
            return jsonify({"ok": True, "id": review_id, "review": True})

        resource_id = execute_db(
            """
            INSERT INTO resources
            (title, kind, description, body, url, tags, original_filename, stored_filename,
             mime_type, file_size, uploaded_by, pinned, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                title,
                kind,
                description,
                body,
                url,
                tags,
                meta["original_filename"],
                meta["stored_filename"],
                meta["mime_type"],
                meta["file_size"],
                user["id"],
                1 if request.form.get("pinned") == "true" else 0,
                now,
                now,
            ),
        )
        return jsonify({"ok": True, "id": resource_id})

    q = clean_text(request.args.get("q"), 200).lower()
    saved_only = request.args.get("saved") == "1"
    params: list = [user["id"]]
    where = []
    if q:
        like = f"%{q}%"
        where.append("(LOWER(r.title) LIKE ? OR LOWER(r.description) LIKE ? OR LOWER(r.body) LIKE ? OR LOWER(r.tags) LIKE ? OR LOWER(r.url) LIKE ?)")
        params.extend([like, like, like, like, like])
    if saved_only:
        where.append("EXISTS(SELECT 1 FROM saves ss WHERE ss.resource_id = r.id AND ss.user_id = ?)")
        params.append(user["id"])
    where_sql = "WHERE " + " AND ".join(where) if where else ""
    with get_db() as db:
        rows = db.execute(
            f"""
            SELECT r.*, u.name AS uploader_name,
                   EXISTS(SELECT 1 FROM saves s WHERE s.resource_id = r.id AND s.user_id = ?) AS saved
            FROM resources r
            JOIN users u ON u.id = r.uploaded_by
            {where_sql}
            ORDER BY r.pinned DESC, r.created_at DESC
            """,
            tuple(params),
        ).fetchall()
    return jsonify({"resources": [with_file_links(row_to_dict(row), "resources") for row in rows]})


@app.route("/api/resource-reviews")
@login_required
def api_resource_reviews():
    user = current_user()
    where = "WHERE rr.status != 'deleted'"
    params: tuple = ()
    if user["role"] != "teacher":
        where = "WHERE rr.student_id = ? AND rr.status != 'deleted'"
        params = (user["id"],)
    with get_db() as db:
        rows = db.execute(
            f"""
            SELECT rr.*, u.name AS student_name, reviewer.name AS reviewer_name
            FROM resource_reviews rr
            JOIN users u ON u.id = rr.student_id
            LEFT JOIN users reviewer ON reviewer.id = rr.reviewed_by
            {where}
            ORDER BY
              CASE rr.status WHEN 'pending' THEN 0 WHEN 'published' THEN 1 ELSE 2 END,
              rr.updated_at DESC
            """,
            params,
        ).fetchall()
    return jsonify({"reviews": [with_file_links(row_to_dict(row), "resource_reviews") for row in rows]})


@app.route("/api/resource-reviews/<int:review_id>", methods=["PATCH"])
@teacher_required
def api_resource_review_item(review_id: int):
    user = current_user()
    data = request.get_json(force=True)
    action = clean_text(data.get("action"), 40)
    teacher_comment = clean_text(data.get("teacher_comment"), 1200)
    now = now_iso()

    with get_db() as db:
        review = row_to_dict(
            db.execute(
                """
                SELECT rr.*, u.name AS student_name
                FROM resource_reviews rr
                JOIN users u ON u.id = rr.student_id
                WHERE rr.id = ?
                """,
                (review_id,),
            ).fetchone()
        )
        if not review:
            return jsonify({"error": "Student resource upload not found."}), 404

    if action == "publish":
        stored_filename = review["stored_filename"]
        if stored_filename:
            source = UPLOAD_DIR / "resource_reviews" / stored_filename
            target = UPLOAD_DIR / "resources" / stored_filename
            if source.exists() and not target.exists():
                shutil.copy2(source, target)
        resource_id = execute_db(
            """
            INSERT INTO resources
            (title, kind, description, body, url, tags, original_filename, stored_filename,
             mime_type, file_size, uploaded_by, pinned, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
            """,
            (
                review["title"],
                review["kind"],
                review["description"],
                review["body"],
                review["url"],
                review["tags"],
                review["original_filename"],
                stored_filename,
                review["mime_type"],
                review["file_size"],
                user["id"],
                now,
                now,
            ),
        )
        execute_db(
            """
            UPDATE resource_reviews
            SET status = 'published', teacher_comment = ?, reviewed_by = ?, updated_at = ?
            WHERE id = ?
            """,
            (teacher_comment, user["id"], now, review_id),
        )
        create_notification(review["student_id"], f"Your resource upload was published: {review['title']}.", "#resources")
        return jsonify({"ok": True, "resource_id": resource_id})

    if action == "private":
        execute_db(
            """
            UPDATE resource_reviews
            SET status = 'private', teacher_comment = ?, reviewed_by = ?, updated_at = ?
            WHERE id = ?
            """,
            (teacher_comment, user["id"], now, review_id),
        )
        create_notification(review["student_id"], f"Teacher reviewed your resource upload: {review['title']}.", "#resources")
        return jsonify({"ok": True})

    if action == "delete":
        execute_db(
            """
            UPDATE resource_reviews
            SET status = 'deleted', teacher_comment = ?, reviewed_by = ?, updated_at = ?
            WHERE id = ?
            """,
            (teacher_comment, user["id"], now, review_id),
        )
        create_notification(review["student_id"], f"Teacher removed your resource upload: {review['title']}.", "#resources")
        return jsonify({"ok": True})

    if action == "comment":
        execute_db(
            """
            UPDATE resource_reviews
            SET teacher_comment = ?, reviewed_by = ?, updated_at = ?
            WHERE id = ?
            """,
            (teacher_comment, user["id"], now, review_id),
        )
        create_notification(review["student_id"], f"Teacher commented on your resource upload: {review['title']}.", "#resources")
        return jsonify({"ok": True})

    return jsonify({"error": "Choose publish, private, delete, or comment."}), 400


@app.route("/api/resources/<int:resource_id>", methods=["PATCH", "DELETE"])
@teacher_required
def api_resource_item(resource_id: int):
    if request.method == "DELETE":
        with get_db() as db:
            row = row_to_dict(db.execute("SELECT * FROM resources WHERE id = ?", (resource_id,)).fetchone())
            if not row:
                return jsonify({"error": "Resource not found."}), 404
            db.execute("DELETE FROM saves WHERE resource_id = ?", (resource_id,))
            db.execute("DELETE FROM resources WHERE id = ?", (resource_id,))
            db.commit()
        if row.get("stored_filename"):
            (UPLOAD_DIR / "resources" / row["stored_filename"]).unlink(missing_ok=True)
        return jsonify({"ok": True})

    data = request.get_json(force=True)
    pinned = 1 if data.get("pinned") else 0
    execute_db("UPDATE resources SET pinned = ?, updated_at = ? WHERE id = ?", (pinned, now_iso(), resource_id))
    return jsonify({"ok": True})


@app.route("/api/resources/<int:resource_id>/save", methods=["POST", "DELETE"])
@login_required
def api_save_resource(resource_id: int):
    user = current_user()
    if request.method == "POST":
        try:
            execute_db(
                "INSERT INTO saves (user_id, resource_id, created_at) VALUES (?, ?, ?)",
                (user["id"], resource_id, now_iso()),
            )
        except sqlite3.IntegrityError:
            pass
    else:
        execute_db("DELETE FROM saves WHERE user_id = ? AND resource_id = ?", (user["id"], resource_id))
    return jsonify({"ok": True})


@app.route("/api/inbox", methods=["GET", "POST"])
@login_required
def api_inbox():
    user = current_user()
    if request.method == "POST":
        meta = save_upload(request.files.get("file"), "inbox", user)
        now = now_iso()
        post_id = execute_db(
            """
            INSERT INTO inbox_posts
            (title, body, url, original_filename, stored_filename, mime_type, file_size,
             author_id, pinned, deleted_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?)
            """,
            (
                clean_text(request.form.get("title"), 180) or "Inbox post",
                clean_text(request.form.get("body"), 5000),
                clean_text(request.form.get("url"), 1000),
                meta["original_filename"],
                meta["stored_filename"],
                meta["mime_type"],
                meta["file_size"],
                user["id"],
                1 if user["role"] == "teacher" and request.form.get("pinned") == "true" else 0,
                now,
                now,
            ),
        )
        return jsonify({"ok": True, "id": post_id})

    with get_db() as db:
        posts = []
        rows = db.execute(
            """
            SELECT p.*, u.name AS author_name, u.role AS author_role
            FROM inbox_posts p
            JOIN users u ON u.id = p.author_id
            WHERE p.deleted_at = ''
            ORDER BY p.pinned DESC, p.created_at DESC
            """
        ).fetchall()
        for row in rows:
            post = with_file_links(row_to_dict(row), "inbox")
            replies = [
                row_to_dict(reply)
                for reply in db.execute(
                    """
                    SELECT r.*, u.name AS author_name, u.role AS author_role
                    FROM inbox_replies r
                    JOIN users u ON u.id = r.author_id
                    WHERE r.post_id = ?
                    ORDER BY r.created_at ASC
                    """,
                    (post["id"],),
                )
            ]
            post["replies"] = replies
            posts.append(post)
    return jsonify({"posts": posts})


@app.route("/api/inbox/<int:post_id>/reply", methods=["POST"])
@login_required
def api_inbox_reply(post_id: int):
    user = current_user()
    data = request.get_json(force=True)
    body = clean_text(data.get("body"), 3000)
    if not body:
        return jsonify({"error": "Reply cannot be blank."}), 400
    execute_db(
        "INSERT INTO inbox_replies (post_id, body, author_id, created_at) VALUES (?, ?, ?, ?)",
        (post_id, body, user["id"], now_iso()),
    )
    return jsonify({"ok": True})


@app.route("/api/inbox/<int:post_id>", methods=["PATCH", "DELETE"])
@login_required
def api_inbox_item(post_id: int):
    user = current_user()
    with get_db() as db:
        post = row_to_dict(db.execute("SELECT * FROM inbox_posts WHERE id = ?", (post_id,)).fetchone())
    if not post:
        return jsonify({"error": "Inbox post not found."}), 404

    if request.method == "DELETE":
        if user["role"] != "teacher" and post["author_id"] != user["id"]:
            return jsonify({"error": "You can only delete your own inbox posts."}), 403
        execute_db("UPDATE inbox_posts SET deleted_at = ?, updated_at = ? WHERE id = ?", (now_iso(), now_iso(), post_id))
        return jsonify({"ok": True})

    if user["role"] != "teacher":
        return jsonify({"error": "Only teachers can pin inbox posts."}), 403
    data = request.get_json(force=True)
    execute_db(
        "UPDATE inbox_posts SET pinned = ?, updated_at = ? WHERE id = ?",
        (1 if data.get("pinned") else 0, now_iso(), post_id),
    )
    return jsonify({"ok": True})


@app.route("/api/submissions", methods=["GET", "POST"])
@login_required
def api_submissions():
    user = current_user()
    if request.method == "POST":
        if user["role"] != "student":
            return jsonify({"error": "Submissions are for student work."}), 403
        meta = save_upload(request.files.get("file"), "submissions", user)
        now = now_iso()
        submission_id = execute_db(
            """
            INSERT INTO submissions
            (title, description, text_content, url, original_filename, stored_filename, mime_type,
             file_size, student_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                clean_text(request.form.get("title"), 180) or "Untitled submission",
                clean_text(request.form.get("description"), 1200),
                clean_text(request.form.get("text_content"), 12000),
                clean_text(request.form.get("url"), 1000),
                meta["original_filename"],
                meta["stored_filename"],
                meta["mime_type"],
                meta["file_size"],
                user["id"],
                now,
                now,
            ),
        )
        return jsonify({"ok": True, "id": submission_id})

    where = ""
    params: tuple = ()
    if user["role"] != "teacher":
        where = "WHERE s.student_id = ?"
        params = (user["id"],)
    with get_db() as db:
        submissions = [
            with_file_links(row_to_dict(row), "submissions")
            for row in db.execute(
                f"""
                SELECT s.*, u.name AS student_name,
                       (SELECT COUNT(*) FROM submission_comments c WHERE c.submission_id = s.id) AS comment_count
                FROM submissions s
                JOIN users u ON u.id = s.student_id
                {where}
                ORDER BY s.updated_at DESC
                """,
                params,
            )
        ]
    return jsonify({"submissions": submissions})


@app.route("/api/submissions/<int:submission_id>/comments", methods=["GET", "POST"])
@login_required
def api_submission_comments(submission_id: int):
    item = require_submission_access(submission_id)
    user = current_user()
    if request.method == "POST":
        if user["role"] != "teacher":
            return jsonify({"error": "Only teachers can comment on submissions."}), 403
        data = request.get_json(force=True)
        body = clean_text(data.get("body"), 4000)
        if not body:
            return jsonify({"error": "Comment cannot be blank."}), 400
        execute_db(
            "INSERT INTO submission_comments (submission_id, teacher_id, body, created_at) VALUES (?, ?, ?, ?)",
            (submission_id, user["id"], body, now_iso()),
        )
        execute_db("UPDATE submissions SET updated_at = ? WHERE id = ?", (now_iso(), submission_id))
        create_notification(item["student_id"], f"New teacher comment on {item['title']}.", "#submissions")
        return jsonify({"ok": True})

    with get_db() as db:
        comments = [
            row_to_dict(row)
            for row in db.execute(
                """
                SELECT c.*, u.name AS teacher_name
                FROM submission_comments c
                JOIN users u ON u.id = c.teacher_id
                WHERE c.submission_id = ?
                ORDER BY c.created_at ASC
                """,
                (submission_id,),
            )
        ]
    return jsonify({"comments": comments})


@app.route("/api/teacher-room", methods=["GET", "POST"])
@teacher_required
def api_teacher_room():
    user = current_user()
    if request.method == "POST":
        meta = save_upload(request.files.get("file"), "teacher_room", user)
        now = now_iso()
        item_id = execute_db(
            """
            INSERT INTO teacher_room_items
            (title, kind, description, body, url, tags, original_filename, stored_filename,
             mime_type, file_size, uploaded_by, pinned, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                clean_text(request.form.get("title"), 180) or "Teacher room item",
                clean_text(request.form.get("kind"), 40) or "note",
                clean_text(request.form.get("description"), 1200),
                clean_text(request.form.get("body"), 12000),
                clean_text(request.form.get("url"), 1000),
                clean_text(request.form.get("tags"), 500),
                meta["original_filename"],
                meta["stored_filename"],
                meta["mime_type"],
                meta["file_size"],
                user["id"],
                1 if request.form.get("pinned") == "true" else 0,
                now,
                now,
            ),
        )
        return jsonify({"ok": True, "id": item_id})

    with get_db() as db:
        items = [
            with_file_links(row_to_dict(row), "teacher_room")
            for row in db.execute(
                """
                SELECT t.*, u.name AS uploader_name
                FROM teacher_room_items t
                JOIN users u ON u.id = t.uploaded_by
                ORDER BY t.pinned DESC, t.created_at DESC
                """
            )
        ]
    return jsonify({"items": items})


@app.route("/api/teacher-room/<int:item_id>", methods=["PATCH", "DELETE"])
@teacher_required
def api_teacher_room_item(item_id: int):
    if request.method == "DELETE":
        with get_db() as db:
            row = row_to_dict(db.execute("SELECT * FROM teacher_room_items WHERE id = ?", (item_id,)).fetchone())
            if not row:
                return jsonify({"error": "Teacher room item not found."}), 404
            db.execute("DELETE FROM teacher_room_items WHERE id = ?", (item_id,))
            db.commit()
        if row.get("stored_filename"):
            (UPLOAD_DIR / "teacher_room" / row["stored_filename"]).unlink(missing_ok=True)
        return jsonify({"ok": True})
    data = request.get_json(force=True)
    execute_db(
        "UPDATE teacher_room_items SET pinned = ?, updated_at = ? WHERE id = ?",
        (1 if data.get("pinned") else 0, now_iso(), item_id),
    )
    return jsonify({"ok": True})


@app.route("/api/notifications", methods=["GET", "POST"])
@login_required
def api_notifications():
    user = current_user()
    if request.method == "POST":
        execute_db("UPDATE notifications SET read_at = ? WHERE user_id = ? AND read_at = ''", (now_iso(), user["id"]))
        return jsonify({"ok": True})
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM notifications WHERE user_id = ? ORDER BY created_at DESC LIMIT 30",
            (user["id"],),
        ).fetchall()
    return jsonify({"notifications": [row_to_dict(row) for row in rows]})


@app.route("/api/ai/profile", methods=["GET", "POST"])
@login_required
def api_ai_profile():
    user = current_user()
    with get_db() as db:
        existing = row_to_dict(db.execute("SELECT * FROM ai_profiles WHERE user_id = ?", (user["id"],)).fetchone())
        if request.method == "POST":
            data = request.get_json(force=True)
            tone = clean_text(data.get("tone"), 240) or "friendly and clear"
            helpfulness = clean_text(data.get("helpfulness"), 500) or "explain ideas without doing classwork"
            focus = clean_text(data.get("focus"), 500) or "AI and machine learning research questions"
            custom = clean_text(data.get("custom_instructions"), 1200)
            if existing:
                db.execute(
                    """
                    UPDATE ai_profiles
                    SET tone = ?, helpfulness = ?, focus = ?, custom_instructions = ?
                    WHERE user_id = ?
                    """,
                    (tone, helpfulness, focus, custom, user["id"]),
                )
            else:
                db.execute(
                    """
                    INSERT INTO ai_profiles (user_id, tone, helpfulness, focus, custom_instructions)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (user["id"], tone, helpfulness, focus, custom),
                )
            db.commit()
            return jsonify({"ok": True})

        if not existing:
            db.execute("INSERT INTO ai_profiles (user_id) VALUES (?)", (user["id"],))
            db.commit()
            existing = row_to_dict(db.execute("SELECT * FROM ai_profiles WHERE user_id = ?", (user["id"],)).fetchone())
    return jsonify({"profile": existing})


@app.route("/api/ai/history")
@login_required
def api_ai_history():
    user = current_user()
    with get_db() as db:
        rows = db.execute(
            """
            SELECT role, content, citations_json, created_at
            FROM ai_messages
            WHERE user_id = ?
            ORDER BY created_at ASC
            LIMIT 80
            """,
            (user["id"],),
        ).fetchall()
    return jsonify({"messages": [row_to_dict(row) for row in rows]})


def search_class_resources(query: str, user: dict, limit: int = 5) -> list[dict]:
    terms = [term for term in query.lower().replace("\n", " ").split(" ") if len(term) > 2]
    with get_db() as db:
        rows = db.execute(
            """
            SELECT id, title, kind, description, body, url, tags, created_at
            FROM resources
            ORDER BY pinned DESC, created_at DESC
            LIMIT 60
            """
        ).fetchall()
    scored = []
    for row in rows:
        item = row_to_dict(row)
        haystack = " ".join(
            [
                item.get("title", ""),
                item.get("kind", ""),
                item.get("description", ""),
                item.get("body", ""),
                item.get("url", ""),
                item.get("tags", ""),
            ]
        ).lower()
        score = sum(haystack.count(term) for term in terms) if terms else 1
        if score or not terms:
            item["score"] = score
            scored.append(item)
    scored.sort(key=lambda value: (value["score"], value["created_at"]), reverse=True)
    return scored[:limit]


def build_ai_context(resources: list[dict]) -> str:
    if not resources:
        return "No matching classroom resources were found."
    lines = []
    for resource in resources:
        snippet = resource.get("description") or resource.get("body") or resource.get("url") or ""
        snippet = snippet.replace("\n", " ")[:600]
        lines.append(
            f"- Resource #{resource['id']}: {resource['title']} ({resource['kind']}). "
            f"Tags: {resource.get('tags') or 'none'}. Notes: {snippet}"
        )
    return "\n".join(lines)


def fallback_ai_answer(question: str, citations: list[dict], profile: dict, user: dict) -> str:
    topic = question.strip().rstrip("?!.")
    if not citations:
        return (
            "I can help with research questions by searching classroom resources and suggesting a path. "
            f"I did not find a close classroom-resource match for \"{topic}\" yet.\n\n"
            "Try this research path:\n"
            "1. Define the key AI/ML idea in your own words.\n"
            "2. Compare it with one related idea, model, tool, or risk.\n"
            "3. Look for an example, limitation, and classroom connection.\n"
            "4. Ask a narrower follow-up question so I can search the class resources again."
        )
    cited = "\n".join(f"- {item['title']} ({item['kind']})" for item in citations)
    focus = profile.get("focus") or "AI and machine learning research"
    role_note = (
        "As a teacher, you may want to use these to guide a class explanation or discussion."
        if user["role"] == "teacher"
        else "As a student, use these as research starting points, not as finished work."
    )
    return (
        f"I found classroom resources that may help with \"{topic}\".\n\n"
        f"Sources used:\n{cited}\n\n"
        f"Research focus: {focus}\n"
        f"{role_note}\n\n"
        "Suggested next steps:\n"
        "1. Open the most relevant source and note the main claim or explanation.\n"
        "2. Check whether it gives an example, evidence, or practical use case.\n"
        "3. Ask me a narrower question about one term, method, or comparison from that source."
    )


@app.route("/api/ai/chat", methods=["POST"])
@login_required
def api_ai_chat():
    user = current_user()
    data = request.get_json(force=True)
    question = clean_text(data.get("message"), 4000)
    if not question:
        return jsonify({"error": "Ask a question first."}), 400

    with get_db() as db:
        profile = row_to_dict(db.execute("SELECT * FROM ai_profiles WHERE user_id = ?", (user["id"],)).fetchone())
        if not profile:
            db.execute("INSERT INTO ai_profiles (user_id) VALUES (?)", (user["id"],))
            db.commit()
            profile = row_to_dict(db.execute("SELECT * FROM ai_profiles WHERE user_id = ?", (user["id"],)).fetchone())
        history_rows = db.execute(
            """
            SELECT role, content
            FROM ai_messages
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT 10
            """,
            (user["id"],),
        ).fetchall()

    citations = search_class_resources(question, user)
    citations_payload = [
        {"id": item["id"], "title": item["title"], "kind": item["kind"]} for item in citations
    ]
    context = build_ai_context(citations)
    _ = context, history_rows
    answer = fallback_ai_answer(question, citations_payload, profile, user)

    citations_json = json.dumps(citations_payload)
    execute_db(
        "INSERT INTO ai_messages (user_id, role, content, citations_json, created_at) VALUES (?, 'user', ?, '[]', ?)",
        (user["id"], question, now_iso()),
    )
    execute_db(
        "INSERT INTO ai_messages (user_id, role, content, citations_json, created_at) VALUES (?, 'assistant', ?, ?, ?)",
        (user["id"], answer, citations_json, now_iso()),
    )
    return jsonify({"answer": answer, "citations": citations_payload})


@app.route("/file/<bucket>/<int:item_id>")
@login_required
def download_file(bucket: str, item_id: int):
    user = current_user()
    table_by_bucket = {
        "resources": "resources",
        "resource_reviews": "resource_reviews",
        "submissions": "submissions",
        "inbox": "inbox_posts",
        "teacher_room": "teacher_room_items",
    }
    if bucket not in table_by_bucket:
        abort(404)
    table = table_by_bucket[bucket]

    with get_db() as db:
        item = row_to_dict(db.execute(f"SELECT * FROM {table} WHERE id = ?", (item_id,)).fetchone())
    if not item or not item.get("stored_filename"):
        abort(404)

    if bucket == "teacher_room" and user["role"] != "teacher":
        abort(403)
    if bucket == "resource_reviews" and user["role"] != "teacher" and item["student_id"] != user["id"]:
        abort(403)
    if bucket == "submissions" and user["role"] != "teacher" and item["student_id"] != user["id"]:
        abort(403)
    if bucket == "inbox" and item.get("deleted_at"):
        abort(404)

    path = UPLOAD_DIR / bucket / item["stored_filename"]
    if not path.exists():
        abort(404)
    inline = request.args.get("inline") == "1" and can_preview(item)
    return send_file(
        path,
        mimetype=item.get("mime_type") or "application/octet-stream",
        as_attachment=not inline,
        download_name=item.get("original_filename") or path.name,
    )


@app.route("/health")
def health():
    return jsonify({"ok": True, "app": "GenWise AI/ML Classroom"})


init_db()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "8777")), debug=False)
