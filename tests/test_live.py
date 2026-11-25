import pytest

import carbr


@pytest.mark.live
def test_large_properties_of_petrolina_from_the_public_bucket():
    carbr.set_base_url(None)
    x = carbr.car_properties("PE", municipality="Petrolina", size_class="large", geometry=False)
    assert len(x) > 0
    assert set(x["municipality"]) == {"Petrolina"}
