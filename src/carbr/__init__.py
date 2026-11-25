"""carbr — imóveis do Cadastro Ambiental Rural (CAR) no Python.

Os imóveis rurais declarados no CAR, republicados do serviço público do Sicar
em GeoParquet. As consultas por UF, município, situação, porte, retângulo,
ponto ou código leem do arquivo remoto só os trechos de que precisam: não é
preciso baixar a base inteira.

Quick start
-----------
>>> import carbr
>>> carbr.car_catalog()                                          # doctest: +SKIP
>>> carbr.car_summary(["state", "size_class"])                   # doctest: +SKIP
>>> carbr.car_properties("PE", municipality="Petrolina")         # doctest: +SKIP
>>> carbr.car_at(lon=-40.5, lat=-9.2)                            # doctest: +SKIP
"""

from __future__ import annotations

from ._client import (
    CarError,
    CarWarning,
    ConfigError,
    IntegrityError,
    set_base_url,
    set_timeout,
)
from ._client import cache_dir as car_cache_dir
from ._client import clear_cache as car_cache_clear
from ._msg import set_verbose
from .cite import car_cite
from .data import (
    car_at,
    car_catalog,
    car_check,
    car_dictionary,
    car_municipalities,
    car_properties,
    car_property,
    car_summary,
    car_tbl,
)

__version__ = "0.3.0"

__all__ = [
    "CarError",
    "CarWarning",
    "ConfigError",
    "IntegrityError",
    "car_at",
    "car_cache_clear",
    "car_cache_dir",
    "car_catalog",
    "car_check",
    "car_cite",
    "car_dictionary",
    "car_municipalities",
    "car_properties",
    "car_property",
    "car_summary",
    "car_tbl",
    "set_base_url",
    "set_timeout",
    "set_verbose",
]
