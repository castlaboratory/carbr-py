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
