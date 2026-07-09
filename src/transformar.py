"""
transformar.py

Funciones de validación y transformación (construcción del dataset maestro,
centroides geográficos y utilidades). Equivalente a la sección de transformación
que antes vivía en `etl.py`.
"""
from __future__ import annotations

from typing import Any, Dict
from pathlib import Path

import numpy as np
import pandas as pd

from src.logging_config import configurar_logging

logger = configurar_logging(__name__)


def validar_calidad(df: pd.DataFrame, nombre: str) -> Dict[str, Any]:
    nulos = df.isna().sum()
    nulos = nulos[nulos > 0]
    duplicados = df.duplicated().sum()

    reporte = {
        "nombre": nombre,
        "filas": len(df),
        "columnas_con_nulos": nulos.to_dict(),
        "filas_duplicadas": int(duplicados),
    }

    if nulos.empty:
        logger.info("[%s] sin columnas con nulos", nombre)
    else:
        logger.warning("[%s] columnas con nulos: %s", nombre, nulos.to_dict())

    if duplicados:
        logger.warning("[%s] %s filas duplicadas detectadas", nombre, duplicados)

    return reporte


def validar_todas(tablas: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
    logger.info("Iniciando validación de calidad de datos")
    reportes = {nombre: validar_calidad(df, nombre) for nombre, df in tablas.items()}
    logger.info("Validación de calidad de datos finalizada")
    return reportes


def construir_centroides_geo(geo: pd.DataFrame) -> pd.DataFrame:
    centroides = (
        geo.groupby("geolocation_zip_code_prefix")
        .agg(
            lat=("geolocation_lat", "mean"),
            lng=("geolocation_lng", "mean"),
            ciudad=("geolocation_city", lambda s: s.mode().iat[0] if not s.mode().empty else s.iloc[0]),
            estado=("geolocation_state", lambda s: s.mode().iat[0] if not s.mode().empty else s.iloc[0]),
        )
        .reset_index()
        .rename(columns={"geolocation_zip_code_prefix": "zip_code_prefix"})
    )
    logger.info("Centroides de geolocalización construidos: %s prefijos únicos", len(centroides))
    return centroides


def haversine_km(lat1: np.ndarray, lng1: np.ndarray, lat2: np.ndarray, lng2: np.ndarray) -> np.ndarray:
    r = 6371.0
    lat1, lng1, lat2, lng2 = map(np.radians, [lat1, lng1, lat2, lng2])
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlng / 2.0) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


def construir_dataset_maestro(tablas: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    logger.info("Construyendo dataset maestro (join de %s tablas)", len(tablas))

    orders = tablas["orders"]
    items = tablas["order_items"]
    customers = tablas["customers"]
    sellers = tablas["sellers"]
    reviews = tablas["order_reviews"][ ["order_id", "review_score"] ].drop_duplicates("order_id")
    products = tablas["products"][ ["product_id", "product_category_name"] ]
    cat_translation = tablas["category_translation"]

    pagos_agg = (
        tablas["order_payments"]
        .groupby("order_id")
        .agg(payment_value=("payment_value", "sum"), payment_installments=("payment_installments", "max"))
        .reset_index()
    )

    df = items.merge(orders, on="order_id", how="inner")
    df = df.merge(customers, on="customer_id", how="left")
    df = df.merge(sellers, on="seller_id", how="left")
    df = df.merge(reviews, on="order_id", how="left")
    df = df.merge(pagos_agg, on="order_id", how="left")
    df = df.merge(products, on="product_id", how="left")
    df = df.merge(cat_translation, on="product_category_name", how="left")

    # Filtramos geolocalización a los prefijos realmente usados para no agrupar todo el dataset global.
    zip_prefixes = pd.Index(df["customer_zip_code_prefix"].dropna().astype(int).unique()).append(
        pd.Index(df["seller_zip_code_prefix"].dropna().astype(int).unique())
    ).unique()
    geo_usado = tablas["geolocation"][tablas["geolocation"]["geolocation_zip_code_prefix"].isin(zip_prefixes)]
    geo_centroides = construir_centroides_geo(geo_usado)

    # Distancia vendedor-cliente vía centroides de CEP
    geo_cli = geo_centroides.rename(columns={"lat": "lat_cliente", "lng": "lng_cliente"})
    geo_sel = geo_centroides.rename(columns={"lat": "lat_vendedor", "lng": "lng_vendedor"})

    df = df.merge(
        geo_cli[["zip_code_prefix", "lat_cliente", "lng_cliente"]],
        left_on="customer_zip_code_prefix", right_on="zip_code_prefix", how="left",
    ).drop(columns=["zip_code_prefix"])

    df = df.merge(
        geo_sel[["zip_code_prefix", "lat_vendedor", "lng_vendedor"]],
        left_on="seller_zip_code_prefix", right_on="zip_code_prefix", how="left",
    ).drop(columns=["zip_code_prefix"])

    con_coords = df[["lat_cliente", "lng_cliente", "lat_vendedor", "lng_vendedor"]].notna().all(axis=1)
    df["distancia_km"] = np.nan
    df.loc[con_coords, "distancia_km"] = haversine_km(
        df.loc[con_coords, "lat_vendedor"].values, df.loc[con_coords, "lng_vendedor"].values,
        df.loc[con_coords, "lat_cliente"].values, df.loc[con_coords, "lng_cliente"].values,
    )

    # Variables temporales
    df["dias_entrega"] = (df["order_delivered_customer_date"] - df["order_purchase_timestamp"]).dt.days
    df["atraso_dias"] = (
        df["order_delivered_customer_date"] - df["order_estimated_delivery_date"]
    ).dt.days

    df["flete_por_km"] = np.where(df["distancia_km"] > 1, df["freight_value"] / df["distancia_km"], np.nan)

    df["mes_compra"] = df["order_purchase_timestamp"].dt.to_period("M").astype(str)
    df["ticket_total"] = df["price"] + df["freight_value"]

    logger.info("Dataset maestro construido: %s filas, %s columnas", df.shape[0], df.shape[1])

    filas_sin_geo = df["distancia_km"].isna().sum()
    if filas_sin_geo:
        logger.warning(
            "%s filas (%.1f%%) sin distancia calculable por falta de match geográfico",
            filas_sin_geo, 100 * filas_sin_geo / len(df),
        )

    return df
