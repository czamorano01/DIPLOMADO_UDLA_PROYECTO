"""
Tests unitarios de las funciones de cálculo más críticas del pipeline.
Ejecutar con: pytest tests/ -v
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.etl import haversine_km
from src.metrics import normalizar_0_100, calcular_indice_desempeno


def test_haversine_distancia_cero_para_mismo_punto():
    d = haversine_km(np.array([-23.5]), np.array([-46.6]), np.array([-23.5]), np.array([-46.6]))
    assert d[0] == pytest.approx(0.0, abs=1e-6)


def test_haversine_distancia_sp_rio():
    # Distancia real São Paulo - Río de Janeiro es ~360 km
    d = haversine_km(np.array([-23.55]), np.array([-46.63]), np.array([-22.91]), np.array([-43.17]))
    assert 330 < d[0] < 400


def test_normalizar_0_100_rango_basico():
    serie = pd.Series([0, 50, 100])
    resultado = normalizar_0_100(serie)
    assert resultado.iloc[0] == 0
    assert resultado.iloc[-1] == 100


def test_normalizar_0_100_invertido():
    serie = pd.Series([0, 50, 100])
    resultado = normalizar_0_100(serie, invertir=True)
    assert resultado.iloc[0] == 100
    assert resultado.iloc[-1] == 0


def test_normalizar_0_100_valores_constantes_no_falla():
    serie = pd.Series([5, 5, 5])
    resultado = normalizar_0_100(serie)
    assert (resultado == 50.0).all()


def test_calcular_indice_desempeno_pesos_y_rango():
    cfg = {
        "indice_desempeno": {
            "peso_volumen": 0.25,
            "peso_puntualidad": 0.30,
            "peso_eficiencia_flete": 0.20,
            "peso_satisfaccion": 0.25,
        }
    }
    agregado = pd.DataFrame({
        "volumen": [10, 100],
        "atraso_prom": [5, -2],
        "flete_por_km_prom": [2.0, 0.5],
        "review_prom": [3.0, 4.8],
    })
    resultado = calcular_indice_desempeno(agregado, cfg)
    assert "indice_desempeno" in resultado.columns
    assert resultado["indice_desempeno"].between(0, 100).all()
    # La fila con más volumen, menos atraso, flete más eficiente y mejor review
    # debe tener un índice mayor
    assert resultado.iloc[1]["indice_desempeno"] > resultado.iloc[0]["indice_desempeno"]
