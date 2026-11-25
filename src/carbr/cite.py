"""How to cite the data."""

from __future__ import annotations


def citation(version: str) -> str:
    return (
        "Serviço Florestal Brasileiro. Sistema Nacional de Cadastro Ambiental Rural "
        "(Sicar): imóveis rurais. Dados organizados pelo CastLab/UFPE (pacote carbr), "
        f"versão {version}."
    )


def car_cite() -> str | None:
    """Imprime e devolve a citação da versão publicada.

    A origem dos dados é o Sicar, do Serviço Florestal Brasileiro.
    """
    from . import _client

    cat = _client.catalog_json()
    if cat is None:
        return None
    text = citation(cat["version"])
    print(text)
    return text
