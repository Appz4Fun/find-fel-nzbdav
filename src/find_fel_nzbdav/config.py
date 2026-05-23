from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


REQUIRED_ENV_KEYS = (
    "NZB_DAV_URL",
    "NZB_DAV_API_KEY",
    "HYDRA_URL",
    "HYDRA_API_KEY",
)


@dataclass(frozen=True)
class Config:
    nzbdav_url: str
    nzbdav_api_key: str
    hydra_url: str
    hydra_api_key: str
    webdav_url: str
    webdav_user: str | None = None
    webdav_pass: str | None = None
    max_candidates: int = 3
    poll_interval: float = 5.0
    timeout: float = 1800.0

    @classmethod
    def from_env_file(cls, path: str | Path) -> "Config":
        values = parse_env_file(Path(path))
        missing = [key for key in REQUIRED_ENV_KEYS if not values.get(key)]
        if missing:
            raise ValueError(f"Missing required env key(s): {', '.join(missing)}")

        nzbdav_url = normalize_url(values["NZB_DAV_URL"])
        hydra_url = normalize_url(values["HYDRA_URL"])
        webdav_url = normalize_url(values.get("WEBDAV_URL") or nzbdav_url)

        return cls(
            nzbdav_url=nzbdav_url,
            nzbdav_api_key=values["NZB_DAV_API_KEY"],
            hydra_url=hydra_url,
            hydra_api_key=values["HYDRA_API_KEY"],
            webdav_url=webdav_url,
            webdav_user=values.get("WEBDAV_USER") or None,
            webdav_pass=values.get("WEBDAV_PASS") or None,
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
