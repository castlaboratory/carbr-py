"""A tiny publication on disk: six square properties in two municipalities."""

import hashlib
import json

import duckdb
import pandas as pd
import pytest
from shapely.geometry import MultiPolygon, box

import carbr


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def release(tmp_path):
    x = [-40.50, -40.48, -40.46, -35.00, -34.98, -40.50]
    y = [-9.40, -9.40, -9.40, -8.00, -8.00, -9.40]
    # The sixth property overlaps the first: a bigger square on the same corner.
    side = [0.01] * 5 + [0.05]
    mun = ["2611101"] * 3 + ["2611606"] * 2 + ["2611101"]
    props = pd.DataFrame({  # noqa: F841
        "property_code": [f"PE-{m}-{i:032X}" for i, m in enumerate(mun, 1)],
        "status_code": ["AT", "AT", "PE", "AT", "CA", "AT"],
        "status": ["active", "active", "pending", "active", "cancelled", "active"],
        "condition": "Aguardando análise",
        "property_type_code": "IRU",
        "property_type": "rural_property",
        "created_at": pd.Timestamp("2020-06-01", tz="UTC"),
        "area_ha": [10.0, 20.0, 30.0, 40.0, 50.0, 6000.0],
        "fiscal_modules": [0.2, 0.4, 0.6, 5.0, 6.0, 100.0],
        "size_class": ["small"] * 3 + ["medium"] * 2 + ["large"],
        "state": "PE",
        "municipality": ["Petrolina"] * 3 + ["Recife"] * 2 + ["Petrolina"],
        "municipality_code": [int(m) for m in mun],
        "registration_state": "PE",
        "lon": [a + s / 2 for a, s in zip(x, side)],
        "lat": [b + s / 2 for b, s in zip(y, side)],
        "geometry_valid": True,
        "xmin": x,
        "ymin": y,
        "xmax": [a + s for a, s in zip(x, side)],
        "ymax": [b + s for b, s in zip(y, side)],
        "geometry": [MultiPolygon([box(a, b, a + s, b + s)]).wkb for a, b, s in zip(x, y, side)],
    })
    (tmp_path / "properties" / "state=PE").mkdir(parents=True)
    (tmp_path / "municipalities").mkdir()
    f_props = tmp_path / "properties" / "state=PE" / "part-0.parquet"
    f_mun = tmp_path / "municipalities" / "state=PE.parquet"
    con = duckdb.connect()
    con.execute(f"COPY (SELECT * FROM props ORDER BY municipality_code) TO '{f_props}' (FORMAT parquet)")
    con.execute(f"""
        COPY (SELECT state, municipality_code, municipality, count(*) AS properties,
                count(*) FILTER (size_class = 'small') AS small_properties, sum(area_ha) AS area_ha,
                count(*) FILTER (status = 'active') AS active,
                count(*) FILTER (status = 'pending') AS pending,
                count(*) FILTER (status = 'suspended') AS suspended,
                count(*) FILTER (status = 'cancelled') AS cancelled,
                count(*) FILTER (NOT geometry_valid) AS invalid_geometries,
                min(xmin) AS xmin, min(ymin) AS ymin, max(xmax) AS xmax, max(ymax) AS ymax
              FROM props GROUP BY ALL) TO '{f_mun}' (FORMAT parquet)""")
    (tmp_path / "summary").mkdir()
    f_sum = tmp_path / "summary" / "state=PE.parquet"
    con.execute(f"""
        COPY (SELECT state, status, size_class, property_type, condition,
                year(created_at)::INTEGER AS created_year, count(*) AS properties,
                sum(area_ha) AS area_ha
              FROM props GROUP BY ALL) TO '{f_sum}' (FORMAT parquet)""")
    # Indicadores de qualidade: o 1º imóvel está inteiro dentro do 6º; o 5º é cancelado e fica de fora.
    quality = pd.DataFrame({  # noqa: F841
        "property_code": [props["property_code"][i] for i in (0, 1, 2, 5, 3)],
        "municipality_code": [2611101, 2611101, 2611101, 2611101, 2611606],
        "overlap_count": [1, 0, 0, 1, 0],
        "overlap_share": [1.0, 0.0, 0.0, 0.04, 0.0],
        "outside_share": [0.0, 0.0, 0.6, 0.0, 0.0],
        # O 2º imóvel fica em terra indígena; o 3º, em parte num parque; o 6º, inteiro numa APA.
        "indigenous_share": [0.0, 0.8, 0.0, 0.0, 0.0],
        "strict_protection_share": [0.0, 0.0, 0.3, 0.0, 0.0],
        "sustainable_use_share": [0.0, 0.0, 0.0, 1.0, 0.0],
        "indigenous_land": [None, "Terra Teste", None, None, None],
        "conservation_unit": [None, None, "Parque Teste", "APA Teste", None],
        "conservation_category": [None, None, "Parque", "Área de Proteção Ambiental", None],
        # O imóvel de Recife (o último aqui) tem dois embargos do Ibama, sobre 40% da área.
        "embargo_count": [0, 0, 0, 0, 2],
        "embargo_share": [0.0, 0.0, 0.0, 0.0, 0.4],
    })
    (tmp_path / "quality").mkdir()
    (tmp_path / "quality-municipalities").mkdir()
    f_q = tmp_path / "quality" / "state=PE.parquet"
    f_qm = tmp_path / "quality-municipalities" / "state=PE.parquet"
    con.execute(f"COPY (SELECT * FROM quality ORDER BY municipality_code, property_code) TO '{f_q}' (FORMAT parquet)")
    con.execute(f"""
        COPY (SELECT 'PE' AS state, q.municipality_code, count(*) AS properties,
                count(*) FILTER (overlap_share > 0.01) AS overlapping,
                count(*) FILTER (overlap_share > 0.5) AS overlapping_half,
                sum(p.area_ha * overlap_share) AS overlap_ha,
                count(*) FILTER (outside_share > 0.5) AS outside_half,
                sum(p.area_ha * outside_share) AS outside_ha,
                count(*) FILTER (indigenous_share > 0.01) AS indigenous,
                sum(p.area_ha * indigenous_share) AS indigenous_ha,
                count(*) FILTER (strict_protection_share > 0.01) AS strict_protection,
                sum(p.area_ha * strict_protection_share) AS strict_protection_ha,
                count(*) FILTER (sustainable_use_share > 0.01) AS sustainable_use,
                sum(p.area_ha * sustainable_use_share) AS sustainable_use_ha,
                count(*) FILTER (embargo_count > 0) AS embargoed,
                sum(p.area_ha * embargo_share) AS embargo_ha
              FROM quality q JOIN props p USING (property_code) GROUP BY ALL) TO '{f_qm}' (FORMAT parquet)""")
    (tmp_path / "typology").mkdir()
    f_typ = tmp_path / "typology" / "municipalities.parquet"
    con.execute(f"""
        COPY (SELECT * FROM (VALUES
                ('PE', 2611101, 'Petrolina', 'overlapping', 'Muita sobreposição', 4, 0.75, 0.9, 0.75, 0.0, 0.25, 0.5, 0.4),
                ('PE', 2611606, 'Recife', 'few', 'Poucos cadastros', 1, 1.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.01))
              t(state, municipality_code, municipality, typology, typology_label, properties, small_share,
                large_area_share, waiting_share, notified_share, analysed_share, overlap_share, coverage))
        TO '{f_typ}' (FORMAT parquet)""")
    (tmp_path / "catalog.json").write_text(json.dumps({
        "version": "2026-01-01",
        "source": {"name": "teste"},
        "states": {"PE": {"properties": 6, "municipalities": 2, "quality": {
            "invalid_geometries": 0, "null_geometries": 0, "registered_in_other_state": 0}}},
        "files": [
            {"path": "properties/state=PE/part-0.parquet", "sha256": _sha(f_props)},
            {"path": "municipalities/state=PE.parquet", "sha256": _sha(f_mun)},
            {"path": "summary/state=PE.parquet", "sha256": _sha(f_sum)},
            {"path": "quality/state=PE.parquet", "sha256": _sha(f_q)},
            {"path": "quality-municipalities/state=PE.parquet", "sha256": _sha(f_qm)},
            {"path": "typology/municipalities.parquet", "sha256": _sha(f_typ)},
        ],
        "typology": {"of": "2026-01-01", "groups": [
            {"code": "overlapping", "label": "Muita sobreposição", "description": "Teste.",
             "municipalities": 1, "properties": 4},
            {"code": "few", "label": "Poucos cadastros", "description": "Teste.",
             "municipalities": 1, "properties": 1}]},
    }))
    (tmp_path / "dictionary.json").write_text(json.dumps(
        [{"column": "property_code", "sicar_name": "cod_imovel", "description": "Código"}]))
    carbr.set_verbose(False)
    carbr.set_base_url(tmp_path)
    yield tmp_path
    carbr.set_base_url(None)
