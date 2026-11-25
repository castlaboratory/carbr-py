"""The public functions: catalogue, municipalities and properties."""

from __future__ import annotations

import json
import re
import unicodedata
import warnings
from typing import Iterable, Sequence

import duckdb
import pandas as pd

from . import _client, _msg
from .cite import citation

COLUMNS = [
    "property_code", "status_code", "status", "condition", "property_type_code",
    "property_type", "created_at", "area_ha", "fiscal_modules", "size_class", "state",
    "municipality", "municipality_code", "registration_state", "lon", "lat",
    "geometry_valid", "xmin", "ymin", "xmax", "ymax", "geometry",
]
_STATUS = ("active", "pending", "suspended", "cancelled")
_SIZE = ("small", "medium", "large")
_TYPE = ("rural_property", "settlement", "traditional_community")
_CODE = re.compile(r"^[A-Z]{2}-[0-9]{7}-[0-9A-F]{32}$")
_CRS = "EPSG:4674"


def _as_list(x) -> list:
    if x is None:
        return []
    return [x] if isinstance(x, (str, int)) else list(x)


def _choices(value, allowed: Sequence[str], arg: str) -> list[str]:
    values = _as_list(value)
    bad = [v for v in values if v not in allowed]
    if bad:
        raise ValueError(f"`{arg}` must be one of {', '.join(allowed)}; got {bad!r}.")
    return values


def _fold(text: str) -> str:
    """Lower case, no accents, single spaces: how municipality names are matched."""
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z0-9 ]", "", text.lower()).split())


def _states(state, cat: dict) -> list[str]:
    available = list(cat["states"])
    if state is None:
        return available
    states = [str(s).upper() for s in _as_list(state)]
    missing = [s for s in states if s not in available]
    if missing:
        raise ValueError(
            f"State(s) {missing!r} not in this publication. Available: {available!r}."
        )
    return states


def _relation(cat: dict, states: list[str]) -> duckdb.DuckDBPyRelation:
    return _client.con().read_parquet(_client.property_files(cat, states))


def _collect(rel: duckdb.DuckDBPyRelation, where: list[str], params: list, geometry: bool):
    cols = "*" if geometry else "* EXCLUDE (geometry)"
    sql = f"SELECT {cols} FROM rel" + (" WHERE " + " AND ".join(where) if where else "")
    try:
        return _client.con().execute(sql, params).df()
    except duckdb.Error as err:
        warnings.warn(
            f"The CAR publication could not be read; returning an empty result. {err}",
            _client.CarWarning,
            stacklevel=3,
        )
        return None


def _finish(out: pd.DataFrame | None, geometry: bool):
    """DataFrame, or GeoDataFrame when geometry was asked for and geopandas is there."""
    if out is None:
        out = pd.DataFrame(columns=COLUMNS)
    if not geometry:
        return out.drop(columns="geometry", errors="ignore")
    try:
        import geopandas as gpd
    except ImportError:
        _msg.step("Install carbr[geo] to get a GeoDataFrame; returning WKB.")
        return out
    geom = gpd.GeoSeries.from_wkb(out["geometry"].map(lambda g: None if g is None else bytes(g)),
                                  crs=_CRS)
    return gpd.GeoDataFrame(out.drop(columns="geometry"), geometry=geom, crs=_CRS)


def car_catalog(refresh: bool = False) -> pd.DataFrame:
    """O que está publicado: uma linha por UF.

    A versão, a origem e a citação ficam em ``df.attrs`` (``version``,
    ``source``, ``citation``). Zero linhas (com aviso) se a publicação não
    responder.

    Parameters
    ----------
    refresh
        Se ``True``, ignora o catálogo em cache (válido por 6 horas).
    """
    columns = ["state", "properties", "municipalities", "invalid_geometries",
               "null_geometries", "registered_in_other_state"]
    cat = _client.catalog_json(refresh)
    if cat is None:
        return pd.DataFrame(columns=columns)
    rows = [
        {
            "state": uf,
            "properties": s.get("properties"),
            "municipalities": s.get("municipalities"),
            **{k: s.get("quality", {}).get(k) for k in columns[3:]},
        }
        for uf, s in cat["states"].items()
    ]
    out = pd.DataFrame(rows, columns=columns)
    out.attrs.update(version=cat["version"], source=cat.get("source"),
                     citation=citation(cat["version"]))
    return out


def car_dictionary() -> pd.DataFrame:
    """Dicionário de dados: coluna publicada, nome no Sicar e descrição."""
    columns = ["column", "sicar_name", "description"]
    raw = _client.fetch("dictionary.json")
    if raw is None:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(json.loads(raw), columns=columns)


def car_municipalities(state: str | Iterable[str] | None = None) -> pd.DataFrame:
    """Resumo por município.

    Imóveis, pequenos imóveis (até 4 módulos fiscais), área declarada,
    contagem por situação, geometrias inválidas e retângulo envolvente.

    Parameters
    ----------
    state
        Sigla de uma ou mais UFs; ``None`` traz todas as publicadas.
    """
    columns = ["state", "municipality_code", "municipality", "properties", "small_properties",
               "area_ha", "active", "pending", "suspended", "cancelled", "invalid_geometries",
               "xmin", "ymin", "xmax", "ymax"]
    cat = _client.catalog_json()
    if cat is None:
        return pd.DataFrame(columns=columns)
    files = [_client.cached_file(cat, f"municipalities/state={s}.parquet")
             for s in _states(state, cat)]
    if any(f is None for f in files):
        return pd.DataFrame(columns=columns)
    rel = _client.con().read_parquet([str(f) for f in files])  # noqa: F841
    return _client.con().execute("SELECT * FROM rel ORDER BY municipality_code").df()


_DIMS = ("state", "status", "size_class", "property_type", "condition", "created_year")


def car_summary(by: str | Iterable[str] | None = "state",
                state: str | Iterable[str] | None = None) -> pd.DataFrame:
    """Resumo pré-calculado.

    Contagem de imóveis e área declarada por qualquer combinação de UF,
    situação, porte, tipo, etapa da análise e ano de criação do cadastro. Lê
    tabelas pequenas, calculadas na publicação e guardadas em cache: responde
    em segundos mesmo para o país inteiro, sem ler os imóveis.

    Parameters
    ----------
    by
        Dimensões do resumo, uma ou mais de ``"state"``, ``"status"``,
        ``"size_class"``, ``"property_type"``, ``"condition"`` e
        ``"created_year"``. ``None`` devolve uma linha só, com o total.
    state
        Sigla de uma ou mais UFs; ``None`` traz todas as publicadas.

    Returns
    -------
    pandas.DataFrame
        As colunas de ``by``, ``properties`` (número de imóveis) e ``area_ha``
        (área declarada, em hectares).
    """
    by = _choices(by, _DIMS, "by")
    empty = pd.DataFrame(columns=[*by, "properties", "area_ha"])
    cat = _client.catalog_json()
    if cat is None:
        return empty
    paths = [f"summary/state={s}.parquet" for s in _states(state, cat)]
    if not set(paths) <= {f["path"] for f in cat["files"]}:
        # A catalogue cached before the summary was published.
        cat = _client.catalog_json(refresh=True)
        if cat is None:
            return empty
    files = [_client.cached_file(cat, p) for p in paths]
    if any(f is None for f in files):
        return empty
    rel = _client.con().read_parquet([str(f) for f in files])  # noqa: F841
    cols = ", ".join([*by, "sum(properties)::BIGINT AS properties", "sum(area_ha) AS area_ha"])
    group = f" GROUP BY {', '.join(by)} ORDER BY {', '.join(by)}" if by else ""
    return _client.con().execute(f"SELECT {cols} FROM rel{group}").df()


def _municipality_codes(municipality, states: list[str]) -> list[int]:
    values = _as_list(municipality)
    if all(isinstance(v, int) or re.fullmatch(r"[0-9]{7}", str(v)) for v in values):
        return [int(v) for v in values]
    known = car_municipalities(states)
    folded = known["municipality"].map(_fold)
    wanted = [_fold(v) for v in values]
    unknown = [v for v, w in zip(values, wanted) if w not in set(folded)]
    if unknown:
        raise ValueError(
            f"Municipalities not found in {', '.join(states)}: {unknown!r}. "
            "See car_municipalities(), or pass the 7-digit IBGE code."
        )
    return [int(c) for c in known.loc[folded.isin(wanted), "municipality_code"]]


def car_tbl(state: str | Iterable[str] | None = None) -> duckdb.DuckDBPyRelation | None:
    """Relação preguiçosa do DuckDB sobre os imóveis.

    Para consultas que as outras funções não cobrem. Nada é lido até
    ``.df()``; ``filter``, ``project`` e ``aggregate`` viram leitura parcial
    do arquivo remoto. A geometria vem em WKB.
    """
    cat = _client.catalog_json()
    if cat is None:
        return None
    return _relation(cat, _states(state, cat))


def car_properties(
    state: str | Iterable[str],
    municipality=None,
    status=None,
    size_class=None,
    property_type=None,
    bbox: Sequence[float] | None = None,
    geometry: bool = True,
):
    """Imóveis rurais declarados no CAR.

    Os filtros são aplicados antes da leitura: só os trechos do arquivo que
    os atendem são transferidos.

    Parameters
    ----------
    state
        Sigla de uma ou mais UFs.
    municipality
        Nomes ou códigos IBGE (7 dígitos) de municípios.
    status
        ``"active"``, ``"pending"``, ``"suspended"``, ``"cancelled"``.
    size_class
        ``"small"`` (até 4 módulos fiscais), ``"medium"`` (acima de 4 até 15), ``"large"``.
    property_type
        ``"rural_property"``, ``"settlement"``, ``"traditional_community"``.
    bbox
        ``(xmin, ymin, xmax, ymax)`` em graus (SIRGAS 2000).
    geometry
        Se ``True``, devolve o perímetro: GeoDataFrame com ``carbr[geo]``
        instalado, senão WKB. ``False`` não transfere a geometria.

    Returns
    -------
    pandas.DataFrame ou geopandas.GeoDataFrame
        Uma linha por imóvel; as colunas estão em :func:`car_dictionary`.
    """
    status = _choices(status, _STATUS, "status")
    size_class = _choices(size_class, _SIZE, "size_class")
    property_type = _choices(property_type, _TYPE, "property_type")
    if bbox is not None and len(bbox) != 4:
        raise ValueError("`bbox` must be (xmin, ymin, xmax, ymax).")
    cat = _client.catalog_json()
    if cat is None:
        return _finish(None, geometry)
    states = _states(state, cat)
    where, params = [], []

    def isin(column: str, values: list) -> None:
        where.append(f"{column} IN ({', '.join('?' * len(values))})")
        params.extend(values)

    if municipality is not None:
        isin("municipality_code", _municipality_codes(municipality, states))
    if status:
        isin("status", status)
    if size_class:
        isin("size_class", size_class)
    if property_type:
        isin("property_type", property_type)
    if bbox is not None:
        where.append("xmax >= ? AND ymax >= ? AND xmin <= ? AND ymin <= ?")
        params.extend(float(v) for v in bbox)
    rel = _relation(cat, states)
    return _finish(_collect(rel, where, params, geometry), geometry)


def car_property(code: str | Iterable[str], geometry: bool = True):
    """Um ou mais imóveis pelo código (``UF-0000000-identificador``)."""
    codes = [str(c).strip().upper() for c in _as_list(code)]
    bad = [c for c in codes if not _CODE.match(c)]
    if bad:
        raise ValueError(
            f"Not CAR property codes: {bad!r}. Expected 'UF-0000000-' followed by "
            "32 hexadecimal digits."
        )
    cat = _client.catalog_json()
    if cat is None:
        return _finish(None, geometry)
    rel = _relation(cat, list(cat["states"]))
    marks = ", ".join("?" * len(codes))
    # The code carries the municipality: that filter reads a few row groups.
    out = _collect(
        rel,
        [f"municipality_code IN ({marks})", f"property_code IN ({marks})"],
        [int(c[3:10]) for c in codes] + codes,
        geometry,
    )
    if out is None:
        return _finish(None, geometry)
    # A few properties sit in another municipality or state than the code says.
    left = [c for c in codes if c not in set(out["property_code"])]
    if left:
        more = _collect(rel, [f"property_code IN ({', '.join('?' * len(left))})"], left, geometry)
        if more is not None and len(more):
            out = pd.concat([out, more], ignore_index=True)
    return _finish(out, geometry)


def car_at(lon: float, lat: float, state=None, geometry: bool = True):
    """Imóveis que contêm um ponto.

    Responde "que imóveis estão declarados aqui?". O filtro pelo retângulo
    envolvente é feito na leitura remota e o teste exato, com o shapely
    (``carbr[geo]``). Sobreposições são comuns: pode vir mais de uma linha.
    """
    lon, lat = float(lon), float(lat)
    try:
        import geopandas  # noqa: F401
        from shapely.geometry import Point
    except ImportError as err:
        raise ImportError("car_at() needs geopandas: pip install 'carbr[geo]'.") from err
    cat = _client.catalog_json()
    if cat is None:
        return _finish(None, geometry)
    rel = _relation(cat, _states(state, cat))
    out = _collect(rel, ["xmin <= ? AND xmax >= ? AND ymin <= ? AND ymax >= ?"],
                   [lon, lon, lat, lat], True)
    out = _finish(out, True)
    out = out[out.geometry.intersects(Point(lon, lat))].reset_index(drop=True)
    if not geometry:
        return pd.DataFrame(out.drop(columns="geometry"))
    return out
