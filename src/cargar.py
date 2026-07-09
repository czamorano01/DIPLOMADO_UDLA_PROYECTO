"""
cargar.py

Funciones ligeras de carga/guardado para el pipeline (exportar DataFrames a CSV).
"""
from __future__ import annotations

from pathlib import Path
import pandas as pd

from src.logging_config import configurar_logging

logger = configurar_logging(__name__)


def guardar_dataframe_csv(ruta: Path, df: pd.DataFrame, index: bool = False) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(ruta, index=index)
    logger.info("Guardado CSV: %s (%s filas)", ruta, len(df))
