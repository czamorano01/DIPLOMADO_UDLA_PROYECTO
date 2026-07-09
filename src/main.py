"""
main.py

Punto de entrada del pipeline. Ejecutar desde la raíz del proyecto:

    python -m src.main

Flujo:
  1. Carga config.yaml
  2. Inicializa logging (consola + archivo rotativo en logs/)
  3. Carga y valida las 9 tablas Olist
  4. Construye el dataset maestro con variables derivadas (distancia, atraso, etc.)
  5. Calcula flujos nacionales y urbanos con el índice de desempeño (4 métricas)
  6. Calcula los datasets estadísticos para los paneles
  7. Exporta todo a CSV en outputs/ (sin cambios respecto a versiones anteriores)
  8. Genera tres archivos HTML livianos y autocontenidos (file://, sin
     servidor HTTP, sin caché posible entre corridas) y los abre
     automáticamente en el navegador: dashboard_flujos.html,
     dashboard_estadisticas.html y mapa_animado.html (mapa 2D con los flujos
     nacionales animados en bucle continuo, sin dependencias externas).
"""

from __future__ import annotations

import sys
import time
import webbrowser
from pathlib import Path

import yaml

RAIZ_PROYECTO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ_PROYECTO))

from src.logging_config import inicializar_logging, configurar_logging  # noqa: E402
from src import etl, metrics, visualization_builder  # noqa: E402


def cargar_config(raiz: Path) -> dict:
    ruta_config = raiz / "config" / "config.yaml"
    with open(ruta_config, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def formatear_moneda_brl(valor: float) -> str:
    return f"R$ {valor:,.0f}".replace(",", ".")


def construir_payload(df, geo, cfg, tablas) -> dict:
    logger = configurar_logging(__name__)
    logger.info("Construyendo flujos y datasets estadísticos para el dashboard")

    flujos_nacionales = metrics.construir_flujos_nacionales(df, geo, cfg)
    flujos_urbanos = metrics.construir_flujos_urbanos(df, geo, cfg)

    stats = {
        "dispersion_distancia_entrega": metrics.dataset_dispersión_distancia_entrega(df, cfg).to_dict("records"),
        "dispersion_distancia_flete": metrics.dataset_dispersión_distancia_flete(df, cfg).to_dict("records"),
        "atraso_vs_satisfaccion": metrics.dataset_atraso_vs_satisfaccion(df).to_dict("records"),
        "serie_tiempo_ventas": metrics.dataset_serie_tiempo_ventas(df).to_dict("records"),
        "top_categorias": metrics.dataset_top_categorias(df).to_dict("records"),
        "metodos_pago": metrics.dataset_metodos_pago(tablas["order_payments"]).to_dict("records"),
        "top_estados_gmv": metrics.dataset_top_estados_gmv(df).to_dict("records"),
    }

    corr = metrics.dataset_matriz_correlacion(df)
    stats["matriz_correlacion"] = {"columnas": list(corr.columns), "datos": corr.values.tolist()}

    total_pedidos = int(df["order_id"].nunique())
    gmv_total = float(df["ticket_total"].sum())
    periodo = f"{df['order_purchase_timestamp'].min():%Y-%m} a {df['order_purchase_timestamp'].max():%Y-%m}"

    payload = {
        "meta": {
            "total_pedidos": total_pedidos,
            "gmv_total_fmt": formatear_moneda_brl(gmv_total),
            "periodo": periodo,
        },
        "flujos_nacionales": flujos_nacionales.to_dict("records"),
        "flujos_urbanos": flujos_urbanos.to_dict("records"),
        "stats": stats,
    }
    logger.info("Payload construido: %s pedidos, %s arcos nacionales, %s arcos urbanos",
                total_pedidos, len(flujos_nacionales), len(flujos_urbanos))
    return payload, flujos_nacionales, flujos_urbanos, stats


def exportar_csv(raiz: Path, cfg: dict, flujos_nacionales, flujos_urbanos, stats: dict) -> None:
    logger = configurar_logging(__name__)
    out_dir = raiz / cfg["paths"]["outputs_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)

    flujos_nacionales.to_csv(out_dir / "flujos_nacionales.csv", index=False)
    flujos_urbanos.to_csv(out_dir / "flujos_urbanos_sao_paulo.csv", index=False)

    import pandas as pd  # import local para evitar dependencia si solo se usa el módulo de config

    for nombre, registros in stats.items():
        if nombre == "matriz_correlacion":
            pd.DataFrame(registros["datos"], columns=registros["columnas"], index=registros["columnas"]).to_csv(
                out_dir / f"{nombre}.csv"
            )
        else:
            pd.DataFrame(registros).to_csv(out_dir / f"{nombre}.csv", index=False)

    logger.info("CSVs exportados en %s", out_dir)


def abrir_en_navegador(rutas_html: list[Path]) -> None:
    """
    Abre los dashboards directamente como archivos locales (file://), sin
    servidor HTTP: nada que ocupe un puerto, nada que quede corriendo de
    fondo, nada que Chrome pueda cachear entre corridas (una respuesta HTTP
    se cachea; un archivo local que se vuelve a leer del disco, no).
    `new=2` le pide al navegador una pestaña nueva para cada archivo.
    """
    logger = configurar_logging(__name__)
    for ruta_html in rutas_html:
        logger.info("Abriendo %s en el navegador...", ruta_html.name)
        webbrowser.open(ruta_html.resolve().as_uri(), new=2)


def main() -> None:
    inicio = time.time()
    cfg = cargar_config(RAIZ_PROYECTO)
    inicializar_logging(cfg["logging"], RAIZ_PROYECTO)
    logger = configurar_logging(__name__)

    logger.info("=== Inicio del pipeline: Geografía de ventas + Dashboard 360 (Olist) ===")

    try:
        tablas = etl.cargar_todas_las_tablas(cfg, RAIZ_PROYECTO)
        etl.validar_todas(tablas)
        df = etl.construir_dataset_maestro(tablas)

        payload, flujos_nacionales, flujos_urbanos, stats = construir_payload(
            df, tablas["geolocation"], cfg, tablas
        )

        exportar_csv(RAIZ_PROYECTO, cfg, flujos_nacionales, flujos_urbanos, stats)

        ruta_flujos = RAIZ_PROYECTO / cfg["paths"]["dashboard_flujos_file"]
        ruta_estadisticas = RAIZ_PROYECTO / cfg["paths"]["dashboard_estadisticas_file"]
        ruta_mapa = RAIZ_PROYECTO / cfg["paths"]["dashboard_mapa_file"]
        visualization_builder.construir_dashboard_flujos_html(payload, ruta_flujos)
        visualization_builder.construir_dashboard_estadisticas_html(payload, ruta_estadisticas)
        visualization_builder.construir_mapa_animado_html(payload, ruta_mapa)

        abrir_en_navegador([ruta_flujos, ruta_estadisticas, ruta_mapa])

        duracion = time.time() - inicio
        logger.info("=== Pipeline completado en %.1f segundos ===", duracion)

    except Exception:
        logger.exception("El pipeline terminó con un error no controlado")
        raise


if __name__ == "__main__":
    main()
