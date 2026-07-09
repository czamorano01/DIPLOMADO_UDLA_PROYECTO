"""
metrics.py

Calcula el índice de desempeño logístico (IDL) y construye los datasets
estadísticos que alimentan los paneles del dashboard (correlaciones,
series de tiempo, rankings, distribuciones).
"""

from __future__ import annotations

from typing import Any, Dict

import numpy as np
import pandas as pd

from src.logging_config import configurar_logging

logger = configurar_logging(__name__)


def normalizar_0_100(serie: pd.Series, invertir: bool = False) -> pd.Series:
    """Escala min-max a 0-100. Si invertir=True, un valor más bajo obtiene score más alto."""
    minimo, maximo = serie.min(), serie.max()
    if maximo == minimo:
        return pd.Series(50.0, index=serie.index)
    escalado = (serie - minimo) / (maximo - minimo) * 100
    return 100 - escalado if invertir else escalado


def calcular_indice_desempeno(agregado: pd.DataFrame, cfg: Dict[str, Any]) -> pd.DataFrame:
    """
    Índice de Desempeño Logístico (IDL), 0-100, combinando:
      - volumen de pedidos (a mayor volumen, mayor score)
      - puntualidad (a menor atraso, mayor score)
      - eficiencia de flete (a menor costo por km, mayor score)
      - satisfacción (a mayor review, mayor score)
    Los pesos vienen de config.yaml (negocio.indice_desempeno), nunca hardcodeados.
    """
    pesos = cfg["indice_desempeno"]
    suma_pesos = sum(pesos.values())
    if not np.isclose(suma_pesos, 1.0, atol=0.01):
        logger.warning("Los pesos del índice suman %.2f (no 1.0); se normalizan igual", suma_pesos)

    score_volumen = normalizar_0_100(agregado["volumen"])
    score_puntualidad = normalizar_0_100(agregado["atraso_prom"], invertir=True)
    score_flete = normalizar_0_100(agregado["flete_por_km_prom"], invertir=True)
    score_satisfaccion = normalizar_0_100(agregado["review_prom"])

    agregado = agregado.copy()
    agregado["score_volumen"] = score_volumen
    agregado["score_puntualidad"] = score_puntualidad
    agregado["score_flete"] = score_flete
    agregado["score_satisfaccion"] = score_satisfaccion

    agregado["indice_desempeno"] = (
        pesos["peso_volumen"] * score_volumen
        + pesos["peso_puntualidad"] * score_puntualidad
        + pesos["peso_eficiencia_flete"] * score_flete
        + pesos["peso_satisfaccion"] * score_satisfaccion
    ).round(1)

    logger.info(
        "Índice de desempeño calculado para %s filas (promedio=%.1f)",
        len(agregado), agregado["indice_desempeno"].mean(),
    )
    return agregado


# --------------------------------------------------------------------------- #
# Centroides geográficos por unidad territorial (estado / ciudad)
# --------------------------------------------------------------------------- #

def centroides_por_estado(geo: pd.DataFrame) -> pd.DataFrame:
    c = (
        geo.groupby("geolocation_state")
        .agg(lat=("geolocation_lat", "mean"), lng=("geolocation_lng", "mean"))
        .reset_index()
        .rename(columns={"geolocation_state": "estado"})
    )
    logger.info("Centroides por estado calculados: %s estados", len(c))
    return c


def centroides_por_ciudad(geo: pd.DataFrame, estado: str) -> pd.DataFrame:
    geo_estado = geo[geo["geolocation_state"] == estado]
    c = (
        geo_estado.groupby("geolocation_city")
        .agg(lat=("geolocation_lat", "mean"), lng=("geolocation_lng", "mean"))
        .reset_index()
        .rename(columns={"geolocation_city": "ciudad"})
    )
    logger.info("Centroides por ciudad calculados para estado %s: %s ciudades", estado, len(c))
    return c


# --------------------------------------------------------------------------- #
# Flujos (arcos) nacionales y urbanos, con las 4 métricas + índice
# --------------------------------------------------------------------------- #

def _agregar_por_par(df: pd.DataFrame, col_origen: str, col_destino: str) -> pd.DataFrame:
    agregado = (
        df.groupby([col_origen, col_destino])
        .agg(
            volumen=("order_id", "nunique"),
            gmv=("ticket_total", "sum"),
            atraso_prom=("atraso_dias", "mean"),
            flete_por_km_prom=("flete_por_km", "mean"),
            review_prom=("review_score", "mean"),
            distancia_prom_km=("distancia_km", "mean"),
        )
        .reset_index()
        .dropna(subset=["atraso_prom", "flete_por_km_prom", "review_prom"])
    )
    return agregado


def construir_flujos_nacionales(df: pd.DataFrame, geo: pd.DataFrame, cfg: Dict[str, Any]) -> pd.DataFrame:
    logger.info("Construyendo flujos nacionales (estado vendedor -> estado cliente)")
    umbral = cfg["negocio"]["min_pedidos_por_arco"]
    top_n = cfg["negocio"]["top_n_arcos_nacional"]

    agregado = _agregar_por_par(df, "seller_state", "customer_state")
    agregado = agregado[agregado["volumen"] >= umbral]
    agregado = calcular_indice_desempeno(agregado, cfg)

    centroides = centroides_por_estado(geo)
    agregado = agregado.merge(
        centroides.rename(columns={"estado": "seller_state", "lat": "lat_origen", "lng": "lng_origen"}),
        on="seller_state", how="left",
    )
    agregado = agregado.merge(
        centroides.rename(columns={"estado": "customer_state", "lat": "lat_destino", "lng": "lng_destino"}),
        on="customer_state", how="left",
    )

    agregado = agregado.sort_values("volumen", ascending=False).head(top_n).reset_index(drop=True)
    logger.info("Flujos nacionales construidos: %s arcos (umbral=%s pedidos)", len(agregado), umbral)
    return agregado


def construir_flujos_urbanos(df: pd.DataFrame, geo: pd.DataFrame, cfg: Dict[str, Any]) -> pd.DataFrame:
    estado_foco = cfg["negocio"]["estado_urbano_foco"]
    logger.info("Construyendo flujos urbanos dentro de %s (ciudad vendedor -> ciudad cliente)", estado_foco)

    umbral = max(2, cfg["negocio"]["min_pedidos_por_arco"] // 2)
    top_n = cfg["negocio"]["top_n_arcos_urbano"]

    df_estado = df[(df["seller_state"] == estado_foco) & (df["customer_state"] == estado_foco)]
    agregado = _agregar_por_par(df_estado, "seller_city", "customer_city")
    agregado = agregado[agregado["volumen"] >= umbral]
    agregado = calcular_indice_desempeno(agregado, cfg)

    centroides = centroides_por_ciudad(geo, estado_foco)
    agregado = agregado.merge(
        centroides.rename(columns={"ciudad": "seller_city", "lat": "lat_origen", "lng": "lng_origen"}),
        on="seller_city", how="left",
    )
    agregado = agregado.merge(
        centroides.rename(columns={"ciudad": "customer_city", "lat": "lat_destino", "lng": "lng_destino"}),
        on="customer_city", how="left",
    )

    agregado = agregado.dropna(subset=["lat_origen", "lat_destino"])
    agregado = agregado.sort_values("volumen", ascending=False).head(top_n).reset_index(drop=True)
    logger.info("Flujos urbanos construidos: %s arcos dentro de %s", len(agregado), estado_foco)
    return agregado


# --------------------------------------------------------------------------- #
# Datasets estadísticos para los paneles de la ruleta
# --------------------------------------------------------------------------- #

def _dataset_dispersión_agrupada(
    df: pd.DataFrame,
    x_col: str,
    y_col: str,
    n_bins: int,
) -> pd.DataFrame:
    subset = df.dropna(subset=[x_col, y_col]).copy()
    if subset.empty:
        return pd.DataFrame(columns=['x', 'y', 'count'])

    x_min, x_max = subset[x_col].min(), subset[x_col].max()
    y_min, y_max = subset[y_col].min(), subset[y_col].max()
    if x_min == x_max:
        x_max = x_min + 1
    if y_min == y_max:
        y_max = y_min + 1

    subset['x_bin'] = pd.cut(subset[x_col], bins=n_bins, labels=False, include_lowest=True)
    subset['y_bin'] = pd.cut(subset[y_col], bins=n_bins, labels=False, include_lowest=True)

    grouped = (
        subset.groupby(['x_bin', 'y_bin'], observed=True)
        .agg(count=('order_id', 'nunique'), **{x_col: (x_col, 'mean'), y_col: (y_col, 'mean')})
        .reset_index(drop=True)
        .round(2)
    )
    return grouped


def dataset_dispersión_distancia_entrega(df: pd.DataFrame, cfg: Dict[str, Any]) -> pd.DataFrame:
    bins = cfg['negocio'].get('scatter_aggregation_bins', 80)
    return _dataset_dispersión_agrupada(df, 'distancia_km', 'dias_entrega', bins)


def dataset_dispersión_distancia_flete(df: pd.DataFrame, cfg: Dict[str, Any]) -> pd.DataFrame:
    bins = cfg['negocio'].get('scatter_aggregation_bins', 80)
    return _dataset_dispersión_agrupada(df, 'distancia_km', 'freight_value', bins)


def dataset_atraso_vs_satisfaccion(df: pd.DataFrame) -> pd.DataFrame:
    subset = df.dropna(subset=["atraso_dias", "review_score"]).copy()
    bins = [-100, -7, -3, 0, 3, 7, 100]
    etiquetas = ["<-7d (muy anticipado)", "-7 a -3d", "-3 a 0d", "0 a 3d (tarde)", "3 a 7d", ">7d (muy tarde)"]
    subset["bucket_atraso"] = pd.cut(subset["atraso_dias"], bins=bins, labels=etiquetas)
    return (
        subset.groupby("bucket_atraso", observed=True)
        .agg(review_prom=("review_score", "mean"), n_pedidos=("order_id", "nunique"))
        .reset_index()
        .round(2)
    )


def dataset_matriz_correlacion(df: pd.DataFrame) -> pd.DataFrame:
    columnas = ["price", "freight_value", "distancia_km", "dias_entrega", "review_score", "payment_installments"]
    corr = df[columnas].corr(numeric_only=True).round(2)
    return corr


def dataset_serie_tiempo_ventas(df: pd.DataFrame) -> pd.DataFrame:
    serie = (
        df.groupby("mes_compra")
        .agg(gmv=("ticket_total", "sum"), pedidos=("order_id", "nunique"))
        .reset_index()
        .sort_values("mes_compra")
    )
    return serie.round(2)


def dataset_top_categorias(df: pd.DataFrame, top_n: int = 10) -> pd.DataFrame:
    agregado = (
        df.dropna(subset=["product_category_name_english"])
        .groupby("product_category_name_english")
        .agg(
            ticket_prom=("ticket_total", "mean"),
            review_prom=("review_score", "mean"),
            volumen=("order_id", "nunique"),
        )
        .reset_index()
        .sort_values("volumen", ascending=False)
        .head(top_n)
        .round(2)
    )
    return agregado


def dataset_metodos_pago(pagos: pd.DataFrame) -> pd.DataFrame:
    agregado = (
        pagos.groupby("payment_type")
        .agg(
            n_pagos=("order_id", "nunique"),
            cuotas_prom=("payment_installments", "mean"),
            valor_prom=("payment_value", "mean"),
        )
        .reset_index()
        .sort_values("n_pagos", ascending=False)
        .round(2)
    )
    return agregado


def dataset_top_estados_gmv(df: pd.DataFrame, top_n: int = 10) -> pd.DataFrame:
    agregado = (
        df.groupby("customer_state")
        .agg(gmv=("ticket_total", "sum"), pedidos=("order_id", "nunique"))
        .reset_index()
        .sort_values("gmv", ascending=False)
        .head(top_n)
        .round(2)
    )
    return agregado
