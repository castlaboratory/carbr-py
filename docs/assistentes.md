# Assistentes (MCP)

O `carbr` traz um servidor do [Model Context Protocol](https://modelcontextprotocol.io) (MCP). Com
ele, um assistente compatível responde perguntas sobre o CAR consultando os dados reais, e cita a
fonte e a data da publicação, em vez de estimar.

- "Quantos imóveis foram notificados e não responderam em Marabá?"
- "O que está declarado no ponto de longitude -47,9 e latitude -15,8?"
- "Verifique estes códigos de imóvel e diga quais têm pendência."
- "Em que etapa da análise estão os imóveis do Pará?"

O servidor roda na máquina de quem usa, lê a mesma publicação dos pacotes e não envia nada a
terceiros além das leituras dos arquivos públicos.

## Instalação

```bash
pip install "carbr[mcp]"
carbr-mcp          # fala MCP pela entrada e saída padrão; é o assistente quem o inicia
```

Com o [uv](https://docs.astral.sh/uv/), nem é preciso instalar antes:

```bash
uvx --from "carbr[mcp]" carbr-mcp
```

## Configuração no assistente

A maioria dos clientes aceita um bloco como este no arquivo de configuração de servidores MCP:

```json
{
  "mcpServers": {
    "car": {
      "command": "uvx",
      "args": ["--from", "carbr[mcp]", "carbr-mcp"]
    }
  }
}
```

No Claude Code:

```bash
claude mcp add car -- uvx --from "carbr[mcp]" carbr-mcp
```

Para apontar o servidor para um espelho ou para uma cópia local da publicação, defina a variável
de ambiente `CAR_URL` no mesmo bloco.

## Ferramentas

| Ferramenta | O que responde |
|---|---|
| `catalogo` | UFs publicadas, número de imóveis e data dos dados |
| `dicionario` | O que significa cada coluna |
| `resumo` | Totais de imóveis e de área por UF, situação, porte, tipo, etapa e ano de criação |
| `etapas_da_analise` | Quantos imóveis estão em cada etapa da análise, no país ou em UFs |
| `municipios` | Os municípios de uma UF, ordenados por imóveis, área, pendentes etc. |
| `municipio` | Um município em detalhe, com as etapas da análise |
| `imoveis_no_ponto` | Os imóveis declarados numa coordenada, com aviso de sobreposição |
| `verificar_imoveis` | Triagem de até 200 códigos de imóvel por chamada |

Toda resposta traz a data da publicação (`versao`) e a citação (`fonte`). O servidor também
orienta o assistente a lembrar que o cadastro é autodeclarado, que constar no CAR não comprova
posse nem propriedade, e que esta é uma republicação sem caráter oficial.

## Limites

- As ferramentas devolvem atributos, não perímetros: para mapas, use os pacotes ou a
  [página de consulta](https://car.castlab.org).
- Não há ferramenta de consulta livre. O assistente só faz as perguntas da tabela acima.
- As respostas são tão atuais quanto a publicação, que é copiada do Sicar toda semana.
