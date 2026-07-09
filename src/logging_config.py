"""
logging_config.py

Configura logging de forma centralizada para todo el pipeline.
Uso:
    from src.logging_config import configurar_logging
    logger = configurar_logging(__name__)
"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path
from typing import Any, Dict

_CONFIGURADO = False


def _preparar_directorio_logs(ruta_archivo: Path) -> None:
    ruta_archivo.parent.mkdir(parents=True, exist_ok=True)


def inicializar_logging(cfg: Dict[str, Any], raiz_proyecto: Path) -> None:
    """
    Inicializa el logging raíz una sola vez por ejecución del proceso.
    Se llama desde main.py antes de cualquier otra cosa.
    """
    global _CONFIGURADO
    if _CONFIGURADO:
        return

    nivel = getattr(logging, cfg.get("nivel", "INFO").upper(), logging.INFO)
    formato = cfg.get("formato", "%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    archivo_log = raiz_proyecto / cfg.get("archivo", "logs/pipeline.log")
    max_bytes = int(cfg.get("rotacion_bytes", 5 * 1024 * 1024))
    backups = int(cfg.get("respaldo_copias", 3))

    _preparar_directorio_logs(archivo_log)

    handler_consola = logging.StreamHandler()
    handler_consola.setFormatter(logging.Formatter(formato))

    handler_archivo = logging.handlers.RotatingFileHandler(
        archivo_log, maxBytes=max_bytes, backupCount=backups, encoding="utf-8"
    )
    handler_archivo.setFormatter(logging.Formatter(formato))

    logging.basicConfig(level=nivel, handlers=[handler_consola, handler_archivo])
    _CONFIGURADO = True


def configurar_logging(nombre_modulo: str) -> logging.Logger:
    """Devuelve un logger con el nombre del módulo llamador."""
    return logging.getLogger(nombre_modulo)
