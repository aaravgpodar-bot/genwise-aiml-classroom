import json
import os
import secrets
import shutil
import sqlite3
import uuid
import pg8000
import re
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
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

try:
    from .supabase_integration import SupabaseClient, SupabaseConfig, load_dotenv
except ImportError:
    from supabase_integration import SupabaseClient, SupabaseConfig, load_dotenv


ROOT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = ROOT_DIR.parent
load_dotenv(PROJECT_DIR / ".env")
DATA_DIR = Path(os.getenv("GENWISE_DATA_DIR", str(ROOT_DIR / "instance")))
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "genwise.db"
SUPABASE_CONFIG = SupabaseConfig.from_env()
SUPABASE_CLIENT = SupabaseClient(SUPABASE_CONFIG)

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
    for bucket in ("resources", "resource_reviews", "assignments", "submissions", "inbox", "teacher_room"):
        (UPLOAD_DIR / bucket).mkdir(parents=True, exist_ok=True)


app.config["SECRET_KEY"] = load_secret_key()


class PostgresRow:
    def __init__(self, cursor_wrapper, row_data):
        self._keys = [col[0] for col in cursor_wrapper.cursor.description]
        self._data = row_data
        self._dict = dict(zip(self._keys, row_data))

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._data[key]
        return self._dict[key]

    def keys(self):
        return self._keys

class PostgresCursorWrapper:
    def __init__(self, cursor):
        self.cursor = cursor
        self._lastrowid = None

    def execute(self, sql, params=()):
        sql = sql.replace("?", "%s")
        if "PRAGMA table_info" in sql:
            match = re.search(r"PRAGMA table_info\((\w+)\)", sql)
            if match:
                table_name = match.group(1).lower()
                postgres_sql = """
                    SELECT column_name AS name
                    FROM information_schema.columns
                    WHERE table_schema = 'aarav' AND table_name = %s;
                """
                self.cursor.execute(postgres_sql, (table_name,))
                return self
        
        is_insert = sql.strip().upper().startswith("INSERT")
        if is_insert and "RETURNING" not in sql.upper():
            sql_stripped = sql.strip().rstrip(";")
            sql = sql_stripped + " RETURNING id;"
        
        try:
            self.cursor.execute(sql, params)
        except pg8000.exceptions.DatabaseError as e:
            err_msg = str(e)
            if any(code in err_msg for code in ["23505", "23503", "23514"]):
                raise sqlite3.IntegrityError(err_msg)
            raise e
        
        if is_insert:
            try:
                res = self.cursor.fetchone()
                if res:
                    self._lastrowid = res[0]
            except Exception:
                pass
        return self

    @property
    def lastrowid(self):
        return self._lastrowid

    def fetchone(self):
        row = self.cursor.fetchone()
        if row is None:
            return None
        return PostgresRow(self, row)

    def fetchall(self):
        rows = self.cursor.fetchall()
        return [PostgresRow(self, r) for r in rows]

    def __iter__(self):
        while True:
            row = self.fetchone()
            if row is None:
                break
            yield row

    def close(self):
        self.cursor.close()

class PostgresConnectionWrapper:
    def __init__(self, pg_conn):
        self.conn = pg_conn

    def cursor(self):
        return PostgresCursorWrapper(self.conn.cursor())

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def close(self):
        self.conn.close()

    def execute(self, sql, params=()):
        cursor = self.cursor()
        cursor.execute(sql, params)
        return cursor

    def executescript(self, script_sql):
        statements = script_sql.split(";")
        cursor = self.cursor()
        for statement in statements:
            stmt = statement.strip()
            if not stmt:
                continue
            stmt = stmt.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
            cursor.execute(stmt)
        self.commit()


@contextmanager
def get_db():
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        import urllib.parse
        parsed = urllib.parse.urlparse(db_url)
        conn = pg8000.connect(
            user=parsed.username,
            password=parsed.password,
            host=parsed.hostname,
            port=parsed.port or 5432,
            database=parsed.path.lstrip('/')
        )
        cursor = conn.cursor()
        cursor.execute("SET search_path TO aarav;")
        conn.commit()
        cursor.close()
        
        wrapper = PostgresConnectionWrapper(conn)
        try:
            yield wrapper
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
    else:
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

            CREATE TABLE IF NOT EXISTS assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                instructions TEXT NOT NULL DEFAULT '',
                url TEXT NOT NULL DEFAULT '',
                due_at TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'open',
                original_filename TEXT NOT NULL DEFAULT '',
                stored_filename TEXT NOT NULL DEFAULT '',
                mime_type TEXT NOT NULL DEFAULT '',
                file_size INTEGER NOT NULL DEFAULT 0,
                created_by INTEGER NOT NULL,
                pinned INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (created_by) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS assignment_saves (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                assignment_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(user_id, assignment_id),
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (assignment_id) REFERENCES assignments(id)
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

            CREATE TABLE IF NOT EXISTS inbox_saves (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                post_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(user_id, post_id),
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (post_id) REFERENCES inbox_posts(id)
            );

            CREATE TABLE IF NOT EXISTS submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                assignment_id INTEGER,
                visibility TEXT NOT NULL DEFAULT 'private',
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
                FOREIGN KEY (assignment_id) REFERENCES assignments(id),
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

            CREATE TABLE IF NOT EXISTS password_reset_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                code_hash TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                used_at TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
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
        columns = {row["name"] for row in db.execute("PRAGMA table_info(submissions)").fetchall()}
        if "assignment_id" not in columns:
            db.execute("ALTER TABLE submissions ADD COLUMN assignment_id INTEGER REFERENCES assignments(id)")
        if "visibility" not in columns:
            db.execute("ALTER TABLE submissions ADD COLUMN visibility TEXT NOT NULL DEFAULT 'private'")
        comment_columns = {row["name"] for row in db.execute("PRAGMA table_info(submission_comments)").fetchall()}
        if "author_id" not in comment_columns:
            db.execute("ALTER TABLE submission_comments ADD COLUMN author_id INTEGER")
            db.execute("UPDATE submission_comments SET author_id = teacher_id WHERE author_id IS NULL")
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


def public_user(user: dict | None) -> dict | None:
    if not user:
        return None
    safe = dict(user)
    safe.pop("password_hash", None)
    return safe


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

    if SUPABASE_CONFIG.configured:
        slug = SUPABASE_CONFIG.app_slugs[0] if SUPABASE_CONFIG.app_slugs else "aarav-genwise-aiml-classroom"
        object_name = f"{slug}/{bucket}/{stored}"
        result = SUPABASE_CLIENT.upload_file(path, object_name, file.mimetype or "application/octet-stream")
        if result.get("ok"):
            app.logger.info("Mirrored upload to Supabase Storage: %s", object_name)
        else:
            app.logger.warning("Supabase Storage mirror failed for %s: %s", object_name, result.get("message"))

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
            SELECT s.*, u.name AS student_name, a.title AS assignment_title
            FROM submissions s
            JOIN users u ON u.id = s.student_id
            LEFT JOIN assignments a ON a.id = s.assignment_id
            WHERE s.id = ?
            """,
            (submission_id,),
        ).fetchone()
    item = row_to_dict(row)
    if not item:
        abort(404)
    if item.get("visibility") == "class":
        return item
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
    return render_template("index.html")


@app.route("/api/me")
def api_me():
    user = current_user()
    return jsonify({"user": public_user(user)})


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

    try:
        execute_db(
            """
            INSERT INTO users (name, email, password_hash, role, approved, disabled, created_at)
            VALUES (?, ?, ?, ?, ?, 0, ?)
            """,
            (name, email, generate_password_hash(password), role, 1, now_iso()),
        )
    except sqlite3.IntegrityError:
        return jsonify({"error": "An account with that email already exists."}), 400

    return jsonify({"ok": True, "message": "Account created. You can sign in now."})


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
        return jsonify({"error": "This account is not active yet."}), 403
    session["user_id"] = user["id"]
    return jsonify({"ok": True, "user": public_user(user)})


@app.route("/api/password-reset/request", methods=["POST"])
def api_password_reset_request():
    data = request.get_json(force=True)
    email = normalize_email(data.get("email"))
    generic_message = "If that account exists, a reset code has been created."
    if not email:
        return jsonify({"error": "Enter the email address for the account."}), 400

    with get_db() as db:
        user = row_to_dict(
            db.execute(
                "SELECT id, disabled FROM users WHERE email = ?",
                (email,),
            ).fetchone()
        )
        db.execute(
            "DELETE FROM password_reset_codes WHERE used_at != '' OR expires_at <= ?",
            (now_iso(),),
        )
        if not user or user["disabled"]:
            db.commit()
            return jsonify({"ok": True, "message": generic_message})

        code = f"{secrets.randbelow(1000000):06d}"
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(timespec="seconds")
        db.execute(
            """
            INSERT INTO password_reset_codes (user_id, code_hash, expires_at, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (user["id"], generate_password_hash(code), expires_at, now_iso()),
        )
        db.commit()

    return jsonify(
        {
            "ok": True,
            "message": "Prototype reset code created. Use it within 15 minutes.",
            "reset_code": code,
        }
    )


@app.route("/api/password-reset/confirm", methods=["POST"])
def api_password_reset_confirm():
    data = request.get_json(force=True)
    email = normalize_email(data.get("email"))
    code = clean_text(data.get("code"), 20)
    new_password = data.get("new_password") or ""

    if not email or not code or len(new_password) < 8:
        return jsonify({"error": "Enter your email, reset code, and a new password with at least 8 characters."}), 400

    with get_db() as db:
        user = row_to_dict(
            db.execute(
                "SELECT id FROM users WHERE email = ? AND disabled = 0",
                (email,),
            ).fetchone()
        )
        if not user:
            return jsonify({"error": "Reset code is invalid or expired."}), 400

        rows = db.execute(
            """
            SELECT id, code_hash
            FROM password_reset_codes
            WHERE user_id = ? AND used_at = '' AND expires_at > ?
            ORDER BY created_at DESC
            LIMIT 5
            """,
            (user["id"], now_iso()),
        ).fetchall()
        matched = None
        for row in rows:
            if check_password_hash(row["code_hash"], code):
                matched = row
                break
        if not matched:
            return jsonify({"error": "Reset code is invalid or expired."}), 400

        db.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (generate_password_hash(new_password), user["id"]),
        )
        db.execute(
            "UPDATE password_reset_codes SET used_at = ? WHERE id = ?",
            (now_iso(), matched["id"]),
        )
        db.commit()

    session.clear()
    return jsonify({"ok": True, "message": "Password reset. You can sign in with the new password."})


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
                SELECT p.*, u.name AS author_name,
                       EXISTS(SELECT 1 FROM inbox_saves s WHERE s.post_id = p.id AND s.user_id = ?) AS saved
                FROM inbox_posts p
                JOIN users u ON u.id = p.author_id
                WHERE p.deleted_at = ''
                ORDER BY p.pinned DESC, p.created_at DESC
                LIMIT 5
                """,
                (user["id"],),
            )
        ]
        recent_assignments = [
            with_file_links(row_to_dict(row), "assignments")
            for row in db.execute(
                """
                SELECT a.*, u.name AS creator_name,
                       EXISTS(SELECT 1 FROM assignment_saves s WHERE s.assignment_id = a.id AND s.user_id = ?) AS saved,
                       (SELECT COUNT(*) FROM submissions sub WHERE sub.assignment_id = a.id) AS submission_count,
                       (SELECT COUNT(*) FROM submissions sub WHERE sub.assignment_id = a.id AND sub.student_id = ?) AS my_submission_count
                FROM assignments a
                JOIN users u ON u.id = a.created_by
                WHERE a.status != 'archived'
                ORDER BY a.pinned DESC,
                         CASE a.status WHEN 'open' THEN 0 ELSE 1 END,
                         CASE WHEN a.due_at = '' THEN 1 ELSE 0 END,
                         a.due_at ASC,
                         a.created_at DESC
                LIMIT 5
                """,
                (user["id"], user["id"]),
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
        saved_assignments = [
            with_file_links(row_to_dict(row), "assignments")
            for row in db.execute(
                """
                SELECT a.*, u.name AS creator_name, 1 AS saved,
                       (SELECT COUNT(*) FROM submissions sub WHERE sub.assignment_id = a.id) AS submission_count,
                       (SELECT COUNT(*) FROM submissions sub WHERE sub.assignment_id = a.id AND sub.student_id = ?) AS my_submission_count
                FROM assignment_saves s
                JOIN assignments a ON a.id = s.assignment_id
                JOIN users u ON u.id = a.created_by
                WHERE s.user_id = ? AND a.status != 'archived'
                ORDER BY s.created_at DESC
                LIMIT 5
                """,
                (user["id"], user["id"]),
            )
        ]
        saved_inbox = [
            with_file_links(row_to_dict(row), "inbox")
            for row in db.execute(
                """
                SELECT p.*, u.name AS author_name, u.role AS author_role, 1 AS saved
                FROM inbox_saves s
                JOIN inbox_posts p ON p.id = s.post_id
                JOIN users u ON u.id = p.author_id
                WHERE s.user_id = ? AND p.deleted_at = ''
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
            "recent_assignments": recent_assignments,
            "saved_resources": saved_resources,
            "saved_assignments": saved_assignments,
            "saved_inbox": saved_inbox,
            "unread_notifications": unread_notifications,
        }

        if user["role"] == "teacher":
            payload["recent_users"] = [
                row_to_dict(row)
                for row in db.execute(
                    "SELECT id, name, email, role, created_at FROM users ORDER BY created_at DESC LIMIT 6"
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
                    SELECT s.*, u.name AS student_name, a.title AS assignment_title,
                           (SELECT COUNT(*) FROM submission_comments c WHERE c.submission_id = s.id) AS comment_count
                    FROM submissions s
                    JOIN users u ON u.id = s.student_id
                    LEFT JOIN assignments a ON a.id = s.assignment_id
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
                    SELECT s.*, u.name AS student_name, a.title AS assignment_title,
                           (SELECT COUNT(*) FROM submission_comments c WHERE c.submission_id = s.id) AS comment_count
                    FROM submissions s
                    JOIN users u ON u.id = s.student_id
                    LEFT JOIN assignments a ON a.id = s.assignment_id
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


@app.route("/api/assignments", methods=["GET", "POST"])
@login_required
def api_assignments():
    user = current_user()
    if request.method == "POST":
        if user["role"] != "teacher":
            return jsonify({"error": "Only teachers can create assignments."}), 403
        meta = save_upload(request.files.get("file"), "assignments", user)
        now = now_iso()
        title = clean_text(request.form.get("title"), 180) or "Untitled assignment"
        assignment_id = execute_db(
            """
            INSERT INTO assignments
            (title, instructions, url, due_at, status, original_filename, stored_filename,
             mime_type, file_size, created_by, pinned, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'open', ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                title,
                clean_text(request.form.get("instructions"), 12000),
                clean_text(request.form.get("url"), 1000),
                clean_text(request.form.get("due_at"), 120),
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
        with get_db() as db:
            student_ids = [
                row["id"]
                for row in db.execute(
                    "SELECT id FROM users WHERE role = 'student' AND approved = 1 AND disabled = 0"
                )
            ]
        for student_id in student_ids:
            create_notification(student_id, f"New assignment posted: {title}.", "#assignments")
        return jsonify({"ok": True, "id": assignment_id})

    q = clean_text(request.args.get("q"), 200).lower()
    saved_only = request.args.get("saved") == "1"
    params: list = [user["id"], user["id"]]
    where = ["a.status != 'archived'"]
    if q:
        like = f"%{q}%"
        where.append("(LOWER(a.title) LIKE ? OR LOWER(a.instructions) LIKE ? OR LOWER(a.url) LIKE ?)")
        params.extend([like, like, like])
    if saved_only:
        where.append("EXISTS(SELECT 1 FROM assignment_saves ss WHERE ss.assignment_id = a.id AND ss.user_id = ?)")
        params.append(user["id"])
    where_sql = "WHERE " + " AND ".join(where)
    with get_db() as db:
        rows = db.execute(
            f"""
            SELECT a.*, u.name AS creator_name,
                   EXISTS(SELECT 1 FROM assignment_saves s WHERE s.assignment_id = a.id AND s.user_id = ?) AS saved,
                   (SELECT COUNT(*) FROM submissions sub WHERE sub.assignment_id = a.id) AS submission_count,
                   (SELECT COUNT(*) FROM submissions sub WHERE sub.assignment_id = a.id AND sub.student_id = ?) AS my_submission_count
            FROM assignments a
            JOIN users u ON u.id = a.created_by
            {where_sql}
            ORDER BY a.pinned DESC,
                     CASE a.status WHEN 'open' THEN 0 ELSE 1 END,
                     CASE WHEN a.due_at = '' THEN 1 ELSE 0 END,
                     a.due_at ASC,
                     a.created_at DESC
            """,
            tuple(params),
        ).fetchall()
    return jsonify({"assignments": [with_file_links(row_to_dict(row), "assignments") for row in rows]})


@app.route("/api/assignments/<int:assignment_id>", methods=["PATCH", "DELETE"])
@teacher_required
def api_assignment_item(assignment_id: int):
    with get_db() as db:
        assignment = row_to_dict(db.execute("SELECT * FROM assignments WHERE id = ?", (assignment_id,)).fetchone())
    if not assignment or assignment["status"] == "archived":
        return jsonify({"error": "Assignment not found."}), 404

    if request.method == "DELETE":
        execute_db(
            "UPDATE assignments SET status = 'archived', updated_at = ? WHERE id = ?",
            (now_iso(), assignment_id),
        )
        return jsonify({"ok": True})

    data = request.get_json(force=True)
    status = clean_text(data.get("status", assignment["status"]), 40)
    if status not in {"open", "closed", "archived"}:
        return jsonify({"error": "Assignment status must be open, closed, or archived."}), 400
    execute_db(
        """
        UPDATE assignments
        SET title = ?, instructions = ?, url = ?, due_at = ?, status = ?, pinned = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            clean_text(data.get("title", assignment["title"]), 180) or assignment["title"],
            clean_text(data.get("instructions", assignment["instructions"]), 12000),
            clean_text(data.get("url", assignment["url"]), 1000),
            clean_text(data.get("due_at", assignment["due_at"]), 120),
            status,
            1 if data.get("pinned", assignment["pinned"]) else 0,
            now_iso(),
            assignment_id,
        ),
    )
    return jsonify({"ok": True})


@app.route("/api/assignments/<int:assignment_id>/save", methods=["POST", "DELETE"])
@login_required
def api_assignment_save(assignment_id: int):
    user = current_user()
    with get_db() as db:
        assignment = row_to_dict(
            db.execute("SELECT id FROM assignments WHERE id = ? AND status != 'archived'", (assignment_id,)).fetchone()
        )
    if not assignment:
        return jsonify({"error": "Assignment not found."}), 404
    if request.method == "POST":
        try:
            execute_db(
                "INSERT INTO assignment_saves (user_id, assignment_id, created_at) VALUES (?, ?, ?)",
                (user["id"], assignment_id, now_iso()),
            )
        except sqlite3.IntegrityError:
            pass
    else:
        execute_db("DELETE FROM assignment_saves WHERE user_id = ? AND assignment_id = ?", (user["id"], assignment_id))
    return jsonify({"ok": True})


@app.route("/api/resources", methods=["GET", "POST"])
@login_required
def api_resources():
    user = current_user()
    if request.method == "POST":
        bucket = "resources"
        meta = save_upload(request.files.get("file"), bucket, user)
        now = now_iso()
        title = clean_text(request.form.get("title"), 180) or "Untitled resource"
        kind = clean_text(request.form.get("kind"), 40) or "resource"
        description = clean_text(request.form.get("description"), 1200)
        body = clean_text(request.form.get("body"), 12000)
        url = clean_text(request.form.get("url"), 1000)
        tags = clean_text(request.form.get("tags"), 500)

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
                1 if user["role"] == "teacher" and request.form.get("pinned") == "true" else 0,
                now,
                now,
            ),
        )
        with get_db() as db:
            recipient_ids = [
                row["id"]
                for row in db.execute(
                    "SELECT id FROM users WHERE id != ? AND approved = 1 AND disabled = 0",
                    (user["id"],),
                )
            ]
        for recipient_id in recipient_ids:
            create_notification(recipient_id, f"New shared resource: {title}.", "#resources")
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

    saved_only = request.args.get("saved") == "1"
    where = "WHERE p.deleted_at = ''"
    params: list = [user["id"]]
    if saved_only:
        where += " AND EXISTS(SELECT 1 FROM inbox_saves ss WHERE ss.post_id = p.id AND ss.user_id = ?)"
        params.append(user["id"])

    with get_db() as db:
        posts = []
        rows = db.execute(
            f"""
            SELECT p.*, u.name AS author_name, u.role AS author_role,
                   EXISTS(SELECT 1 FROM inbox_saves s WHERE s.post_id = p.id AND s.user_id = ?) AS saved
            FROM inbox_posts p
            JOIN users u ON u.id = p.author_id
            {where}
            ORDER BY p.pinned DESC, p.created_at DESC
            """,
            tuple(params),
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


@app.route("/api/inbox/<int:post_id>/save", methods=["POST", "DELETE"])
@login_required
def api_inbox_save(post_id: int):
    user = current_user()
    with get_db() as db:
        post = row_to_dict(
            db.execute("SELECT id FROM inbox_posts WHERE id = ? AND deleted_at = ''", (post_id,)).fetchone()
        )
    if not post:
        return jsonify({"error": "Inbox post not found."}), 404
    if request.method == "POST":
        try:
            execute_db(
                "INSERT INTO inbox_saves (user_id, post_id, created_at) VALUES (?, ?, ?)",
                (user["id"], post_id, now_iso()),
            )
        except sqlite3.IntegrityError:
            pass
    else:
        execute_db("DELETE FROM inbox_saves WHERE user_id = ? AND post_id = ?", (user["id"], post_id))
    return jsonify({"ok": True})


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
        try:
            assignment_id = int(request.form.get("assignment_id") or 0)
        except ValueError:
            return jsonify({"error": "Choose a valid assignment."}), 400
        visibility = clean_text(request.form.get("visibility"), 20)
        visibility = "class" if visibility == "class" else "private"
        assignment_title = ""
        if assignment_id:
            with get_db() as db:
                assignment = row_to_dict(
                    db.execute(
                        "SELECT id, title, status FROM assignments WHERE id = ? AND status != 'archived'",
                        (assignment_id,),
                    ).fetchone()
                )
            if not assignment:
                return jsonify({"error": "Assignment not found."}), 404
            if assignment["status"] != "open":
                return jsonify({"error": "This assignment is closed."}), 400
            assignment_title = assignment["title"]
        meta = save_upload(request.files.get("file"), "submissions", user)
        now = now_iso()
        submission_id = execute_db(
            """
            INSERT INTO submissions
            (assignment_id, visibility, title, description, text_content, url, original_filename, stored_filename, mime_type,
             file_size, student_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                assignment_id or None,
                visibility,
                clean_text(request.form.get("title"), 180) or assignment_title or "Untitled submission",
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
        with get_db() as db:
            teacher_ids = [
                row["id"]
                for row in db.execute(
                    "SELECT id FROM users WHERE role = 'teacher' AND approved = 1 AND disabled = 0"
                )
            ]
        for teacher_id in teacher_ids:
            create_notification(teacher_id, f"New submission: {clean_text(request.form.get('title'), 180) or assignment_title or 'Untitled submission'}.", "#submissions")
        return jsonify({"ok": True, "id": submission_id})

    where = ""
    params: tuple = ()
    if user["role"] != "teacher":
        where = "WHERE s.student_id = ? OR s.visibility = 'class'"
        params = (user["id"],)
    with get_db() as db:
        submissions = [
            with_file_links(row_to_dict(row), "submissions")
            for row in db.execute(
                f"""
                SELECT s.*, u.name AS student_name, a.title AS assignment_title,
                       (SELECT COUNT(*) FROM submission_comments c WHERE c.submission_id = s.id) AS comment_count
                FROM submissions s
                JOIN users u ON u.id = s.student_id
                LEFT JOIN assignments a ON a.id = s.assignment_id
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
        if item.get("visibility") != "class" and user["role"] != "teacher":
            return jsonify({"error": "Only teachers can comment on private submissions."}), 403
        data = request.get_json(force=True)
        body = clean_text(data.get("body"), 4000)
        if not body:
            return jsonify({"error": "Comment cannot be blank."}), 400
        execute_db(
            "INSERT INTO submission_comments (submission_id, teacher_id, author_id, body, created_at) VALUES (?, ?, ?, ?, ?)",
            (submission_id, user["id"], user["id"], body, now_iso()),
        )
        execute_db("UPDATE submissions SET updated_at = ? WHERE id = ?", (now_iso(), submission_id))
        if user["id"] != item["student_id"]:
            create_notification(item["student_id"], f"New comment on {item['title']}.", "#submissions")
        return jsonify({"ok": True})

    with get_db() as db:
        comments = [
            row_to_dict(row)
            for row in db.execute(
                """
                SELECT c.*, u.name AS teacher_name, u.name AS author_name, u.role AS author_role
                FROM submission_comments c
                JOIN users u ON u.id = COALESCE(c.author_id, c.teacher_id)
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


@app.route("/api/supabase/status")
def api_supabase_status():
    status = SUPABASE_CONFIG.public_status()
    status["storage"] = SUPABASE_CLIENT.storage_status()
    status["database_mode"] = "postgres" if os.getenv("DATABASE_URL") else "sqlite"
    status["database_note"] = "Supabase PostgreSQL database is connected and active in the aarav schema." if os.getenv("DATABASE_URL") else "Supabase database needs a DB password or service role key before migration."
    return jsonify(status)


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
        "assignments": "assignments",
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
    if bucket == "submissions" and item.get("visibility") != "class" and user["role"] != "teacher" and item["student_id"] != user["id"]:
        abort(403)
    if bucket == "inbox" and item.get("deleted_at"):
        abort(404)

    path = UPLOAD_DIR / bucket / item["stored_filename"]
    if not path.exists():
        if SUPABASE_CONFIG.configured:
            slug = SUPABASE_CONFIG.app_slugs[0] if SUPABASE_CONFIG.app_slugs else "aarav-genwise-aiml-classroom"
            supabase_url = f"{SUPABASE_CONFIG.url}/storage/v1/object/public/{SUPABASE_CONFIG.storage_bucket}/{slug}/{bucket}/{item['stored_filename']}"
            return redirect(supabase_url)
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
    return jsonify(
        {
            "ok": True,
            "app": "GenWise AI/ML Classroom",
            "supabase_configured": SUPABASE_CONFIG.configured,
            "database_mode": "sqlite",
        }
    )


init_db()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "8777")), debug=False)
