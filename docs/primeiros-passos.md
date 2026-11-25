# Primeiros passos

O **Cadastro Ambiental Rural (CAR)** é o registro público eletrônico dos imóveis
rurais do país, criado pelo Código Florestal (Lei nº 12.651/2012) e mantido no Sicar
pelo Serviço Florestal Brasileiro. O `carbr` lê uma republicação dos dados públicos
do cadastro em GeoParquet: cada consulta transfere só os trechos do arquivo de que
precisa, sem baixar a base de um estado inteiro e sem passar pelos servidores do Sicar.

| Função | Para quê |
|---|---|
| `car_catalog()` | O que está publicado |
| `car_dictionary()` | O que cada coluna significa |
| `car_municipalities()` | Resumo por município |
| `car_properties()` | Imóveis de uma UF, com filtros |
| `car_property()` | Um imóvel pelo código |
| `car_at()` | Imóveis que contêm um ponto |
| `car_tbl()` | Relação preguiçosa do DuckDB |
| `car_cite()` | Como citar |

## O que está publicado

`car_catalog()` traz uma linha por UF, com o número de imóveis e os indicadores de
qualidade da carga. A versão é a data em que os dados foram lidos do Sicar.

```python
import carbr

cat = carbr.car_catalog()
print(cat.T)

cat.attrs["version"]
```

```text
                                0
state                          PE
properties                 436190
municipalities                184
invalid_geometries             50
null_geometries                 0
registered_in_other_state       7
2026-11-25
```

O dicionário de dados diz o que é cada coluna e qual era o seu nome no Sicar.

```python
print(carbr.car_dictionary().to_string(index=False))
```

```text
            column         sicar_name                                                                      description
     property_code         cod_imovel                       Código do imóvel no CAR (UF-município IBGE-identificador).
       status_code      status_imovel          Situação do cadastro: AT ativo, PE pendente, SU suspenso, CA cancelado.
            status                NaN                       Situação do cadastro por extenso, derivada de status_code.
         condition           condicao              Etapa da análise em que o cadastro está, como informada pelo Sicar.
property_type_code        tipo_imovel        IRU imóvel rural, AST assentamento, PCT povos e comunidades tradicionais.
     property_type                NaN                      Tipo do imóvel por extenso, derivado de property_type_code.
        created_at        dat_criacao                                        Data e hora de criação do cadastro (UTC).
           area_ha               area                                           Área declarada do imóvel, em hectares.
    fiscal_modules           m_fiscal                                            Área em módulos fiscais do município.
        size_class                NaN        small até 4 módulos fiscais, medium acima de 4 até 15, large acima de 15.
             state                 uf                                                UF onde o imóvel está localizado.
      municipality          municipio                                         Município onde o imóvel está localizado.
 municipality_code cod_municipio_ibge                                            Código IBGE do município (7 dígitos).
registration_state                NaN                           UF do prefixo de property_code; pode diferir de state.
               lon                NaN                            Longitude de um ponto dentro do imóvel (SIRGAS 2000).
               lat                NaN                             Latitude de um ponto dentro do imóvel (SIRGAS 2000).
    geometry_valid                NaN                     Se a geometria declarada é válida (sem autointerseção etc.).
              xmin                NaN Limite oeste do retângulo envolvente do imóvel, para filtro espacial na leitura.
              ymin                NaN                                              Limite sul do retângulo envolvente.
              xmax                NaN                                            Limite leste do retângulo envolvente.
              ymax                NaN                                            Limite norte do retângulo envolvente.
          geometry    geo_area_imovel         Perímetro declarado do imóvel, WKB, EPSG:4674. Nulo se o Sicar não traz.
```

## Resumo por município

Para contagens, não é preciso ler os imóveis: o resumo municipal é um arquivo
pequeno, guardado em cache.

```python
mun = carbr.car_municipalities("PE")

mun.sort_values("properties", ascending=False)[
    ["municipality", "properties", "small_properties", "area_ha", "pending"]
].head(6)
```

```text
    municipality  properties  small_properties      area_ha  pending
12     Araripina       15663             15625  187423.2964        1
112     Ouricuri       14200             14182  219156.7227        6
124    Petrolina       10918             10799  411153.0978       11
29        Buíque        9734              9651  109496.3160        3
21        Bodocó        7271              7236  147941.1297        2
55      Custódia        6598              6540  153165.5342        1
```

## Imóveis de um município

Os filtros de `car_properties()` são aplicados antes da leitura. Aqui, os imóveis
médios e grandes de Petrolina — algumas centenas, de um arquivo com mais de 400 mil.
Com o extra `geo` instalado, o resultado é um GeoDataFrame em SIRGAS 2000.

```python
petrolina = carbr.car_properties(
    "PE", municipality="Petrolina", size_class=["medium", "large"]
)

petrolina[["property_code", "status", "area_ha", "fiscal_modules", "size_class"]].head(6)
```

```text
                                 property_code  status   area_ha  fiscal_modules size_class
0  PE-2611101-111805B2DFBA4AF7B2BE2458D8CE27FD  active  652.4604         11.6057     medium
1  PE-2611101-B095898582B2428EBDD3200C7CA25992  active  245.1787          4.4578     medium
2  PE-2611101-69A386072C4E4D3189F24800452142C1  active  245.5974          4.4654     medium
3  PE-2611101-C283CE3BF96A440DBE8D9026B91FC2C1  active  534.9252          9.7259     medium
4  PE-2611101-ADEC18D9D8EA4CB6B5A3F56074EA0B63  active  432.0721          7.8559     medium
5  PE-2611101-03F43B55FBE64453A6F2F740902D02CB  active  803.5238         14.6095     medium
```

```python
ax = petrolina.plot(
    column="size_class", categorical=True, legend=True, figsize=(7, 5.5),
    cmap="Greens", edgecolor="white", linewidth=0.2,
    legend_kwds={"loc": "lower left", "frameon": False},
)
ax.set_title("Imóveis médios e grandes no CAR — Petrolina, Pernambuco")
ax.set_axis_off()

fig("petrolina")
```

![petrolina](assets/petrolina.png)

O município pode ser dado pelo nome (sem diferenciar maiúsculas nem acentos) ou pelo
código IBGE de sete dígitos. Os outros filtros são `status`, `property_type` e `bbox`.

## Sem a geometria

A geometria é a parte pesada do arquivo. Quando só os atributos interessam,
`geometry=False` deixa de transferi-la. Os cadastros pendentes de Pernambuco, por
município:

```python
pending = carbr.car_properties("PE", status="pending", geometry=False)

pending["municipality"].value_counts().head(6)
```

```text
municipality
Carnaubeira da Penha    145
Floresta                104
Águas Belas              59
Pesqueira                35
Jatobá                   28
Tupanatinga              23
Name: count, dtype: int64
```

## Que imóveis estão declarados aqui?

`car_at()` devolve os imóveis que contêm um ponto. Como o cadastro é autodeclarado,
sobreposições são comuns e o resultado pode ter mais de uma linha.

```python
here = carbr.car_at(lon=-40.5, lat=-9.2, geometry=False)

print(here[["property_code", "municipality", "area_ha", "status", "condition"]].T)
```

```text
                                                         0
property_code  PE-2611101-588BC484570D440484F527F07DF5AFFA
municipality                                     Petrolina
area_ha                                         81578.6042
status                                              active
condition                               Aguardando análise
```

## Um imóvel pelo código

```python
one = carbr.car_property("PE-2611101-588BC484570D440484F527F07DF5AFFA", geometry=False)

print(one.T)
```

```text
                                                              0
property_code       PE-2611101-588BC484570D440484F527F07DF5AFFA
status_code                                                  AT
status                                                   active
condition                                    Aguardando análise
property_type_code                                          AST
property_type                                        settlement
created_at                     2026-02-13 13:21:54.947000-03:00
area_ha                                              81578.6042
fiscal_modules                                           0.5209
size_class                                                small
state                                                        PE
municipality                                          Petrolina
municipality_code                                       2611101
registration_state                                           PE
lon                                                  -40.550236
lat                                                   -9.131521
geometry_valid                                             True
xmin                                                 -40.824844
ymin                                                  -9.398057
xmax                                                 -40.298282
ymax                                                  -8.864982
```

## Consultas próprias

`car_tbl()` devolve uma relação preguiçosa do DuckDB sobre os arquivos publicados.
Nada é lido até o `.df()`, e a agregação roda sobre o arquivo remoto lendo só as
colunas usadas.

```python
carbr.car_tbl("PE").aggregate(
    "size_class, count(*) AS properties, round(sum(area_ha)) AS area_ha"
).order("properties DESC").df()
```

```text
  size_class  properties    area_ha
0      small      429650  5934124.0
1     medium        5167  1272210.0
2      large        1373  1229005.0
```

## Como citar

```python
text = carbr.car_cite()
```

```text
Serviço Florestal Brasileiro. Sistema Nacional de Cadastro Ambiental Rural (Sicar): imóveis rurais. Dados organizados pelo CastLab/UFPE (pacote carbr), versão 2026-11-25.
```

## Endereço dos dados e cache

O pacote lê de um bucket público. Para usar um espelho compatível com S3 ou uma cópia
local da publicação, chame `carbr.set_base_url()` ou defina a variável de ambiente
`CAR_URL`. O catálogo e o resumo municipal ficam em cache em `carbr.car_cache_dir()`;
os imóveis nunca são copiados para o disco.
