from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol
from urllib.parse import urlencode


class JsonHttpClient(Protocol):
    def get_json(self, url: str, timeout: float = 30) -> Any: ...
    def post_multipart_json(
        self,
        url: str,
        *,
        field_name: str,
        filename: str,
        data: bytes,
        timeout: float = 30,
    ) -> Any: ...


@dataclass(frozen=True)
class NZBDavJob:
    nzo_id: str
    status: str
    name: str | None = None
    storage: str | None = None
    fail_message: str | None = None
    raw: dict[str, Any] | None = None


class NZBDavJobFailed(RuntimeError):
    def __init__(
        self,
        nzo_id: str,
        status: str,
        fail_message: str | None = None,
    ) -> None:
        self.nzo_id = nzo_id
        self.status = status
        self.fail_message = fail_message
        message = f"NZBDAV job {nzo_id} reached terminal status {status}"
        if fail_message:
            message = f"{message}: {fail_message}"
        super().__init__(message)


TERMINAL_SUCCESS_STATUSES = {"completed"}
TERMINAL_FAILURE_STATUSES = {
    "failed",
    "deleted",
    "aborted",
    "repair failed",
    "unpacking failed",
}


class NZBDavClient:
    def __init__(self, http: JsonHttpClient, base_url: str, api_key: str) -> None:
        self.http = http
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def submit(self, nzb_url: str, name: str, *, timeout: float = 300) -> str:
        response = self.http.get_json(
            self._api_url(
                {
                    "mode": "addurl",
                    "name": nzb_url,
                    "nzbname": name,
                    "output": "json",
                }
            ),
            timeout=timeout,
        )
        nzo_id = _first_nzo_id(response)
        if response.get("status") is not True or not nzo_id:
            raise RuntimeError(f"NZBDAV submit failed: {response!r}")
        return nzo_id

    def submit_bytes(self, nzb_data: bytes, name: str, *, timeout: float = 300) -> str:
        filename = name if name.endswith(".nzb") else f"{name}.nzb"
        response = self.http.post_multipart_json(
            self._api_url(
                {
                    "mode": "addfile",
                    "nzbname": name,
                    "output": "json",
                }
            ),
            field_name="nzbfile",
            filename=filename,
            data=nzb_data,
            timeout=timeout,
        )
        nzo_id = _first_nzo_id(response)
        if response.get("status") is not True or not nzo_id:
            raise RuntimeError(f"NZBDAV submit failed: {response!r}")
        return nzo_id

    def queue_status(self, nzo_id: str, *, timeout: float = 10) -> NZBDavJob | None:
        response = self.http.get_json(
            self._api_url({"mode": "queue", "output": "json"}),
            timeout=timeout,
        )
        return _find_job(response.get("queue", {}).get("slots", []), nzo_id)

    def history(self, nzo_id: str, *, timeout: float = 10) -> NZBDavJob | None:
        response = self.http.get_json(
            self._api_url({"mode": "history", "output": "json"}),
            timeout=timeout,
        )
        return _find_job(response.get("history", {}).get("slots", []), nzo_id)

    def _api_url(self, params: dict[str, str]) -> str:
        query = urlencode({**params, "apikey": self.api_key})
        return f"{self.base_url}/api?{query}"


def wait_for_terminal_job(
    client: NZBDavClient,
    nzo_id: str,
    *,
    poll_interval: float = 5,
    timeout: float = 1800,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> NZBDavJob:
    deadline = monotonic() + timeout
    while True:
        queue_job = client.queue_status(nzo_id)
        if queue_job is not None:
            status = queue_job.status.strip().lower()
            if status in TERMINAL_FAILURE_STATUSES:
                raise NZBDavJobFailed(
                    nzo_id,
                    queue_job.status,
                    getattr(queue_job, "fail_message", None),
                )
        else:
            history_job = client.history(nzo_id)
            if history_job is not None:
                status = history_job.status.strip().lower()
                if status in TERMINAL_SUCCESS_STATUSES:
                    return history_job
                if status in TERMINAL_FAILURE_STATUSES:
                    raise NZBDavJobFailed(
                        nzo_id,
                        history_job.status,
                        getattr(history_job, "fail_message", None),
                    )

        if monotonic() >= deadline:
            raise TimeoutError(f"Timed out waiting for NZBDAV job {nzo_id}")
        sleep(poll_interval)


def storage_to_webdav_path(storage: str) -> str:
    normalized = "/" + storage.strip("/")
    if normalized == "/":
        return "/content/"

    if normalized.startswith("/content/") or normalized == "/content":
        return _with_trailing_slash(normalized)

    for prefix in (
        "/mnt/nzbdav/completed-symlinks/",
        "/mnt/data/completed-symlinks/",
    ):
        if normalized.startswith(prefix):
            suffix = normalized.removeprefix(prefix)
            return _with_trailing_slash(f"/content/{suffix}")

    parts = [part for part in normalized.split("/") if part]
    if len(parts) >= 2:
        return _with_trailing_slash(f"/content/{parts[-2]}/{parts[-1]}")
    if parts:
        return _with_trailing_slash(f"/content/{parts[-1]}")
    return "/content/"


def _first_nzo_id(response: dict[str, Any]) -> str | None:
    nzo_ids = response.get("nzo_ids")
    if isinstance(nzo_ids, list) and nzo_ids:
        return str(nzo_ids[0])
    nzo_id = response.get("nzo_id")
    if nzo_id:
        return str(nzo_id)
    return None


def _find_job(slots: list[dict[str, Any]], nzo_id: str) -> NZBDavJob | None:
    for slot in slots:
        if str(slot.get("nzo_id", "")) == nzo_id:
            return NZBDavJob(
                nzo_id=nzo_id,
                status=str(slot.get("status", "")),
                name=slot.get("name") or slot.get("filename"),
                storage=slot.get("storage"),
                fail_message=_slot_fail_message(slot),
                raw=slot,
            )
    return None


def _slot_fail_message(slot: dict[str, Any]) -> str | None:
    for key in ("fail_message", "fail_msg", "failure", "error", "message"):
        value = slot.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _with_trailing_slash(path: str) -> str:
    return path if path.endswith("/") else f"{path}/"
