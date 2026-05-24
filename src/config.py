from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


REQUIRED_ENV_KEYS = (
    "NZB_DAV_URL",
    "NZB_DAV_API_KEY",
    "HYDRA_URL",
    "HYDRA_API_KEY",
)


@dataclass(frozen=True)
class NZBDavEndpoint:
    url: str
    api_key: str
    webdav_url: str
    webdav_user: str | None = None
    webdav_pass: str | None = None


@dataclass(frozen=True)
class Config:
    endpoints: tuple[NZBDavEndpoint, ...]
    hydra_url: str
    hydra_api_key: str
    max_candidates: int = 3
    poll_interval: float = 5.0
    timeout: float = 1800.0

    @property
    def nzbdav_url(self) -> str:
        return self.endpoints[0].url

    @property
    def nzbdav_api_key(self) -> str:
        return self.endpoints[0].api_key

    @property
    def webdav_url(self) -> str:
        return self.endpoints[0].webdav_url

    @property
    def webdav_user(self) -> str | None:
        return self.endpoints[0].webdav_user

    @property
    def webdav_pass(self) -> str | None:
        return self.endpoints[0].webdav_pass

    @classmethod
    def from_env_file(
        cls,
        path: str | Path,
        *,
        pool_path: str | Path | None = None,
    ) -> "Config":
        values = parse_env_file(Path(path))
        missing = [key for key in REQUIRED_ENV_KEYS if not values.get(key)]
        if missing:
            raise ValueError(f"Missing required env key(s): {', '.join(missing)}")

        hydra_url = normalize_url(values["HYDRA_URL"])

        pool_obj = Path(pool_path) if pool_path is not None else None
        if pool_obj is not None and pool_obj.exists():
            endpoints = _load_pool(pool_obj)
        else:
            nzbdav_url = normalize_url(values["NZB_DAV_URL"])
            webdav_url = normalize_url(values.get("WEBDAV_URL") or nzbdav_url)
            endpoints = (
                NZBDavEndpoint(
                    url=nzbdav_url,
                    api_key=values["NZB_DAV_API_KEY"],
                    webdav_url=webdav_url,
                    webdav_user=values.get("WEBDAV_USER") or None,
                    webdav_pass=values.get("WEBDAV_PASS") or None,
                ),
            )

        return cls(
            endpoints=endpoints,
            hydra_url=hydra_url,
            hydra_api_key=values["HYDRA_API_KEY"],
            max_candidates=int(values.get("FEL_MAX_CANDIDATES", "3")),
            poll_interval=float(values.get("FEL_POLL_INTERVAL", "5")),
            timeout=float(values.get("FEL_TIMEOUT", "1800")),
        )


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


def normalize_url(url: str) -> str:
    return url.strip().rstrip("/")


def _load_pool(path: Path) -> tuple[NZBDavEndpoint, ...]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"pool file {path} must be a YAML list")
    endpoints: list[NZBDavEndpoint] = []
    for index, entry in enumerate(raw, start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"pool entry {index} must be a mapping")
        url = (entry.get("url") or "").strip()
        api_key = (entry.get("api_key") or "").strip()
        if not url:
            raise ValueError(f"pool entry {index} missing 'url'")
        if not api_key:
            raise ValueError(f"pool entry {index} missing 'api_key'")
        webdav_url = normalize_url(entry.get("webdav_url") or url)
        endpoints.append(
            NZBDavEndpoint(
                url=normalize_url(url),
                api_key=api_key,
                webdav_url=webdav_url,
                webdav_user=entry.get("webdav_user") or None,
                webdav_pass=entry.get("webdav_pass") or None,
            )
        )
    return tuple(endpoints)
