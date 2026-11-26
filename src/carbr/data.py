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


def _check_quality(uf: str, part: pd.DataFrame) -> pd.DataFrame:
    """Sobreposição com áreas protegidas dos imóveis de `part` (vazio se a publicação não traz)."""
    columns = ["property_code", "indigenous_share", "strict_protection_share", "sustainable_use_share",
               "indigenous_land", "conservation_unit", "conservation_category", "embargo_count", "embargo_share",
               "public_forest_share", "quilombola_share", "sigef_share"]
    if not len(part):
        return pd.DataFrame(columns=columns)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        quality = car_quality(uf, municipality=sorted({int(c) for c in part["municipality_code"]}))
    return quality[quality["property_code"].isin(part["property_code"])][columns]


_PROTECTED = ["indigenous_share", "strict_protection_share", "sustainable_use_share", "protected_area",
              "embargo_count", "embargo_share", "public_forest_share", "quilombola_share", "sigef_share"]
_SHARE_MIN = 0.01       # abaixo de 1% da área, a sobreposição é ruído de limite


def _percent(share: float) -> str:
    return "toda a área" if share >= 0.995 else f"{max(1, round(100 * share))}% da área"


def _protected(row, check: str, note: str) -> tuple[str, str, str | None]:
    """Acrescenta ao resultado a sobreposição com terra indígena e unidade de conservação."""
    def share(key):
        value = row.get(key)
        return float(value) if pd.notna(value) else 0.0

    ti, strict, sustainable = (share(k) for k in _PROTECTED[:3])        # as três parcelas de área
    unit, category = row.get("conservation_unit"), row.get("conservation_category")
    extra, names = [], []
    if ti >= _SHARE_MIN:
        extra.append(f"Sobrepõe terra indígena ({row.get('indigenous_land')}) em {_percent(ti)}.")
        names.append(row.get("indigenous_land"))
    if strict >= _SHARE_MIN:
        extra.append(f"Sobrepõe unidade de conservação de proteção integral ({unit}) em {_percent(strict)}.")
        names.append(unit)
    elif sustainable >= _SHARE_MIN:
        names.append(unit)
        if check != "blocked":
            extra.append(f"Fica em unidade de conservação de uso sustentável ({category}: {unit}), "
                         f"em {_percent(sustainable)}.")
    embargoes = int(row.get("embargo_count")) if pd.notna(row.get("embargo_count")) else 0
    if embargoes:
        covered = share("embargo_share")
        extra.append(("Há 1 embargo ambiental ativo do Ibama" if embargoes == 1
                      else f"Há {embargoes} embargos ambientais ativos do Ibama")
                     + (f", sobre {_percent(covered)}." if covered >= _SHARE_MIN else " no imóvel."))
    forest = share("public_forest_share")
    if forest >= _SHARE_MIN:
        extra.append(f"Sobrepõe floresta pública não destinada (tipo B) em {_percent(forest)}.")
    quilombola = share("quilombola_share")
    if quilombola >= _SHARE_MIN:
        extra.append(f"Sobrepõe território quilombola georreferenciado no Sigef em {_percent(quilombola)}.")
    alert = (ti >= _SHARE_MIN or strict >= _SHARE_MIN or embargoes > 0 or forest >= _SHARE_MIN
             or quilombola >= _SHARE_MIN)
    if alert and check == "ok":
        check, note = "attention", ""
    area = "; ".join(str(n) for n in names if isinstance(n, str)) or None
    return check, " ".join([note, *extra]).strip(), area


def car_check(code: str | Iterable[str]) -> pd.DataFrame:
    """Verificar vários imóveis de uma vez.

    Para uma lista de códigos, diz o que consta de cada um na camada pública
    do CAR e resume em um resultado: a triagem que antecede, por exemplo, a
    análise de um pedido de crédito rural. Os códigos são agrupados por UF e
    município, de modo que uma lista grande lê poucos trechos de cada arquivo.

    O resultado (``check``) é uma classificação do pacote, não uma regra
    oficial:

    - ``"ok"``: cadastro ativo, sem notificação pendente;
    - ``"attention"``: cadastro pendente, analisado com notificação ainda
      sem resposta do declarante, com mais de 1% da área sobre terra
      indígena, unidade de conservação de proteção integral, floresta
      pública não destinada ou território quilombola georreferenciado no
      Sigef, ou com embargo ambiental ativo do Ibama;
    - ``"blocked"``: cadastro cancelado ou suspenso;
    - ``"not_found"``: código que não está na publicação (pode ter sido
      cadastrado depois da última atualização);
    - ``"invalid"``: texto que não tem o formato de um código do CAR.

    A sobreposição com terras indígenas (Funai) e unidades de conservação
    (CNUC/MMA) é calculada na publicação, pelos perímetros declarados. Estar
    em unidade de uso sustentável é informado na nota, mas não muda o
    resultado: áreas de proteção ambiental e reservas particulares admitem
    imóveis privados. Os embargos são os do Ibama (dados abertos, termos
    não cancelados e sem desembargo), localizados pelo polígono ou pelo
    ponto do termo; não entram embargos estaduais nem do ICMBio. A
    As florestas públicas não destinadas ("tipo B") são as do Cadastro
    Nacional de Florestas Públicas. Os territórios quilombolas são só os
    já georreferenciados no Sigef, do Incra: a camada completa não está
    publicada hoje, então a ausência de alerta não garante que o imóvel
    esteja fora de um território quilombola. A verificação não cobre a
    supressão de vegetação nem o trabalho análogo à escravidão, e não
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
        ``municipality``, ``created_at`` e, para os imóveis não cancelados,
        ``indigenous_share``, ``strict_protection_share``,
        ``sustainable_use_share`` (parcelas da área, de 0 a 1),
        ``protected_area`` (os nomes das áreas sobrepostas),
        ``embargo_count``, ``embargo_share``, ``public_forest_share``,
        ``quilombola_share`` e ``sigef_share``.
    """
    codes = list(dict.fromkeys(str(c).strip().upper() for c in _as_list(code) if str(c).strip()))
    columns = ["property_code", "status", "condition", "property_type", "size_class",
               "area_ha", "fiscal_modules", "state", "municipality", "created_at"]
    order = ["property_code", "check", "note", "stage", *columns[1:], *_PROTECTED]
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
            parts.append(part[columns].merge(_check_quality(uf, part), on="property_code", how="left"))
    found = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=columns)
    found["property_code"] = found["property_code"].astype(object)
    out = pd.DataFrame({"property_code": pd.Series(codes, dtype=object)}).merge(
        found, on="property_code", how="left")
    out["stage"] = out["condition"].map(_stage)
    checks, notes, areas = [], [], []
    for _, row in out.iterrows():
        if not _CODE.match(row["property_code"]):
            verdict = ("invalid", _NOTES["invalid"])
        elif not isinstance(row["state"], str):
            verdict = ("not_found", _NOTES["not_found"])
        else:
            verdict = _protected(row, *_verdict(row))
        checks.append(verdict[0])
        notes.append(verdict[1])
        areas.append(verdict[2] if len(verdict) > 2 else None)
    out["check"], out["note"], out["protected_area"] = checks, notes, pd.Series(areas, dtype=object)
    return out.reindex(columns=order)


_QUALITY = ["property_code", "municipality_code", "overlap_count", "overlap_share", "outside_share",
            "indigenous_share", "strict_protection_share", "sustainable_use_share",
            "indigenous_land", "conservation_unit", "conservation_category",
            "embargo_count", "embargo_share", "public_forest_share",
            "sigef_count", "sigef_share", "quilombola_share", "settlement_share"]
_QUALITY_SUMMARY = ["state", "municipality_code", "municipality", "properties", "overlapping",
                    "overlapping_half", "overlap_ha", "outside_half", "outside_ha",
                    "indigenous", "indigenous_ha", "strict_protection", "strict_protection_ha",
                    "sustainable_use", "sustainable_use_ha", "embargoed", "embargo_ha",
                    "public_forest", "public_forest_ha",
                    "certified", "sigef_ha", "quilombola", "settlement"]


def car_quality(state: str | Iterable[str], municipality=None) -> pd.DataFrame:
    """Indicadores de qualidade por imóvel.

    Sinais calculados na publicação para cada imóvel não cancelado:

    - ``overlap_count`` e ``overlap_share``: com quantos outros imóveis do estado ele
      divide área, e que parcela da área dele está sobreposta (a soma das interseções
      com cada vizinho, limitada a 1);
    - ``outside_share``: que parcela da área fica fora do município declarado, pela
      malha municipal do IBGE;
    - ``indigenous_share``: que parcela fica dentro de terras indígenas (Funai, todas
      as fases do processo), com o nome da principal em ``indigenous_land``;
    - ``strict_protection_share`` e ``sustainable_use_share``: que parcela fica dentro
      de unidades de conservação de proteção integral e de uso sustentável (CNUC/MMA),
      com o nome e a categoria da principal em ``conservation_unit`` e
      ``conservation_category`` (a de proteção integral, se houver);
    - ``embargo_count`` e ``embargo_share``: quantos embargos ambientais ativos do Ibama
      alcançam o imóvel e que parcela da área está embargada (só os termos que têm o
      polígono da área; os demais contam pelo ponto de referência);
    - ``public_forest_share``: que parcela fica dentro de florestas públicas não destinadas
      ("tipo B"), pelo Cadastro Nacional de Florestas Públicas, do Serviço Florestal;
    - ``sigef_count`` e ``sigef_share``: quantas parcelas georreferenciadas no Sigef (Incra)
      o imóvel alcança e que parcela da área elas cobrem, contando só parcelas particulares
      e lotes de assentamento (glebas públicas e áreas protegidas, que também estão no
      Sigef, ficam de fora). Perto de 1 quer dizer que o perímetro declarado no CAR
      coincide com um georreferenciamento aprovado pelo Incra;
    - ``quilombola_share`` e ``settlement_share``: que parcela cai em parcelas do Sigef cuja
      natureza é território quilombola ou assentamento. **A cobertura é parcial**: só os
      territórios já georreferenciados no Sigef; a camada completa de territórios
      quilombolas não está publicada pelo Incra hoje.

    Sobreposição entre imóveis não é sinônimo de disputa: inclui imóvel declarado duas
    vezes e lote dentro de assentamento; a comparação é só entre imóveis do mesmo
    estado. Estar em unidade de uso sustentável também não é irregularidade: áreas de
    proteção ambiental (APA) e reservas particulares (RPPN) admitem imóveis privados.
    As edições das camadas estão em ``source.protected_areas`` no catálogo.

    Parameters
    ----------
    state
        Sigla de uma ou mais UFs.
    municipality
        Nomes ou códigos IBGE (7 dígitos) de municípios; lê só os trechos deles.

    Returns
    -------
    pandas.DataFrame
        ``property_code``, ``municipality_code`` e os indicadores acima. Junte a
        :func:`car_properties` por ``property_code``. As colunas de terras indígenas e
        unidades de conservação vêm vazias se a publicação ainda não as traz.
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
    rel = _client.con().read_parquet(files, union_by_name=True)
    where, params = [], []
    if municipality is not None:
        codes = _municipality_codes(municipality, states)
        where.append(f"municipality_code IN ({', '.join('?' * len(codes))})")
        params.extend(codes)
    out = _collect(rel, where, params, True)
    return pd.DataFrame(columns=_QUALITY) if out is None else out.reindex(columns=_QUALITY)


def car_quality_summary(state: str | Iterable[str] | None = None) -> pd.DataFrame:
    """Indicadores de qualidade por município.

    Para cada município: imóveis não cancelados (``properties``), quantos têm sobreposição
    acima de 1% (``overlapping``) e de 50% da área (``overlapping_half``), os hectares
    sobrepostos (``overlap_ha``, somando os dois lados de cada par), e quantos imóveis
    (``outside_half``) e hectares (``outside_ha``) ficam fora do município declarado.
    E, para terras indígenas (``indigenous``), unidades de proteção integral
    (``strict_protection``) e de uso sustentável (``sustainable_use``), quantos imóveis
    têm mais de 1% da área dentro delas e quantos hectares (``*_ha``); e quantos imóveis
    têm embargo ativo do Ibama (``embargoed``) e os hectares embargados (``embargo_ha``); e
    quantos têm mais de 1% da área em floresta pública tipo B (``public_forest``,
    ``public_forest_ha``). Do Sigef: ``certified`` (imóveis com mais da metade da área em
    parcelas georreferenciadas), ``sigef_ha``, ``quilombola`` e ``settlement`` (imóveis com
    mais de 1% em território quilombola ou em assentamento do Sigef).
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
    rel = _client.con().read_parquet([str(f) for f in files], union_by_name=True)  # noqa: F841
    out = _client.con().execute("SELECT * FROM rel ORDER BY municipality_code").df()
    names = car_municipalities(states)[["municipality_code", "municipality"]]
    return out.merge(names, on="municipality_code", how="left").reindex(columns=_QUALITY_SUMMARY)


_TYPOLOGY = ["state", "municipality_code", "municipality", "typology", "typology_label", "properties",
             "small_share", "large_area_share", "waiting_share", "notified_share", "analysed_share",
             "overlap_share", "coverage"]
_TYPOLOGY_GROUPS = ["typology", "typology_label", "description", "municipalities", "properties"]


def car_typology(state: str | Iterable[str] | None = None) -> pd.DataFrame:
    """Tipologia dos municípios.

    Cada município entra num de cinco grupos, pelo perfil do seu cadastro: o porte dos
    imóveis, em que etapa a análise está e quanto os cadastros se sobrepõem. Os grupos são
    achados por agrupamento (k-médias) sobre sete indicadores e ficam fixos de uma
    atualização para a outra, de modo que dá para acompanhar um município mudando de grupo.
    Municípios com menos de 30 imóveis não cancelados ficam em ``"few"``.

    Os indicadores, todos sobre os imóveis não cancelados do município:

    - ``small_share``: parcela de imóveis pequenos (até 4 módulos fiscais);
    - ``large_area_share``: parcela da área declarada que está em imóveis grandes;
    - ``waiting_share``, ``notified_share`` e ``analysed_share``: parcela aguardando
      análise, notificada sem resposta e já analisada ou em análise;
    - ``overlap_share``: parcela com mais da metade da área sobreposta a outros cadastros;
    - ``coverage``: área declarada dividida pela área do município (limitada a 2).

    Parameters
    ----------
    state
        Sigla de uma ou mais UFs; ``None`` traz o país inteiro.

    Returns
    -------
    pandas.DataFrame
        Uma linha por município: ``state``, ``municipality_code``, ``municipality``,
        ``typology`` (o código do grupo), ``typology_label`` (o nome), ``properties`` e
        os sete indicadores. O que cada grupo quer dizer está em
        :func:`car_typology_groups`.
    """
    empty = pd.DataFrame(columns=_TYPOLOGY)
    cat = _client.catalog_json()
    if cat is None:
        return empty
    states = _states(state, cat)
    path = "typology/municipalities.parquet"
    if path not in {f["path"] for f in cat["files"]}:
        cat = _client.catalog_json(refresh=True)
        if cat is None or path not in {f["path"] for f in cat["files"]}:
            warnings.warn("This publication has no typology; returning an empty result.",
                          _client.CarWarning, stacklevel=2)
            return empty
    file = _client.cached_file(cat, path)
    if file is None:
        return empty
    rel = _client.con().read_parquet(str(file))  # noqa: F841
    out = _client.con().execute("SELECT * FROM rel ORDER BY municipality_code").df()
    return out[out["state"].isin(states)].reindex(columns=_TYPOLOGY).reset_index(drop=True)


def car_typology_groups() -> pd.DataFrame:
    """Os grupos da tipologia dos municípios.

    Returns
    -------
    pandas.DataFrame
        Uma linha por grupo: ``typology`` (o código), ``typology_label`` (o nome),
        ``description`` (o que o distingue), ``municipalities`` e ``properties`` (quantos
        municípios e imóveis estão nele na publicação atual).
    """
    cat = _client.catalog_json()
    groups = (cat or {}).get("typology", {}).get("groups", [])
    out = pd.DataFrame(groups).rename(columns={"code": "typology", "label": "typology_label"})
    return out.reindex(columns=_TYPOLOGY_GROUPS)
