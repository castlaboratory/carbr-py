"""Where the publication lives, how small files are fetched and cached."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import warnings
from pathlib import Path
from urllib.parse import quote

import duckdb
import platformdirs
import requests

from . import _msg

_TIMEOUT = 60.0
_MAX_TRIES = 3
_CATALOG_MAX_AGE = 6 * 3600
DEFAULT_URL = "https://car.castlab.org/current"
_BASE_URL: str | None = None
_CON: duckdb.DuckDBPyConnection | None = None
_HTTPFS = False


class CarError(Exception):
    """Erro do carbr."""


class ConfigError(CarError):
    """Extensão do DuckDB indisponível."""


class IntegrityError(CarError):
    """Arquivo que não confere com o SHA-256 do catálogo."""


class CarWarning(UserWarning):
    """A publicação não respondeu; a função devolve um resultado vazio."""


def set_base_url(url: str | os.PathLike | None) -> None:
    """Define o endereço (URL ou pasta local) da publicação.

    Sem isso, vale a variável de ambiente ``CAR_URL`` e, na falta dela, o
    bucket público. ``None`` volta ao padrão.
    """
    global _BASE_URL
    _BASE_URL = None if url is None else str(url)


def set_timeout(seconds: float) -> None:
    """Tempo limite de cada requisição, em segundos (padrão 60)."""
    global _TIMEOUT
    _TIMEOUT = float(seconds)


def base_url() -> str:
    base = _BASE_URL or os.environ.get("CAR_URL") or DEFAULT_URL
    return base.rstrip("/") if is_remote(base) else str(Path(base).expanduser().resolve())


def is_remote(base: str) -> bool:
    return base.startswith(("http://", "https://"))


def cache_dir() -> Path:
    """Pasta de cache do carbr.

    Guarda o catálogo e o resumo municipal, uma pasta por versão. Os imóveis
    não são copiados: cada consulta lê do arquivo remoto só o que precisa.
    """
    return Path(os.environ.get("CAR_CACHE_DIR") or platformdirs.user_cache_dir("carbr"))


def clear_cache() -> Path:
    """Apaga o cache e devolve o caminho da pasta."""
    path = cache_dir()
    if path.exists():
        shutil.rmtree(path)
        _msg.success(f"Cleared carbr cache at {path}.")
    else:
        _msg.step(f"No carbr cache found at {path}.")
    return path


def _warn(reason: str) -> None:
    warnings.warn(
        f"The CAR publication could not be reached; returning an empty result. {reason}",
        CarWarning,
        stacklevel=4,
    )


def fetch(path: str) -> bytes | None:
    """A small file of the publication, or ``None`` (with a warning)."""
    base = base_url()
    if not is_remote(base):
        file = Path(base) / path
        if file.exists():
            return file.read_bytes()
        _warn(f"{file} does not exist.")
        return None
    url = f"{base}/{quote(path)}"
    reason = ""
    for attempt in range(1, _MAX_TRIES + 1):
        try:
            resp = requests.get(url, timeout=_TIMEOUT, headers={"User-Agent": "carbr Python package"})
            if resp.status_code == 200:
                return resp.content
            reason = f"HTTP {resp.status_code}"
            if resp.status_code not in (429, 500, 502, 503, 504):
                break
        except requests.RequestException as err:
            reason = str(err)
        if attempt < _MAX_TRIES:
            time.sleep(2**attempt)
    _warn(reason)
    return None


def _parse_catalog(raw: bytes) -> dict:
    cat = json.loads(raw)
    if "version" not in cat or "files" not in cat:
        raise CarError("Unexpected catalogue format (no version/files).")
    return cat


def catalog_json(refresh: bool = False) -> dict | None:
    """The published catalogue, from the disk cache when recent enough."""
    base = base_url()
    if not is_remote(base):
        raw = fetch("catalog.json")
        return None if raw is None else _parse_catalog(raw)
    path = cache_dir() / "catalog.json"
    age = time.time() - path.stat().st_mtime if path.exists() else float("inf")
    if not refresh and age < _CATALOG_MAX_AGE:
        return _parse_catalog(path.read_bytes())
    raw = fetch("catalog.json")
    if raw is None:
        if path.exists():
            _msg.step("Using the cached catalogue.")
            return _parse_catalog(path.read_bytes())
        return None
    cat = _parse_catalog(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return cat


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cached_file(cat: dict, path: str) -> Path | None:
    """Path to a verified local copy of a small catalogue file.

    The publication is updated in place. When a file no longer matches the
    SHA-256 of a catalogue read from the cache, the catalogue is read again
    and the file is checked against the fresh one.
    """

    def sha_of(cat: dict) -> str:
        entry = next((f for f in cat["files"] if f["path"] == path), None)
        if entry is None:
            raise CarError(f"{path} is not in the catalogue.")
        return entry["sha256"]

    sha256 = sha_of(cat)
    base = base_url()
    if not is_remote(base):
        return Path(base) / path
    dest = cache_dir() / cat["version"] / path
    if dest.exists() and _sha256(dest) == sha256:
        return dest
    raw = fetch(path)
    if raw is None:
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.write_bytes(raw)
    if _sha256(tmp) != sha256:
        fresh = catalog_json(refresh=True)
        if fresh is None or _sha256(tmp) != sha_of(fresh):
            tmp.unlink()
            raise IntegrityError(
                f"{path} does not match the SHA-256 in the catalogue. The publication "
                "may be in progress; try again in a few minutes."
            )
        cat = fresh
        dest = cache_dir() / cat["version"] / path
        dest.parent.mkdir(parents=True, exist_ok=True)
    tmp.replace(dest)
    # Files of other catalogue versions are superseded.
    for other in cache_dir().iterdir():
        if other.is_dir() and other.name != cat["version"]:
            shutil.rmtree(other)
    return dest


def con() -> duckdb.DuckDBPyConnection:
    """The package's DuckDB connection (in memory, created on first use)."""
    global _CON, _HTTPFS
    if _CON is None:
        _CON = duckdb.connect()
        _HTTPFS = False
    return _CON


def _need_httpfs() -> None:
    global _HTTPFS
    if _HTTPFS:
        return
    try:
        try:
            con().execute("LOAD httpfs")
        except duckdb.Error:
            con().execute("INSTALL httpfs")
            con().execute("LOAD httpfs")
    except duckdb.Error as err:
        raise ConfigError(
            "DuckDB's httpfs extension could not be loaded; it is downloaded once "
            "from the DuckDB extension repository."
        ) from err
    _HTTPFS = True


def property_files(cat: dict, states: list[str]) -> list[str]:
    """Addresses of the property files of the given states."""
    base = base_url()
    keep = [
        f["path"]
        for f in cat["files"]
        if f["path"].startswith("properties/state=") and f["path"][17:19] in states
    ]
    if is_remote(base):
        _need_httpfs()
        return [f"{base}/{quote(p)}" for p in keep]
    return [str(Path(base) / p) for p in keep]


def data_files(cat: dict, prefix: str, states: list[str]) -> list[str]:
    """Addresses of the per-state files `<prefix>/state=<UF>.parquet` that the catalogue lists."""
    base = base_url()
    start = f"{prefix}/state="
    keep = [f["path"] for f in cat["files"]
            if f["path"].startswith(start) and f["path"][len(start):len(start) + 2] in states]
    if is_remote(base):
        _need_httpfs()
        return [f"{base}/{quote(p)}" for p in keep]
    return [str(Path(base) / p) for p in keep]
