"""Servidor MCP do carbr: as consultas ao CAR como ferramentas para assistentes.

Um assistente compatível com o Model Context Protocol (MCP) passa a responder
perguntas como "quantos imóveis notificados há em Marabá?" ou "o que está
declarado neste ponto?" com os dados reais, em vez de estimar. O servidor roda
na máquina de quem usa, lê a mesma publicação dos pacotes e não tem custo de
operação.

    pip install "carbr[mcp]"
    carbr-mcp                     # fala MCP pela entrada e saída padrão (stdio)

Requer o extra ``mcp`` (o SDK ``mcp`` 2.x e o geopandas).
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from . import _client
from ._msg import set_verbose
from .cite import citation
from .data import (
    _stage,
    car_at,
    car_catalog,
    car_check,
    car_dictionary,
    car_municipalities,
    car_quality,
    car_quality_summary,
    car_summary,
    car_tbl,
)

MAX_ROWS = 200

INSTRUCTIONS = """\
Dados públicos do Cadastro Ambiental Rural (CAR) do Brasil, republicados do Sicar
(Serviço Florestal Brasileiro): o perímetro declarado e dez atributos de cada um dos
cerca de 8,6 milhões de imóveis rurais. Não há dado pessoal.

Ao responder com estes dados:
- O cadastro é autodeclarado. Há sobreposições, e constar no CAR não comprova posse nem
  propriedade (Lei 12.651/2012, art. 29, § 2º).
- Os dados são uma cópia semanal; informe a data da publicação (campo `versao`).
- Cite a fonte: Sicar/SFB, via carbr. Esta é uma republicação independente, sem caráter
  oficial; em caso de divergência, vale o Sicar.
- Etapas da análise (`etapa`): waiting = aguardando análise; analysing = em análise;
  notified = analisado, com notificação sem resposta do declarante; answered = respondeu,
  aguarda nova análise; done = análise concluída; cancelled = cancelado.
- Porte (`size_class`): small = até 4 módulos fiscais; medium = de 4 a 15; large = acima
  de 15. Assentamentos e territórios tradicionais aparecem como "small" mesmo quando grandes.
- Para totais do país ou de um estado, use `resumo`; para um município, `municipio`.
- Qualidade (`qualidade`): `overlap_share` é a parcela da área do imóvel sobreposta a outros
  imóveis do estado; `outside_share`, a parcela fora do município declarado. Sobreposição não é
  sinônimo de disputa: inclui imóvel declarado duas vezes e lote dentro de assentamento.
"""

STAGE_LABELS = {
    "waiting": "Aguardando análise",
    "analysing": "Em análise",
    "notified": "Notificado, sem resposta",
    "answered": "Respondeu, aguarda nova análise",
    "done": "Analisado",
    "cancelled": "Cancelado",
}


def _records(df: pd.DataFrame, limit: int = MAX_ROWS) -> list[dict[str, Any]]:
    """Linhas como dicionários simples, sem NaN nem tipos do pandas."""
    out = df.head(limit).astype(object).where(df.head(limit).notna(), None)
    rows = out.to_dict("records")
    for row in rows:
        for key, value in row.items():
            if isinstance(value, pd.Timestamp):
                row[key] = value.date().isoformat()
            elif hasattr(value, "item"):
                row[key] = value.item()
    return rows


def _envelope(**fields: Any) -> dict[str, Any]:
    """Toda resposta leva a versão dos dados e a citação."""
    cat = _client.catalog_json()
    version = cat["version"] if cat else None
    return {**fields, "versao": version, "fonte": citation(version) if version else None}


def catalogo() -> dict[str, Any]:
    """O que está publicado: UFs, número de imóveis e de municípios, data dos dados."""
    df = car_catalog()
    return _envelope(
        estados=_records(df[["state", "properties", "municipalities"]]),
        total_de_imoveis=int(df["properties"].sum()) if len(df) else 0,
    )


def dicionario() -> dict[str, Any]:
    """O que significa cada coluna dos dados e qual o nome dela no Sicar."""
    return _envelope(colunas=_records(car_dictionary()))


def resumo(por: list[str] | None = None, uf: list[str] | None = None) -> dict[str, Any]:
    """Totais pré-calculados de imóveis e de área declarada (hectares), do país ou de UFs.

    `por`: dimensões do resumo, entre "state", "status", "size_class", "property_type",
    "condition" (o texto do Sicar para a etapa da análise) e "created_year". Vazio dá o
    total. `uf`: siglas das UFs; vazio é o país inteiro.
    """
    df = car_summary(por or None, uf or None)
    if "condition" in df.columns:
        df = df.assign(etapa=df["condition"].map(_stage))
    return _envelope(linhas=_records(df), truncado=len(df) > MAX_ROWS)


def etapas_da_analise(uf: list[str] | None = None) -> dict[str, Any]:
    """Quantos imóveis estão em cada etapa da análise, no país ou nas UFs dadas.

    Responde "onde a análise está parada": quantos aguardam análise, quantos foram
    notificados e não responderam, quantos têm a análise concluída.
    """
    df = car_summary(["condition"], uf or None)
    df = df.assign(etapa=df["condition"].map(_stage)).groupby("etapa", as_index=False)[
        ["properties", "area_ha"]].sum()
    total = int(df["properties"].sum())
    df = df.assign(rotulo=df["etapa"].map(STAGE_LABELS),
                   percentual=(100 * df["properties"] / total).round(1) if total else 0.0)
    return _envelope(etapas=_records(df.sort_values("properties", ascending=False)), total=total)


def municipios(uf: str, ordenar_por: str = "properties", limite: int = 20) -> dict[str, Any]:
    """Os municípios de uma UF, do maior para o menor em `ordenar_por`.

    `ordenar_por`: "properties" (imóveis), "small_properties", "area_ha", "pending",
    "cancelled" ou "invalid_geometries".
    """
    df = car_municipalities(uf)
    if ordenar_por not in df.columns:
        raise ValueError(f"`ordenar_por` deve ser uma coluna do resumo municipal: {list(df.columns)}")
    df = df.sort_values(ordenar_por, ascending=False).drop(columns=["xmin", "ymin", "xmax", "ymax"])
    return _envelope(municipios=_records(df, min(int(limite), MAX_ROWS)), total_de_municipios=len(df))


def municipio(uf: str, nome: str) -> dict[str, Any]:
    """Um município em detalhe: imóveis, área, porte, situação e etapas da análise.

    `nome` não diferencia maiúsculas nem acentos. Lê duas colunas do arquivo do estado
    para contar as etapas da análise no município.
    """
    from .data import _fold

    towns = car_municipalities(uf)
    match = towns[towns["municipality"].map(_fold) == _fold(nome)]
    if match.empty:
        near = towns[towns["municipality"].map(_fold).str.contains(_fold(nome)[:5], regex=False)]
        return _envelope(encontrado=False, parecidos=list(near["municipality"].head(8)))
    row = match.iloc[0]
    stages = car_tbl(uf).filter(f"municipality_code = {int(row['municipality_code'])}").aggregate(
        "condition, count(*) AS properties, sum(area_ha) AS area_ha").df()
    stages = stages.assign(etapa=stages["condition"].map(_stage)).groupby("etapa", as_index=False)[
        ["properties", "area_ha"]].sum()
    stages = stages.assign(rotulo=stages["etapa"].map(STAGE_LABELS),
                           percentual=(100 * stages["properties"] / stages["properties"].sum()).round(1))
    summary = _records(match.drop(columns=["xmin", "ymin", "xmax", "ymax"]))[0]
    return _envelope(encontrado=True, municipio=summary,
                     etapas=_records(stages.sort_values("properties", ascending=False)),
                     qualidade=_town_quality(uf, int(row["municipality_code"])))


def _town_quality(uf: str, code: int) -> dict[str, Any] | None:
    """Indicadores de qualidade de um município, ou `None` se a publicação não os traz."""
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        towns = car_quality_summary(uf)
    row = towns[towns["municipality_code"] == code]
    if row.empty:
        return None
    r = _records(row.drop(columns=["state", "municipality_code", "municipality"]))[0]
    n = r["properties"] or 1
    r["percentual_com_sobreposicao"] = round(100 * r["overlapping"] / n, 1)
    r["percentual_com_mais_da_metade_sobreposta"] = round(100 * r["overlapping_half"] / n, 1)
    r["percentual_com_mais_da_metade_fora_do_municipio"] = round(100 * r["outside_half"] / n, 1)
    return r


def _property_quality(df: pd.DataFrame) -> pd.DataFrame:
    """Indicadores de qualidade dos imóveis de `df` (vazio se a publicação não os traz)."""
    import warnings

    columns = ["property_code", "overlap_count", "overlap_share", "outside_share"]
    parts = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for uf, group in df.groupby("state"):
            q = car_quality(uf, municipality=sorted({int(c) for c in group["municipality_code"]}))
            parts.append(q[q["property_code"].isin(group["property_code"])][columns])
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=columns)


def imoveis_no_ponto(lon: float, lat: float) -> dict[str, Any]:
    """Os imóveis declarados num ponto (longitude e latitude em graus, SIRGAS 2000).

    Mais de um resultado significa sobreposição entre cadastros, que é comum.
    """
    df = car_at(lon, lat, geometry=False)
    df = df.assign(etapa=df["condition"].map(_stage))
    df = df.merge(_property_quality(df), on="property_code", how="left")
    columns = ["property_code", "municipality", "state", "status", "condition", "etapa",
               "property_type", "size_class", "area_ha", "fiscal_modules", "created_at",
               "overlap_count", "overlap_share", "outside_share"]
    return _envelope(imoveis=_records(df[columns]), quantidade=len(df), sobreposicao=len(df) > 1)


def verificar_imoveis(codigos: list[str]) -> dict[str, Any]:
    """Verifica uma lista de códigos de imóvel do CAR (até 200 por chamada).

    Para cada código: o que consta na camada pública e um resultado (`check`): ok
    (ativo, sem notificação pendente), attention (pendente ou notificado sem resposta),
    blocked (cancelado ou suspenso), not_found, invalid. A classificação é do carbr, não
    uma regra oficial, e não cobre embargos nem sobreposição com áreas protegidas.
    """
    if len(codigos) > MAX_ROWS:
        raise ValueError(f"No máximo {MAX_ROWS} códigos por chamada; divida a lista.")
    df = car_check(codigos)
    counts = df["check"].value_counts().to_dict() if len(df) else {}
    return _envelope(imoveis=_records(df), resultado={k: int(v) for k, v in counts.items()})


TOOLS = [catalogo, dicionario, resumo, etapas_da_analise, municipios, municipio,
         imoveis_no_ponto, verificar_imoveis]


def build():
    """Monta o servidor MCP com as ferramentas acima."""
    try:
        from mcp.server.mcpserver import MCPServer
    except ImportError as err:  # pragma: no cover
        raise ImportError('O servidor MCP precisa do extra "mcp": pip install "carbr[mcp]".') from err
    from . import __version__

    server = MCPServer(
        "carbr",
        title="CAR — Cadastro Ambiental Rural",
        instructions=INSTRUCTIONS,
        version=__version__,
        website_url="https://car.castlab.org/ajuda.html",
    )
    for tool in TOOLS:
        server.tool()(tool)
    return server


def main() -> None:
    """Ponto de entrada do comando ``carbr-mcp`` (transporte stdio)."""
    set_verbose(False)      # stdout é o canal do protocolo; nada pode ser impresso nele
    _client.con().execute("SET enable_progress_bar = false")
    build().run("stdio")


if __name__ == "__main__":
    main()
