import geopandas as gpd
import pandas as pd
import pytest

import carbr


def test_catalogue_dictionary_and_municipal_summary(release):
    cat = carbr.car_catalog()
    assert list(cat["state"]) == ["PE"]
    assert cat["properties"].iloc[0] == 6
    assert cat.attrs["version"] == "2026-01-01"
    assert "2026-01-01" in cat.attrs["citation"]
    assert list(carbr.car_dictionary()["sicar_name"]) == ["cod_imovel"]
    mun = carbr.car_municipalities("PE")
    assert list(mun["municipality"]) == ["Petrolina", "Recife"]
    assert list(mun["properties"]) == [4, 2]


def test_summary_aggregates_the_precomputed_table(release):
    by_size = carbr.car_summary("size_class")
    assert list(by_size["size_class"]) == ["large", "medium", "small"]
    assert list(by_size["properties"]) == [1, 2, 3]
    assert list(by_size["area_ha"]) == [6000, 90, 60]
    total = carbr.car_summary(None)
    assert total.shape == (1, 2) and total["properties"].iloc[0] == 6
    two = carbr.car_summary(["state", "status"], state="PE")
    assert list(two.columns) == ["state", "status", "properties", "area_ha"]
    assert two["properties"].sum() == 6
    assert list(carbr.car_summary("created_year")["created_year"]) == [2020]
    with pytest.raises(ValueError):
        carbr.car_summary("municipality")


def test_properties_filters(release):
    assert len(carbr.car_properties("PE", geometry=False)) == 6
    assert len(carbr.car_properties("pe", municipality="PETROLINA", geometry=False)) == 4
    assert len(carbr.car_properties("PE", municipality=2611606, geometry=False)) == 2
    one = carbr.car_properties("PE", municipality="2611606", status="active", geometry=False)
    assert len(one) == 1
    assert list(carbr.car_properties("PE", size_class="large", geometry=False)["area_ha"]) == [6000]
    assert len(carbr.car_properties("PE", bbox=(-35.1, -8.1, -34.9, -7.9), geometry=False)) == 2
    assert len(carbr.car_properties("PE", status="suspended", geometry=False)) == 0


def test_geometry_is_a_geodataframe_in_sirgas_2000_or_left_out(release):
    x = carbr.car_properties("PE", municipality="Recife")
    assert isinstance(x, gpd.GeoDataFrame)
    assert x.crs.to_epsg() == 4674
    assert x.geometry.is_valid.all()
    assert "geometry" not in carbr.car_properties("PE", geometry=False).columns


def test_property_by_code(release):
    assert list(carbr.car_property(f"PE-2611606-{4:032X}", geometry=False)["area_ha"]) == [40]
    assert len(carbr.car_property(f"PE-2611606-{99:032X}", geometry=False)) == 0
    # The municipality in the code is a shortcut, not a requirement.
    assert len(carbr.car_property(f"PE-2600054-{4:032X}", geometry=False)) == 0
    with pytest.raises(ValueError):
        carbr.car_property("abc")


def test_at_returns_every_property_that_contains_the_point(release):
    both = carbr.car_at(-40.495, -9.395)
    assert isinstance(both, gpd.GeoDataFrame)
    assert set(both["area_ha"]) == {10, 6000}
    assert len(carbr.car_at(-38, -8)) == 0
    flat = carbr.car_at(-40.495, -9.395, geometry=False)
    assert isinstance(flat, pd.DataFrame) and "geometry" not in flat.columns


def test_tbl_is_lazy(release):
    n = carbr.car_tbl("PE").aggregate("size_class, count(*) AS n").df()
    assert n["n"].sum() == 6
    assert carbr.car_tbl() is not None


def test_bad_arguments(release):
    with pytest.raises(ValueError, match="not in this publication"):
        carbr.car_properties("SP")
    with pytest.raises(ValueError, match="not found"):
        carbr.car_properties("PE", municipality="Atlântida")
    with pytest.raises(ValueError):
        carbr.car_properties("PE", status="ok")
    with pytest.raises(ValueError):
        carbr.car_properties("PE", bbox=(1, 2))


def test_missing_publication_warns_and_returns_the_empty_schema(tmp_path):
    carbr.set_base_url(tmp_path / "nao-existe")
    with pytest.warns(carbr.CarWarning):
        out = carbr.car_properties("PE", geometry=False)
    assert len(out) == 0 and "property_code" in out.columns
    with pytest.warns(carbr.CarWarning):
        assert len(carbr.car_catalog()) == 0
    carbr.set_base_url(None)


def test_file_updated_in_place_is_accepted_after_rereading_the_catalogue(release, tmp_path, monkeypatch):
    import hashlib
    import json
    import shutil
    from urllib.parse import unquote

    import duckdb

    from carbr import _client

    cache = tmp_path / "cache"
    monkeypatch.setenv("CAR_CACHE_DIR", str(cache))
    monkeypatch.setattr(_client, "_MAX_TRIES", 1)

    class Response:
        def __init__(self, file):
            self.status_code, self.content = 200, file.read_bytes()

    def get(url, **kwargs):
        return Response(release / unquote(url.removeprefix("https://car.test/current/")))

    monkeypatch.setattr(_client.requests, "get", get)
    carbr.set_base_url("https://car.test/current")
    assert list(carbr.car_municipalities("PE")["properties"]) == [4, 2]

    # The publication changes: new file, new catalogue; the cached catalogue is stale.
    f_mun = release / "municipalities" / "state=PE.parquet"
    duckdb.connect().execute(
        f"COPY (SELECT * REPLACE (properties + 1 AS properties) FROM read_parquet('{f_mun}')) "
        f"TO '{f_mun}.new' (FORMAT parquet)"
    )
    shutil.move(f"{f_mun}.new", f_mun)
    cat = json.loads((release / "catalog.json").read_text())
    cat["files"][1]["sha256"] = hashlib.sha256(f_mun.read_bytes()).hexdigest()
    (release / "catalog.json").write_text(json.dumps(cat))
    shutil.rmtree(cache / "2026-01-01")
    assert list(carbr.car_municipalities("PE")["properties"]) == [5, 3]

    # A file that matches no catalogue is still refused.
    f_mun.write_bytes(bytes(range(10)))
    shutil.rmtree(cache / "2026-01-01")
    with pytest.raises(carbr.IntegrityError):
        carbr.car_municipalities("PE")


def test_check_classifies_a_batch_of_codes(release):
    codes = [
        f"PE-2611101-{3:032X}",      # pending
        "not a code",
        f"pe-2611606-{5:032X}",      # cancelled, lower case
        f"PE-2611606-{99:032X}",     # not in the publication
        f"PE-2611101-{1:032X}",      # active
        f"PE-2600054-{4:032X}",      # another municipality in the code
        f"SP-3550308-{1:032X}",      # a state that is not published
    ]
    out = carbr.car_check([*codes, codes[0]])
    assert len(out) == 7
    assert list(out["property_code"]) == [c.upper() for c in codes]
    assert list(out["check"]) == ["attention", "invalid", "blocked", "not_found", "ok", "not_found", "not_found"]
    assert list(out["stage"].iloc[[0, 4]]) == ["waiting", "waiting"]
    assert list(out["area_ha"].iloc[[0, 2, 4]]) == [30, 50, 10]
    assert out["state"].iloc[[1, 3, 5, 6]].isna().all()
    assert "cancelado" in out["note"].iloc[2]
    assert list(out.columns) == ["property_code", "check", "note", "stage", "status", "condition",
                                 "property_type", "size_class", "area_ha", "fiscal_modules", "state",
                                 "municipality", "created_at"]
    assert len(carbr.car_check([])) == 0
