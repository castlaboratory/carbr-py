"""Precompila a página da documentação que lê dados reais.

Mesma ideia da vinheta do pacote R: os exemplos rodam aqui, contra a
publicação real, e o Markdown que o site publica é gravado com a saída e a
figura embutidas. O build do site, então, não precisa de rede. Rode da raiz
do repositório quando um exemplo ou os dados mudarem e commite o resultado:

    python docs/precompile.py
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

        Os filtros de `car_properties()` são aplicados antes da leitura. Aqui, os imóveis
        médios e grandes de Petrolina, em Pernambuco — algumas centenas, de um arquivo com
        mais de 400 mil. Com o extra `geo` instalado, o resultado é um GeoDataFrame em
        SIRGAS 2000.
        """,
        """
        petrolina = carbr.car_properties(
            "PE", municipality="Petrolina", size_class=["medium", "large"]
        )

        petrolina[["property_code", "status", "area_ha", "fiscal_modules", "size_class"]].head(6)
        """,
    ),
    (
        "",
        """
        ax = petrolina.plot(
            column="size_class", categorical=True, legend=True, figsize=(7, 5.5),
            cmap="Greens", edgecolor="white", linewidth=0.2,
            legend_kwds={"loc": "lower left", "frameon": False},
        )
        ax.set_title("Imóveis médios e grandes no CAR — Petrolina, Pernambuco")
        ax.set_axis_off()

        fig("petrolina")
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


if __name__ == "__main__":
    page("primeiros-passos.md", PRIMEIROS_PASSOS)
