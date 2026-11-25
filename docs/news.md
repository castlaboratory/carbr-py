# Novidades

## 0.6.0

- `car_typology()` e `car_typology_groups()`: tipologia dos municípios em cinco grupos, pelo perfil
  do cadastro (porte dos imóveis, etapa da análise e sobreposição).

## 0.5.0

- `car_check()` passa a considerar a sobreposição com terras indígenas (Funai) e unidades de
  conservação (CNUC/MMA): mais de 1% da área em terra indígena ou em unidade de proteção integral
  leva o resultado a `"attention"`; unidade de uso sustentável é informada na nota. Colunas novas:
  `indigenous_share`, `strict_protection_share`, `sustainable_use_share` e `protected_area`.
- `car_quality()` e `car_quality_summary()` trazem essas parcelas, os nomes das áreas e as
  contagens por município.
- Servidor MCP: as mesmas informações em `imoveis_no_ponto`, `municipio` e `verificar_imoveis`.

## 0.4.0

- `car_quality()` e `car_quality_summary()`: indicadores de qualidade do cadastro, por imóvel e por
  município (sobreposição com outros imóveis e área fora do município declarado).
- Servidor MCP: `municipio` e `imoveis_no_ponto` passam a trazer os indicadores de qualidade.

## 0.3.0

- Servidor MCP (`carbr-mcp`, extra `mcp`): oito ferramentas de consulta ao CAR para assistentes.

## 0.2.0

- `car_check()`: verifica uma lista de códigos de imóvel de uma vez e resume o que consta de cada um
  (`ok`, `attention`, `blocked`, `not_found`, `invalid`).

## 0.1.3

- Júlia Nascimento Barreto entra na lista de autores. Sem mudança no código.
- README com o endereço da página de consulta no navegador.

## 0.1.2

- O repositório e o site mudaram para a organização `castlaboratory`.
- Sem mudança no código. README com o DOI do Zenodo e o aviso sobre a base normativa dos dados.

## 0.1.1

- Metadados de citação (`CITATION.cff`), para o arquivamento no Zenodo. Sem mudança no código.

## 0.1.0

- Primeira versão no PyPI: `car_catalog()`, `car_dictionary()`, `car_summary()`,
  `car_municipalities()`, `car_properties()`, `car_property()`, `car_at()`,
  `car_tbl()` e `car_cite()`.
- Dados das 27 UFs (8.578.061 imóveis), posição de 24 e 25/11/2026.
- `car_summary()` lê um resumo pré-calculado: totais nacionais em segundos.
- Guias novos: "Inconsistências do cadastro" e "Onde a análise está parada".
