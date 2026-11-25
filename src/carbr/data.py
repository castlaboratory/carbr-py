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


_NOTES = {
    "invalid": "Texto fora do formato de um código do CAR.",
    "not_found": "Código não encontrado nesta publicação.",
}


def _stage(condition) -> str | None:
    """Etapa da análise a partir da situação informada pelo Sicar."""
    if not isinstance(condition, str):
        return None
    if condition.startswith("Cancelado"):
        return "cancelled"
    if condition == "Aguardando análise":
        return "waiting"
    if condition == "Em análise":
        return "analysing"
    if "aguardando atendimento a notificação" in condition:
        return "notified"
    if "após revisão" in condition:
        return "answered"
    return "done"


def _verdict(row) -> tuple[str, str]:
    status, stage = row["status"], row["stage"]
    if status == "cancelled" or stage == "cancelled":
        return "blocked", "Cadastro cancelado."
    if status == "suspended":
        return "blocked", "Cadastro suspenso."
    if stage == "notified":
        return "attention", "Analisado, com notificação sem resposta do declarante."
    if status == "pending":
        return "attention", "Cadastro pendente."
    if not isinstance(status, str):
        return "attention", "Situação não reconhecida."
    return "ok", "Cadastro ativo, sem notificação pendente."


def car_check(code: str | Iterable[str]) -> pd.DataFrame:
    """Verificar vários imóveis de uma vez.

    Para uma lista de códigos, diz o que consta de cada um na camada pública
    do CAR e resume em um resultado: a triagem que antecede, por exemplo, a
    análise de um pedido de crédito rural. Os códigos são agrupados por UF e
    município, de modo que uma lista grande lê poucos trechos de cada arquivo.

    O resultado (``check``) é uma classificação do pacote, não uma regra
    oficial:

    - ``"ok"``: cadastro ativo, sem notificação pendente;
    - ``"attention"``: cadastro pendente, ou analisado com notificação ainda
      sem resposta do declarante;
    - ``"blocked"``: cadastro cancelado ou suspenso;
    - ``"not_found"``: código que não está na publicação (pode ter sido
      cadastrado depois da última atualização);
    - ``"invalid"``: texto que não tem o formato de um código do CAR.

    A verificação diz só o que a camada pública traz. Não cobre embargos,
    sobreposição com terras indígenas ou unidades de conservação, nem
    substitui a consulta oficial ao Sicar.

    Parameters
    ----------
    code
        Códigos de imóvel no CAR (``UF-0000000-identificador``).

    Returns
    -------
    pandas.DataFrame
        Uma linha por código, na ordem dada: ``property_code``, ``check``,
        ``note`` (o motivo, em português), ``stage`` (``"waiting"``,
        ``"analysing"``, ``"notified"``, ``"answered"``, ``"done"`` ou
        ``"cancelled"``), ``status``, ``condition``, ``property_type``,
        ``size_class``, ``area_ha``, ``fiscal_modules``, ``state``,
        ``municipality`` e ``created_at``.
    """
    codes = list(dict.fromkeys(str(c).strip().upper() for c in _as_list(code) if str(c).strip()))
    columns = ["property_code", "status", "condition", "property_type", "size_class",
               "area_ha", "fiscal_modules", "state", "municipality", "created_at"]
    order = ["property_code", "check", "note", "stage", *columns[1:]]
    if not codes:
        return pd.DataFrame(columns=order)
    valid = [c for c in codes if _CODE.match(c)]
    parts = []
    cat = _client.catalog_json() if valid else None
    if cat is not None:
        for uf in dict.fromkeys(c[:2] for c in valid):
            if uf not in cat["states"]:
                continue
            wanted = [c for c in valid if c[:2] == uf]
            rel = _relation(cat, [uf]).project(", ".join([*columns, "municipality_code"]))
            marks = ", ".join("?" * len(wanted))
            towns = sorted({int(c[3:10]) for c in wanted})
            # The code carries the municipality: that filter reads a few row groups.
            part = _collect(rel, [f"municipality_code IN ({', '.join('?' * len(towns))})",
                                  f"property_code IN ({marks})"], [*towns, *wanted], True)
            if part is None:
                continue
            left = [c for c in wanted if c not in set(part["property_code"])]
            if left:
                # A few properties sit in another municipality than the code says.
                more = _collect(rel, [f"property_code IN ({', '.join('?' * len(left))})"], left, True)
                if more is not None and len(more):
                    part = pd.concat([part, more], ignore_index=True)
            parts.append(part[columns])
    found = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=columns)
    found["property_code"] = found["property_code"].astype(object)
    out = pd.DataFrame({"property_code": pd.Series(codes, dtype=object)}).merge(
        found, on="property_code", how="left")
    out["stage"] = out["condition"].map(_stage)
    checks, notes = [], []
    for _, row in out.iterrows():
        if not _CODE.match(row["property_code"]):
            verdict = ("invalid", _NOTES["invalid"])
        elif not isinstance(row["state"], str):
            verdict = ("not_found", _NOTES["not_found"])
        else:
            verdict = _verdict(row)
        checks.append(verdict[0])
        notes.append(verdict[1])
    out["check"], out["note"] = checks, notes
    return out[order]


_QUALITY = ["property_code", "municipality_code", "overlap_count", "overlap_share", "outside_share"]
_QUALITY_SUMMARY = ["state", "municipality_code", "municipality", "properties", "overlapping",
                    "overlapping_half", "overlap_ha", "outside_half", "outside_ha"]


def car_quality(state: str | Iterable[str], municipality=None) -> pd.DataFrame:
    """Indicadores de qualidade por imóvel.

    Dois sinais de inconsistência do cadastro, calculados na publicação para cada imóvel
    não cancelado:

    - ``overlap_count`` e ``overlap_share``: com quantos outros imóveis do estado ele
      divide área, e que parcela da área dele está sobreposta (a soma das interseções
      com cada vizinho, limitada a 1);
    - ``outside_share``: que parcela da área fica fora do município declarado, pela
      malha municipal do IBGE.

    Sobreposição não é sinônimo de disputa: inclui imóvel declarado duas vezes e lote
    dentro de assentamento. A comparação é só entre imóveis do mesmo estado.

    Parameters
    ----------
    state
        Sigla de uma ou mais UFs.
    municipality
        Nomes ou códigos IBGE (7 dígitos) de municípios; lê só os trechos deles.

    Returns
    -------
    pandas.DataFrame
        ``property_code``, ``municipality_code``, ``overlap_count``, ``overlap_share`` e
        ``outside_share``. Junte a :func:`car_properties` por ``property_code``.
    """
    cat = _client.catalog_json()
    if cat is None:
        return pd.DataFrame(columns=_QUALITY)
    states = _states(state, cat)
    files = _client.data_files(cat, "quality", states)
    if not files:
        cat = _client.catalog_json(refresh=True)
        files = _client.data_files(cat, "quality", states) if cat else []
    if not files:
        warnings.warn("This publication has no quality indicators; returning an empty result.",
                      _client.CarWarning, stacklevel=2)
        return pd.DataFrame(columns=_QUALITY)
    rel = _client.con().read_parquet(files)
    where, params = [], []
    if municipality is not None:
        codes = _municipality_codes(municipality, states)
        where.append(f"municipality_code IN ({', '.join('?' * len(codes))})")
        params.extend(codes)
    out = _collect(rel, where, params, True)
    return pd.DataFrame(columns=_QUALITY) if out is None else out[_QUALITY]


def car_quality_summary(state: str | Iterable[str] | None = None) -> pd.DataFrame:
    """Indicadores de qualidade por município.

    Para cada município: imóveis não cancelados (``properties``), quantos têm sobreposição
    acima de 1% (``overlapping``) e de 50% da área (``overlapping_half``), os hectares
    sobrepostos (``overlap_ha``, somando os dois lados de cada par), e quantos imóveis
    (``outside_half``) e hectares (``outside_ha``) ficam fora do município declarado.
    Arquivos pequenos, guardados em cache.

    Parameters
    ----------
    state
        Sigla de uma ou mais UFs; ``None`` traz todas as publicadas.
    """
    empty = pd.DataFrame(columns=_QUALITY_SUMMARY)
    cat = _client.catalog_json()
    if cat is None:
        return empty
    states = _states(state, cat)
    paths = [f"quality-municipalities/state={s}.parquet" for s in states]
    if not set(paths) <= {f["path"] for f in cat["files"]}:
        cat = _client.catalog_json(refresh=True)
        if cat is None or not set(paths) <= {f["path"] for f in cat["files"]}:
            warnings.warn("This publication has no quality indicators; returning an empty result.",
                          _client.CarWarning, stacklevel=2)
            return empty
    files = [_client.cached_file(cat, p) for p in paths]
    if any(f is None for f in files):
        return empty
    rel = _client.con().read_parquet([str(f) for f in files])  # noqa: F841
    out = _client.con().execute("SELECT * FROM rel ORDER BY municipality_code").df()
    names = car_municipalities(states)[["municipality_code", "municipality"]]
    return out.merge(names, on="municipality_code", how="left")[_QUALITY_SUMMARY]
