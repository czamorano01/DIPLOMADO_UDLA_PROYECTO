"""
extraer.py

Funciones de extracción / lectura de archivos CSV con manejo tolerante
de `parse_dates` y logging.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pandas as pd

from src.logging_config import configurar_logging

logger = configurar_logging(__name__)


def _intentar_leer_csv(ruta: Path, **kwargs) -> pd.DataFrame:
    """Intentos seguros de lectura: normal, con encoding BOM y con separador ';' si hace falta."""
    try:
        return pd.read_csv(ruta, **kwargs)
    except Exception:
        # primer fallback: intentar con utf-8-sig (BOM)
        try:
            return pd.read_csv(ruta, encoding="utf-8-sig", **kwargs)
        except Exception:
            # último intento: probar separador ';' que aparece en algunos CSV locales
            return pd.read_csv(ruta, encoding="utf-8-sig", sep=";", **{k: v for k, v in kwargs.items() if k != 'sep'})


def _verificar_archivo_texto(ruta: Path, sample_bytes: int = 1024) -> None:
    """Verifica de forma heurística que el archivo parezca un CSV de texto.

    Lanza `ValueError` con mensaje explicativo si detecta muchos bytes nulos
    (suele indicar archivo corrupto o placeholder de OneDrive "online-only").
    """
    try:
        b = ruta.read_bytes()[:sample_bytes]
    except Exception:
        return
    if not b:
        return
    # proporción de bytes nulos
    nul_ratio = b.count(b"\x00") / len(b)
    if nul_ratio > 0.1:
        raise ValueError(
            f"El archivo {ruta} parece binario o estar corrupto (bytes nulos={nul_ratio:.2f}). "
            "Si usas OneDrive, marca 'Siempre mantener en este dispositivo' o descarga el archivo localmente."
        )


def cargar_tabla(ruta: Path, nombre: str, parse_dates: list[str] | None = None) -> pd.DataFrame:
    """Carga un CSV con manejo de errores y convierte columnas de fecha si faltan en header.

    - Intenta `pd.read_csv(..., parse_dates=...)`.
    - Si Pandas levanta ValueError por columnas faltantes en `parse_dates`, lee sin esa opción
      y convierte manualmente las columnas existentes con `pd.to_datetime(errors='coerce')`.
    """
    # Verificación heurística previa
    _verificar_archivo_texto(ruta)

    try:
        df = _intentar_leer_csv(ruta, parse_dates=parse_dates)
    except FileNotFoundError:
        logger.error("No se encontró el archivo esperado: %s", ruta)
        raise
    except pd.errors.EmptyDataError:
        logger.error("El archivo %s está vacío o corrupto", ruta)
        raise
    except ValueError as e:
        # Manejo específico de columnas faltantes en parse_dates
        msg = str(e)
        if "Missing column provided to 'parse_dates'" in msg:
            logger.warning("Columnas indicadas en parse_dates no están en el header de %s. Reintentando sin parse_dates", ruta)
            df = _intentar_leer_csv(ruta)
            if parse_dates:
                for col in parse_dates:
                    if col in df.columns:
                        df[col] = pd.to_datetime(df[col], errors="coerce")
        else:
            logger.exception("Error inesperado cargando %s", ruta)
            raise
    except Exception:
        logger.exception("Error inesperado cargando %s", ruta)
        raise

    logger.info("Tabla '%s' cargada: %s filas, %s columnas", nombre, df.shape[0], df.shape[1])
    return df


def cargar_todas_las_tablas(cfg: Dict[str, Any], raiz_proyecto: Path) -> Dict[str, pd.DataFrame]:
    """Carga las 9 tablas Olist según config.yaml (compatibilidad con el código anterior)."""
    raw_dir = raiz_proyecto / cfg["paths"]["raw_dir"]
    archivos = cfg["archivos_origen"]

    logger.info("Iniciando carga de %s tablas desde %s", len(archivos), raw_dir)

    tablas = {
        "orders": cargar_tabla(
            raw_dir / archivos["orders"], "orders",
            parse_dates=["order_purchase_timestamp", "order_delivered_customer_date",
                         "order_estimated_delivery_date"],
        ),
        "customers": cargar_tabla(raw_dir / archivos["customers"], "customers"),
        "sellers": cargar_tabla(raw_dir / archivos["sellers"], "sellers"),
        "order_items": cargar_tabla(raw_dir / archivos["order_items"], "order_items"),
        "order_payments": cargar_tabla(raw_dir / archivos["order_payments"], "order_payments"),
        "order_reviews": cargar_tabla(raw_dir / archivos["order_reviews"], "order_reviews"),
        "products": cargar_tabla(raw_dir / archivos["products"], "products"),
        "geolocation": cargar_tabla(raw_dir / archivos["geolocation"], "geolocation"),
        "category_translation": cargar_tabla(
            raw_dir / archivos["category_translation"], "category_translation"
        ),
    }
    logger.info("Carga completa de todas las tablas")
    return tablas
