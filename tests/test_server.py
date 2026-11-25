import pytest

pytest.importorskip("mcp")

from carbr import server  # noqa: E402


def test_tools_answer_from_the_publication(release):
    cat = server.catalogo()
    assert cat["total_de_imoveis"] == 6 and cat["versao"] == "2026-01-01" and "Sicar" in cat["fonte"]

    by_size = server.resumo(["size_class"])
    assert {r["size_class"]: r["properties"] for r in by_size["linhas"]} == {"large": 1, "medium": 2, "small": 3}
    assert server.resumo()["linhas"] == [{"properties": 6, "area_ha": 6150.0}]

    stages = server.etapas_da_analise(["PE"])
    assert stages["total"] == 6 and stages["etapas"][0]["etapa"] == "waiting"
    assert stages["etapas"][0]["rotulo"] == "Aguardando análise" and stages["etapas"][0]["percentual"] == 100.0

    towns = server.municipios("PE", limite=1)
    assert towns["total_de_municipios"] == 2 and towns["municipios"][0]["municipality"] == "Petrolina"

    town = server.municipio("pe", "PETROLINA")
    assert town["encontrado"] and town["municipio"]["properties"] == 4
    assert town["etapas"][0]["properties"] == 4
    assert server.municipio("PE", "Petro")["encontrado"] is False

    here = server.imoveis_no_ponto(-40.495, -9.395)
    assert here["quantidade"] == 2 and here["sobreposicao"] is True
    assert {r["area_ha"] for r in here["imoveis"]} == {10.0, 6000.0}
    assert all(isinstance(r["created_at"], str) for r in here["imoveis"])
    assert {r["area_ha"]: r["overlap_share"] for r in here["imoveis"]} == {10.0: 1.0, 6000.0: 0.04}
    assert town["qualidade"]["overlapping_half"] == 1
    assert town["tipologia"]["typology"] == "overlapping"
    assert town["qualidade"]["indigenous"] == 1 and town["qualidade"]["strict_protection"] == 1
    assert town["qualidade"]["percentual_com_mais_da_metade_sobreposta"] == 25.0

    checked = server.verificar_imoveis([f"PE-2611101-{1:032X}", f"PE-2611606-{5:032X}", "abc"])
    assert checked["resultado"] == {"ok": 1, "blocked": 1, "invalid": 1}
    assert checked["imoveis"][2]["state"] is None
    with pytest.raises(ValueError):
        server.verificar_imoveis(["x"] * 201)
    assert server.dicionario()["colunas"][0]["column"] == "property_code"


@pytest.mark.anyio
async def test_the_server_speaks_mcp(release):
    from mcp import Client

    async with Client(server.build()) as client:
        tools = await client.list_tools()
        names = {tool.name for tool in tools.tools}
        assert names == {f.__name__ for f in server.TOOLS}
        assert all(tool.description for tool in tools.tools)
        result = await client.call_tool("imoveis_no_ponto", {"lon": -40.495, "lat": -9.395})
        assert not result.is_error
        assert result.structured_content["quantidade"] == 2


@pytest.fixture
def anyio_backend():
    return "asyncio"
