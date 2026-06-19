import json
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass(frozen=True)
class SupabaseConfig:
    url: str
    anon_key: str
    project_ref: str
    storage_bucket: str
    app_slugs: tuple[str, ...]

    @classmethod
    def from_env(cls) -> "SupabaseConfig":
        app_slugs = tuple(
            slug.strip()
            for slug in os.getenv("APP_SLUGS", "").replace(";", ",").split(",")
            if slug.strip()
        )
        return cls(
            url=os.getenv("SUPABASE_URL", "").strip().rstrip("/"),
            anon_key=os.getenv("SUPABASE_ANON_KEY", "").strip(),
            project_ref=os.getenv("SUPABASE_PROJECT_REF", "").strip(),
            storage_bucket=os.getenv("SUPABASE_STORAGE_BUCKET", "").strip(),
            app_slugs=app_slugs,
        )

    @property
    def configured(self) -> bool:
        return bool(self.url and self.anon_key and self.storage_bucket)

    def public_status(self) -> dict:
        return {
            "configured": self.configured,
            "url": self.url,
            "project_ref": self.project_ref,
            "storage_bucket": self.storage_bucket,
            "app_slugs": list(self.app_slugs),
        }


class SupabaseClient:
    def __init__(self, config: SupabaseConfig):
        self.config = config

    def _headers(self, content_type: str | None = None) -> dict:
        headers = {
            "apikey": self.config.anon_key,
            "Authorization": f"Bearer {self.config.anon_key}",
        }
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def _request_json(self, url: str) -> tuple[bool, dict | list | str]:
        request = Request(url, headers=self._headers())
        try:
            with urlopen(request, timeout=12) as response:
                body = response.read().decode("utf-8", "replace")
                return True, json.loads(body) if body else {}
        except HTTPError as error:
            body = error.read().decode("utf-8", "replace")
            return False, body or str(error)
        except (URLError, TimeoutError) as error:
            return False, str(error)

    def _post_json(self, url: str, payload: dict) -> tuple[bool, dict | list | str]:
        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=self._headers("application/json"),
            method="POST",
        )
        try:
            with urlopen(request, timeout=12) as response:
                body = response.read().decode("utf-8", "replace")
                return True, json.loads(body) if body else {}
        except HTTPError as error:
            body = error.read().decode("utf-8", "replace")
            return False, body or str(error)
        except (URLError, TimeoutError) as error:
            return False, str(error)

    def storage_status(self) -> dict:
        if not self.config.configured:
            return {"ok": False, "message": "Supabase is not fully configured."}
        bucket = quote(self.config.storage_bucket, safe="")
        ok, payload = self._request_json(f"{self.config.url}/storage/v1/bucket/{bucket}")
        if not ok:
            list_result = self.list_files("", limit=1)
            if list_result.get("ok"):
                return {
                    "ok": True,
                    "message": "Storage listing works. Bucket details are not readable with the anon key.",
                }
        return {"ok": ok, "message": payload}

    def public_url(self, object_name: str) -> str:
        bucket = quote(self.config.storage_bucket, safe="")
        safe_object = "/".join(quote(part, safe="") for part in object_name.split("/") if part)
        return f"{self.config.url}/storage/v1/object/public/{bucket}/{safe_object}"

    def list_files(self, prefix: str = "", limit: int = 100) -> dict:
        if not self.config.configured:
            return {"ok": False, "files": [], "message": "Supabase is not configured."}
        bucket = quote(self.config.storage_bucket, safe="")
        url = f"{self.config.url}/storage/v1/object/list/{bucket}"
        ok, payload = self._post_json(
            url,
            {
                "prefix": prefix.strip("/"),
                "limit": limit,
                "offset": 0,
                "sortBy": {"column": "updated_at", "order": "desc"},
            },
        )
        if not ok:
            return {"ok": False, "files": [], "message": payload}
        if not isinstance(payload, list):
            return {"ok": False, "files": [], "message": payload}
        return {"ok": True, "files": payload, "message": "ok"}

    def upload_file(self, path: Path, object_name: str, content_type: str) -> dict:
        if not self.config.configured:
            return {"ok": False, "skipped": True, "message": "Supabase is not configured."}
        safe_object = "/".join(quote(part, safe="") for part in object_name.split("/") if part)
        bucket = quote(self.config.storage_bucket, safe="")
        url = f"{self.config.url}/storage/v1/object/{bucket}/{safe_object}"
        headers = self._headers(content_type or "application/octet-stream")
        headers["x-upsert"] = "true"
        request = Request(url, data=path.read_bytes(), headers=headers, method="POST")
        try:
            with urlopen(request, timeout=30) as response:
                body = response.read().decode("utf-8", "replace")
                return {
                    "ok": 200 <= response.status < 300,
                    "object_name": object_name,
                    "message": body,
                }
        except HTTPError as error:
            body = error.read().decode("utf-8", "replace")
            return {"ok": False, "object_name": object_name, "message": body or str(error)}
        except (URLError, TimeoutError) as error:
            return {"ok": False, "object_name": object_name, "message": str(error)}
