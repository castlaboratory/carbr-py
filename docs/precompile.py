"""Precompila a página da documentação que lê dados reais.

Mesma ideia da vinheta do pacote R: os exemplos rodam aqui, contra a
publicação real, e o Markdown que o site publica é gravado com a saída e a
figura embutidas. O build do site, então, não precisa de rede. Rode da raiz
do repositório quando um exemplo ou os dados mudarem e commite o resultado:

    python docs/precompile.py [página.md ...]
"""

from __future__ import annotations

import contextlib
import io
import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

import carbr  # noqa: E402

DOCS = Path(__file__).parent
pd.set_option("display.width", 100)
pd.set_option("display.max_columns", 8)
pd.set_option("display.max_colwidth", 60)
pd.set_option("display.max_rows", 12)
carbr.set_verbose(False)
carbr.car_catalog(refresh=True)


def fig(name: str) -> str:
    """Grava a figura corrente em docs/assets e devolve o link Markdown."""
    plt.tight_layout()
    plt.savefig(DOCS / "assets" / f"{name}.png", dpi=110)
    plt.close("all")
    return f"![{name}](assets/{name}.png)"


def run(code: str, ns: dict) -> str:
    """Executa um bloco; devolve o que ele imprimiu mais o repr da última expressão."""
    *body, last = code.split("\n\n")
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        for block in body:
            exec(block, ns)
        try:
            value = eval(last, ns)
        except SyntaxError:
            exec(last, ns)
            value = None
    text = out.getvalue()
    if value is not None:
        text += (value if isinstance(value, str) else repr(value)) + "\n"
    return text


def page(path: str, parts: list[tuple[str, str | None]]) -> None:
    ns: dict = {"carbr": carbr, "pd": pd, "plt": plt, "fig": fig}
    md = []
    for prose, code in parts:
        if prose.strip():
            md.append(textwrap.dedent(prose).strip() + "\n")
        if code is None:
            continue
        code = textwrap.dedent(code).strip()
        md.append("```python\n" + code + "\n```\n")
        out = run(code, ns)
        # Figuras saem como links Markdown de imagem: ficam fora do bloco de saída.
        images = [ln for ln in out.splitlines() if ln.startswith("![")]
        text = "\n".join(ln for ln in out.splitlines() if not ln.startswith("![")).rstrip()
        if text:
            md.append("```text\n" + text + "\n```\n")
        md.extend(i + "\n" for i in images)
    (DOCS / path).write_text("\n".join(md), encoding="utf-8")
    print(f"gravado {path}")


PRIMEIROS_PASSOS = [
    (
        """
        # Primeiros passos

        O **Cadastro Ambiental Rural (CAR)** é o registro público eletrônico dos imóveis
        rurais do país, criado pelo Código Florestal (Lei nº 12.651/2012) e mantido no Sicar
        pelo Serviço Florestal Brasileiro. O `carbr` lê uma republicação dos dados públicos
        do cadastro em GeoParquet, com as 27 UFs e cerca de 8,6 milhões de imóveis. Cada
        consulta transfere só os trechos do arquivo de que precisa, sem baixar a base de um
        estado inteiro e sem passar pelos servidores do Sicar.

        | Função | Para quê |
        |---|---|
        | `car_catalog()` | O que está publicado |
        | `car_dictionary()` | O que cada coluna significa |
        | `car_summary()` | Totais pré-calculados, do estado ou do país |
        | `car_municipalities()` | Resumo por município |
        | `car_properties()` | Imóveis de uma UF, com filtros |
        | `car_property()` | Um imóvel pelo código |
        | `car_at()` | Imóveis que contêm um ponto |
        | `car_tbl()` | Relação preguiçosa do DuckDB |
        | `car_cite()` | Como citar |

        ## O que está publicado

        `car_catalog()` traz uma linha por UF, com o número de imóveis e os indicadores de
        qualidade da carga. A versão é a data da última atualização da publicação.
        """,
        """
        import carbr

        cat = carbr.car_catalog()
        print(cat.attrs["version"], "-", len(cat), "UFs,", cat["properties"].sum(), "imóveis")

        cat.head(6)
        """,
    ),
    (
        "O dicionário de dados diz o que é cada coluna e qual era o seu nome no Sicar.",
        "print(carbr.car_dictionary().to_string(index=False))",
    ),
    (
        """
        ## O país inteiro, sem ler os imóveis

        `car_summary()` lê tabelas pequenas, calculadas na publicação, com a contagem de
        imóveis e a área declarada por UF, situação, porte, tipo, etapa da análise e ano de
        criação do cadastro. O argumento `by` escolhe as dimensões; `None` dá o total.
        """,
        """
        print(carbr.car_summary(None))

        carbr.car_summary("size_class")
        """,
    ),
    (
        """
        Os pequenos imóveis, de até quatro módulos fiscais, são mais de nove em cada dez
        cadastros e um terço da área declarada. Por UF:
        """,
        """
        by_state = carbr.car_summary(["state", "size_class"])
        wide = by_state.pivot(index="state", columns="size_class", values="properties").fillna(0)
        wide = wide.loc[wide.sum(axis=1).sort_values().index, ["small", "medium", "large"]] / 1e3
        wide.columns = ["Pequeno (até 4 módulos fiscais)", "Médio (4 a 15)", "Grande (acima de 15)"]

        ax = wide.plot.barh(stacked=True, figsize=(7, 6.5), width=0.8,
                            color=["#8fbf9f", "#3d8a5c", "#123a23"])
        ax.set_title("Imóveis declarados no CAR, por UF e porte")
        ax.set_xlabel("Milhares de imóveis")
        ax.set_ylabel("")
        ax.legend(frameon=False, loc="lower right")

        fig("estados")
        """,
    ),
    (
        "A etapa da análise mostra onde o cadastro está parado:",
        """
        cond = carbr.car_summary("condition").sort_values("properties", ascending=False)
        cond["share"] = (100 * cond["properties"] / cond["properties"].sum()).round(1)

        print(cond[["condition", "properties", "share"]].head(8).to_string(index=False))
        """,
    ),
    (
        "E o ano de criação dá a linha do tempo do cadastramento:",
        """
        years = carbr.car_summary("created_year")
        ax = (years.set_index("created_year")["properties"] / 1e3).plot.bar(
            figsize=(7, 3.6), color="#1f5f3a", width=0.85, rot=0)
        ax.set_title("Cadastros hoje no CAR, por ano de criação (último ano incompleto)")
        ax.set_xlabel("")
        ax.set_ylabel("Milhares de imóveis")

        fig("anos")
        """,
    ),
    (
        "As dimensões combinam, e `state` restringe a uma ou mais UFs:",
        """
        carbr.car_summary(["status", "size_class"], state=["PE", "BA"])
        """,
    ),
    (
        """
        ## Resumo por município

        O resumo municipal também é pré-calculado. Sem argumento, traz os municípios de
        todas as UFs.
        """,
        """
        mun = carbr.car_municipalities()

        mun.sort_values("properties", ascending=False)[
            ["state", "municipality", "properties", "small_properties", "area_ha", "pending"]
        ].head(6)
        """,
    ),
    (
        """
        ## Imóveis de um município

        `car_properties()` traz os imóveis de uma UF, com filtros aplicados antes da leitura:
        só os trechos do arquivo que atendem ao filtro são transferidos. Aqui, todos os
        imóveis de Petrolina, em Pernambuco — cerca de 11 mil, de um arquivo estadual com mais
        de 400 mil. Com o extra `geo` instalado, o resultado é um GeoDataFrame em SIRGAS 2000.
        """,
        """
        petrolina = carbr.car_properties("PE", municipality="Petrolina")

        petrolina[["property_code", "status", "area_ha", "fiscal_modules", "size_class"]].head(6)
        """,
    ),
    (
        """
        Sobre uma imagem de satélite, o cadastro mostra a ocupação do município: os lotes
        estreitos dos perímetros irrigados junto ao rio São Francisco, ao sul e a leste, e os
        imóveis maiores da caatinga, ao norte. O limite municipal é da malha do IBGE, lida
        direto da API de malhas; o fundo vem do pacote `contextily`.
        """,
        """
        import contextily as ctx
        import geopandas as gpd
        from matplotlib.lines import Line2D
        from matplotlib.patches import Patch

        boundary = gpd.read_file(
            "https://servicodados.ibge.gov.br/api/v3/malhas/municipios/2611101"
            "?formato=application/vnd.geo%2Bjson&qualidade=maxima"
        ).set_crs(4674, allow_override=True)

        valid = petrolina[petrolina["geometry_valid"] & (petrolina["status"] != "cancelled")]
        valid = valid.sort_values("area_ha", ascending=False)
        colors = {"small": "#ffe066", "medium": "#ff922b", "large": "#e03131"}
        labels = {"small": "Pequeno (até 4 módulos fiscais)", "medium": "Médio (4 a 15)",
                  "large": "Grande (acima de 15)"}

        ax = valid.plot(color=valid["size_class"].map(colors), edgecolor=valid["size_class"].map(colors),
                        linewidth=0.3, alpha=0.55, figsize=(7, 7.6))
        boundary.boundary.plot(ax=ax, color="white", linewidth=1.6)
        ax.margins(0.03)
        ctx.add_basemap(ax, crs=valid.crs, source=ctx.providers.Esri.WorldImagery, zoom=10,
                        attribution="Fontes: SFB/Sicar, via carbr; malha municipal do IBGE. Imagem: Esri World Imagery.",
                        attribution_size=6)
        handles = [Patch(color=colors[k], label=labels[k]) for k in colors]
        handles.append(Line2D([], [], color="white", linewidth=1.6, label="Limite municipal"))
        ax.legend(handles=handles, facecolor="#2b2b2b", labelcolor="white",
                  loc="upper right", fontsize=8, framealpha=0.85)
        ax.set_title(f"Imóveis declarados no CAR em Petrolina, Pernambuco\\n"
                     f"{len(valid)} cadastros ativos ou pendentes, por porte", loc="left", fontsize=11)
        ax.set_axis_off()

        fig("mapa-petrolina")
        """,
    ),
    (
        "Os filtros combinam. Só os imóveis grandes com cadastro ativo:",
        """
        large = carbr.car_properties(
            "PE", municipality="Petrolina", size_class="large", status="active", geometry=False
        )

        large.sort_values("area_ha", ascending=False)[
            ["property_code", "area_ha", "fiscal_modules", "condition"]
        ]
        """,
    ),
    (
        """
        O município pode ser dado pelo nome (sem diferenciar maiúsculas nem acentos) ou pelo
        código IBGE de sete dígitos. Os outros filtros são `status`, `property_type` e `bbox`.

        ## Sem a geometria

        A geometria é a parte pesada do arquivo. Quando só os atributos interessam,
        `geometry=False` deixa de transferi-la. Os cadastros pendentes de Pernambuco, por
        município:
        """,
        """
        pending = carbr.car_properties("PE", status="pending", geometry=False)

        pending["municipality"].value_counts().head(6)
        """,
    ),
    (
        """
        ## Que imóveis estão declarados aqui?

        `car_at()` devolve os imóveis que contêm um ponto, procurando em todas as UFs (ou só
        nas de `state`). Como o cadastro é autodeclarado, sobreposições são comuns e o
        resultado pode ter mais de uma linha, como neste ponto do Distrito Federal:
        """,
        """
        here = carbr.car_at(lon=-47.9, lat=-15.8, geometry=False)

        print(here[["property_code", "municipality", "area_ha", "status", "condition"]].T)
        """,
    ),
    (
        "## Um imóvel pelo código",
        """
        one = carbr.car_property("PE-2611101-588BC484570D440484F527F07DF5AFFA", geometry=False)

        print(one.T)
        """,
    ),
    (
        """
        ## Consultas próprias

        Para o que `car_summary()` não cobre, `car_tbl()` devolve uma relação preguiçosa do
        DuckDB sobre os arquivos publicados. Nada é lido até o `.df()`, e a consulta roda
        sobre o arquivo remoto lendo só as colunas usadas. Convém restringir a uma UF: sobre
        o país inteiro, uma agregação lê colunas de 8,6 milhões de linhas e leva minutos.
        """,
        """
        carbr.car_tbl("PE").filter("fiscal_modules > 15 AND status = 'active'").aggregate(
            "municipality, count(*) AS properties, round(sum(area_ha)) AS area_ha"
        ).order("area_ha DESC").limit(5).df()
        """,
    ),
    (
        "## Como citar",
        "text = carbr.car_cite()",
    ),
    (
        """
        ## Endereço dos dados e cache

        O pacote lê de um bucket público. Para usar um espelho compatível com S3 ou uma cópia
        local da publicação, chame `carbr.set_base_url()` ou defina a variável de ambiente
        `CAR_URL`. O catálogo e os resumos ficam em cache em `carbr.car_cache_dir()`, e o
        catálogo vale por seis horas (`car_catalog(refresh=True)` o relê); os imóveis nunca
        são copiados para o disco.
        """,
        None,
    ),
]


INCONSISTENCIAS = [
    (
        """
        # Inconsistências do cadastro

        O CAR é **autodeclarado**: quem desenha o perímetro e informa os dados é o próprio
        declarante, e a conferência vem depois, na análise. Enquanto ela não chega, o cadastro
        guarda sobreposições, imóveis fora do município informado e áreas que não fecham com o
        território. Este guia mostra como encontrar essas inconsistências com o `carbr`, do
        país até um município.

        Nada aqui é juízo sobre um imóvel em particular: são sinais para orientar a análise e
        para quem usa os dados saber o que tem em mãos.
        """,
        """
        import carbr
        import geopandas as gpd


        def ibge_mesh(path):
            url = ("https://servicodados.ibge.gov.br/api/v3/malhas/" + path
                   + "formato=application/vnd.geo%2Bjson&qualidade=intermediaria")
            return gpd.read_file(url).to_crs(4674)
        """,
    ),
    (
        """
        ## O que a carga já registra

        Ao republicar os dados, o `carbr` anota no catálogo o que encontrou em cada UF:
        geometrias inválidas (com autointerseção, por exemplo) e imóveis cujo código começa
        com a sigla de outra UF. As inválidas ficam na publicação, marcadas na coluna
        `geometry_valid`.
        """,
        """
        cat = carbr.car_catalog()
        print(cat[["invalid_geometries", "registered_in_other_state"]].sum())

        cat.sort_values("invalid_geometries", ascending=False)[
            ["state", "properties", "invalid_geometries", "registered_in_other_state"]
        ].head(6)
        """,
    ),
    (
        """
        ## O código diz um município, o cadastro diz outro

        O código do imóvel traz o município em que ele foi registrado (`UF-0000000-…`). Em
        Pernambuco, comparando com a coluna `municipality_code`:
        """,
        """
        moved = carbr.car_tbl("PE").filter(
            "substr(property_code, 4, 7) <> municipality_code::VARCHAR"
        ).project("property_code, municipality, area_ha").df()
        print(len(moved), "imóveis")

        moved["municipality"].value_counts().head(6)
        """,
    ),
    (
        """
        Nem todo caso é erro — imóveis mudam de município quando a base municipal é
        atualizada —, mas é uma lista curta para conferir.

        ## Mais área declarada do que território

        Somando a área declarada dos imóveis de cada município e dividindo pela área do
        município na malha do IBGE, o resultado não deveria passar de 1. Passa em vários.
        """,
        """
        mesh = ibge_mesh("estados/PE?intrarregiao=municipio&")
        mesh["municipality_code"] = mesh["codarea"].astype(int)
        mesh["territory_ha"] = mesh.to_crs(6933).area / 1e4  # projeção de área igual

        ratio = mesh.merge(carbr.car_municipalities("PE"), on="municipality_code", how="left")
        ratio["ratio"] = ratio["area_ha"] / ratio["territory_ha"]
        print((ratio["ratio"] > 1).sum(), "de", len(ratio), "municípios com mais área declarada que território")

        ratio.sort_values("ratio", ascending=False)[
            ["municipality", "properties", "area_ha", "territory_ha", "ratio"]
        ].head(6).round(2)
        """,
    ),
    (
        """
        A concentração na Zona da Mata sugere sobreposição sistemática entre imóveis, não
        erro isolado.
        """,
        """
        from matplotlib.colors import BoundaryNorm, ListedColormap

        cmap = ListedColormap(["#e8f1e4", "#b7d3ad", "#7fae78", "#f08c4a", "#c92a2a"])
        norm = BoundaryNorm([0, 0.5, 0.8, 1, 1.5, 10], cmap.N)
        ax = ratio.plot(column="ratio", cmap=cmap, norm=norm, edgecolor="white", linewidth=0.2,
                        figsize=(7, 3.6), legend=True,
                        legend_kwds={"shrink": 0.6, "ticks": [0, 0.5, 0.8, 1, 1.5],
                                     "label": "Área declarada / área do município"},
                        missing_kwds={"color": "#d9d9d9"})
        ax.set_xlim(-41.4, -34.8)
        ax.set_ylim(-9.5, -7.25)
        ax.set_title("Onde o CAR declara mais área do que o município tem", loc="left")
        ax.set_axis_off()

        fig("razao")
        """,
    ),
    (
        """
        ## Dentro de um município: Petrolina

        Com os perímetros, dá para ir ao detalhe. Os imóveis não cancelados de Petrolina e o
        limite do município, em coordenadas planas para medir em hectares:
        """,
        """
        petrolina = carbr.car_properties("PE", municipality="Petrolina")
        petrolina = petrolina[(petrolina["status"] != "cancelled") & petrolina["geometry_valid"]]
        utm = petrolina.to_crs(31984).reset_index(drop=True)
        boundary = mesh[mesh["codarea"] == "2611101"].to_crs(31984)

        len(utm)
        """,
    ),
    (
        """
        ### Imóveis fora do município

        Recortando cada imóvel pelo limite do município, sai a parcela da área que fica do
        lado de fora. Faixas estreitas na divisa são esperadas, porque o traçado do IBGE e o
        do declarante nunca coincidem; o sinal é o imóvel com mais da metade da área fora.
        """,
        """
        inside_ha = utm.intersection(boundary.geometry.iloc[0]).area / 1e4
        utm["geometry_ha"] = utm.area / 1e4
        utm["outside"] = (1 - inside_ha / utm["geometry_ha"]) > 0.5

        print(utm["outside"].sum(), "imóveis,", round(utm.loc[utm["outside"], "area_ha"].sum()), "hectares")
        """,
    ),
    (
        "",
        """
        ax = boundary.plot(color="#f4f8f1", edgecolor="#123a23", linewidth=1, figsize=(7, 7))
        utm[~utm["outside"]].plot(ax=ax, color="#8fbf9f", alpha=0.6)
        utm[utm["outside"]].plot(ax=ax, color="#c92a2a", edgecolor="#c92a2a", linewidth=0.5)
        ax.set_title("Imóveis registrados em Petrolina que ficam fora do município\\n"
                     "Em vermelho, os que têm mais da metade da área fora do limite do IBGE",
                     loc="left", fontsize=10)
        ax.set_axis_off()

        fig("fora")
        """,
    ),
    (
        """
        ### Sobreposições

        Uma junção espacial do conjunto com ele mesmo, com o predicado `overlaps`, aponta
        para cada imóvel os outros com que ele divide área (tocar na divisa não conta).
        """,
        """
        pairs = gpd.sjoin(utm[["property_code", "geometry"]], utm[["geometry"]], predicate="overlaps")
        utm["neighbours"] = pairs.groupby(level=0).size().reindex(utm.index, fill_value=0)
        summed_ha = utm["geometry_ha"].sum()
        covered_ha = utm.union_all().area / 1e4

        print(f"{(utm['neighbours'] > 0).sum()} de {len(utm)} imóveis sobrepõem ao menos um vizinho")
        print(f"soma das áreas: {summed_ha:.0f} ha; área coberta: {covered_ha:.0f} ha; "
              f"contado em dobro: {summed_ha - covered_ha:.0f} ha")
        """,
    ),
    (
        """
        A maioria das sobreposições são faixas estreitas na divisa. Os casos que mais pesam
        são poucos:
        """,
        """
        utm.sort_values("neighbours", ascending=False)[
            ["property_code", "area_ha", "fiscal_modules", "size_class", "neighbours"]
        ].head(6)
        """,
    ),
    (
        """
        ### "Pequeno" nem sempre é pequeno

        O porte (`size_class`) vem dos módulos fiscais informados pelo Sicar, não da área. Em
        assentamentos e territórios de povos e comunidades tradicionais, um único cadastro
        cobre muitas famílias, e um perímetro de milhares de hectares aparece com menos de
        quatro módulos. Em Pernambuco, os imóveis "pequenos" com mais de 440 hectares — quatro
        vezes o maior módulo fiscal do país:
        """,
        """
        carbr.car_tbl("PE").filter("size_class = 'small' AND area_ha > 440").aggregate(
            "property_type, count(*) AS properties, round(sum(area_ha)) AS area_ha"
        ).df()
        """,
    ),
    (
        """
        Quem conta "pequenos produtores" pelo porte deve separar o tipo do imóvel
        (`property_type`) antes.

        ## O que fazer com isso

        Cada sinal acima vira uma lista de imóveis: `property_code` leva ao cadastro, e
        `car_property()` devolve o perímetro. Para repetir a análise em outro município ou
        outra UF, basta trocar os argumentos.
        """,
        None,
    ),
]

ANALISE = [
    (
        """
        # Onde a análise está parada

        Cadastrar foi a parte rápida: o país tem mais de 8,5 milhões de imóveis no CAR. A
        regularização depende do passo seguinte — o órgão estadual analisar o cadastro e o
        produtor responder ao que a análise pede. Este guia usa a coluna `condition`, a etapa
        da análise informada pelo Sicar, para mostrar onde cada UF está e quem espera por quem.

        Tudo aqui sai do resumo pré-calculado (`car_summary()`), em segundos, menos o mapa do
        fim, que lê duas colunas de um estado.

        ## As etapas

        O Sicar informa quinze situações de análise. Agrupadas em seis etapas:
        """,
        """
        import carbr

        STAGES = ["Aguardando análise", "Em análise", "Notificado, sem resposta",
                  "Respondeu, aguarda reanálise", "Analisado", "Cancelado"]


        def stage(condition):
            if condition.startswith("Cancelado"):
                return "Cancelado"
            if condition == "Aguardando análise":
                return "Aguardando análise"
            if condition == "Em análise":
                return "Em análise"
            if "aguardando atendimento a notificação" in condition:
                return "Notificado, sem resposta"
            if "após revisão" in condition:
                return "Respondeu, aguarda reanálise"
            return "Analisado"


        def by_stage(*by):
            df = carbr.car_summary(["condition", *by])
            df["stage"] = pd.Categorical(df["condition"].map(stage), STAGES)
            return df.groupby([*by, "stage"], observed=False)["properties"].sum().reset_index()


        national = by_stage()
        national["share"] = (100 * national["properties"] / national["properties"].sum()).round(1)

        national
        """,
    ),
    (
        """
        Sete em cada dez cadastros ainda não foram analisados. Dos que foram, a maior parte
        parou no passo seguinte: há mais imóveis notificados à espera de resposta do
        declarante do que imóveis com análise concluída.

        ## A fila não é a mesma em cada UF
        """,
        """
        palette = {"Aguardando análise": "#d9d9d9", "Em análise": "#9ecae1",
                   "Notificado, sem resposta": "#e8590c", "Respondeu, aguarda reanálise": "#fcc419",
                   "Analisado": "#2b8a3e", "Cancelado": "#868e96"}
        states = by_stage("state").pivot(index="state", columns="stage", values="properties")
        shares = states.div(states.sum(axis=1), axis=0).sort_values("Aguardando análise")

        ax = (100 * shares).plot.barh(stacked=True, figsize=(7, 6.8), width=0.8,
                                      color=[palette[s] for s in shares.columns])
        ax.set_title("Em que etapa da análise estão os imóveis de cada UF (%)", loc="left")
        ax.set_xlim(0, 100)
        ax.set_ylabel("")
        ax.legend(ncol=2, frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.05), fontsize=8)

        fig("etapas")
        """,
    ),
    (
        """
        Há três situações bem diferentes. Em parte dos estados quase nada foi analisado
        (cinza). Em alguns a análise andou e concluiu (verde). E em outros a análise andou,
        mas parou na notificação (laranja): o órgão fez a sua parte e a resposta não veio.
        """,
        """
        notified = states["Notificado, sem resposta"].sort_values(ascending=False).to_frame("properties")
        notified["share_of_state"] = (100 * shares["Notificado, sem resposta"]).round(1)
        top5 = 100 * notified["properties"].head(5).sum() / notified["properties"].sum()
        print(f"As cinco primeiras UFs concentram {top5:.0f}% das notificações sem resposta")

        notified.head(8)
        """,
    ),
    (
        "## Quem está sem responder",
        """
        waiting = by_stage("size_class")
        waiting = waiting[waiting["stage"] == "Notificado, sem resposta"].drop(columns="stage")
        waiting["share"] = (100 * waiting["properties"] / waiting["properties"].sum()).round(1)

        waiting
        """,
    ),
    (
        """
        Nove em cada dez são imóveis de até quatro módulos fiscais. É o público que menos tem
        acesso a técnico, a ferramenta de geoprocessamento e a quem explique o relatório da
        análise — e para quem a pendência no CAR pesa no crédito rural.

        ## A notificação envelhece

        Pelo ano de criação do cadastro, a resposta não chega com o tempo: de cada ano desde
        2015, entre um oitavo e um quinto dos cadastros está parado na notificação, e os mais
        antigos não estão em situação melhor.
        """,
        """
        years = by_stage("created_year").pivot(index="created_year", columns="stage", values="properties")

        ax = (years / 1e3).plot.bar(stacked=True, figsize=(7, 4), width=0.85, rot=0,
                                    color=[palette[s] for s in years.columns])
        ax.set_title("Etapa atual da análise, por ano de criação do cadastro", loc="left")
        ax.set_xlabel("")
        ax.set_ylabel("Milhares de imóveis")
        ax.legend(ncol=2, frameon=False, fontsize=8)

        fig("analise-anos")
        """,
    ),
    (
        """
        ## Onde, dentro de um estado

        O resumo vai até a UF. Para descer ao município, `car_tbl()` lê só as duas colunas
        necessárias do arquivo do estado. No Pará, a UF com mais notificações sem resposta:
        """,
        """
        para = carbr.car_tbl("PA").aggregate(
            "municipality_code, municipality, condition, count(*) AS n"
        ).df()
        para["notified"] = para["n"].where(para["condition"].map(stage) == "Notificado, sem resposta", 0)
        para = para.groupby(["municipality_code", "municipality"], as_index=False)[["n", "notified"]].sum()
        para = para.rename(columns={"n": "properties"})
        para["share"] = (100 * para["notified"] / para["properties"]).round(1)

        para.sort_values("notified", ascending=False).head(6)
        """,
    ),
    (
        "",
        """
        import geopandas as gpd

        mesh = gpd.read_file(
            "https://servicodados.ibge.gov.br/api/v3/malhas/estados/PA?intrarregiao=municipio"
            "&formato=application/vnd.geo%2Bjson&qualidade=intermediaria"
        )
        mesh["municipality_code"] = mesh["codarea"].astype(int)
        mesh = mesh.merge(para, on="municipality_code", how="left")

        ax = mesh.plot(column="share", cmap="Oranges", edgecolor="white", linewidth=0.2,
                       figsize=(7, 6.4), legend=True,
                       legend_kwds={"shrink": 0.5, "label": "Notificados, sem resposta (%)"},
                       missing_kwds={"color": "#d9d9d9"})
        ax.set_title("Pará: imóveis notificados que aguardam resposta do declarante\\n"
                     "Parcela dos imóveis de cada município", loc="left", fontsize=10)
        ax.set_axis_off()

        fig("para")
        """,
    ),
    (
        """
        É uma lista de onde um mutirão, um sindicato ou um serviço de atendimento ao produtor
        rende mais: municípios com muitos imóveis já analisados à espera de uma resposta que
        depende só de o declarante entender o que foi pedido.
        """,
        None,
    ),
]

PAGES = {
    "primeiros-passos.md": PRIMEIROS_PASSOS,
    "inconsistencias.md": INCONSISTENCIAS,
    "fila-da-analise.md": ANALISE,
}

if __name__ == "__main__":
    import sys

    for name in sys.argv[1:] or PAGES:
        page(name, PAGES[name])
