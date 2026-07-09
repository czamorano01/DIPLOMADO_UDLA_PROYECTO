"""
Compatibilidad: `src.etl` re-exporta funciones desde los módulos
`src.extraer`, `src.transformar` y `src.cargar` para mantener la API
existente mientras el código queda dividido en responsabilidades.
"""

from src.extraer import cargar_tabla, cargar_todas_las_tablas  # noqa: F401
from src.transformar import (
    validar_calidad,
    validar_todas,
    construir_centroides_geo,
    haversine_km,
    construir_dataset_maestro,
)  # noqa: F401
from src.cargar import guardar_dataframe_csv  # noqa: F401

__all__ = [
    "cargar_tabla",
    "cargar_todas_las_tablas",
    "validar_calidad",
    "validar_todas",
    "construir_centroides_geo",
    "haversine_km",
    "construir_dataset_maestro",
    "guardar_dataframe_csv",
]
