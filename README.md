# Geografía de ventas + Dashboard 360 — Olist Brazilian E-commerce

Proyecto integrador DPL1046 — Diplomado en Ingeniería de Datos con Python (UDLA).
Combina los temas **8 (Geografía de ventas)** y **10 (Dashboard 360)** del listado del curso.

## Qué hace

1. Lee y valida las 9 tablas del dataset Olist (`data/raw/`).
2. Construye un dataset maestro: une órdenes, ítems, clientes, vendedores, pagos,
   reseñas y productos, y calcula variables derivadas (distancia vendedor-cliente
   vía geolocalización, atraso de entrega, eficiencia de flete, ticket total).
3. Calcula un **Índice de Desempeño Logístico (IDL)** por par origen-destino,
   combinando 4 métricas: volumen, puntualidad, eficiencia de flete y satisfacción
   (pesos configurables en `config/config.yaml`).
4. Genera **tres dashboards HTML autocontenidos y livianos** que se abren
   automáticamente en el navegador al terminar la ejecución:
   - `dashboard_flujos.html` — rutas nacionales y urbanas (São Paulo) por
     volumen de pedidos, coloreadas por índice de desempeño, con ranking top 5
     y descarga CSV/JPEG.
   - `dashboard_estadisticas.html` — los 8 paneles estadísticos del negocio
     (dispersión distancia/entrega, dispersión distancia/flete, atraso vs.
     satisfacción, serie de tiempo de ventas, top categorías, métodos de pago,
     top estados por GMV, matriz de correlación), cada uno descargable en
     CSV y JPEG.
   - `mapa_animado.html` — mapa 2D de los flujos nacionales, con arcos y
     partículas en movimiento continuo (loop tipo GIF) coloreados por índice
     de desempeño, silueta del mapa calculada a partir de los propios
     centroides (envolvente convexa, sin datos geográficos externos), ranking
     top 5 y descarga CSV/JPEG.

   Todos los gráficos y la animación están construidos con Canvas 2D nativo
   (motor propio, sin librerías externas como Chart.js): cargan al instante,
   no dependen de ningún servidor local ni de conexión a internet.
5. Exporta todos los datasets usados como CSV en `outputs/`.
6. Registra cada paso en `logs/pipeline.log` (rotativo) y en consola.

## Cómo correrlo en VSCode

```bash
# 1. crear entorno virtual (opcional pero recomendado)
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 2. instalar dependencias
pip install -r requirements.txt

# 3. correr el pipeline completo
python -m src.main
```

Al terminar, se abren automáticamente `outputs/dashboard_flujos.html`,
`outputs/dashboard_estadisticas.html` y `outputs/mapa_animado.html` en tu
navegador (cada uno como archivo local, sin servidor). Si por algún motivo no
se abren solos, ábrelos manualmente haciendo doble clic. Cada corrida
sobrescribe estos tres mismos archivos — no se acumulan copias.

### Correr los tests

```bash
pytest tests/ -v
```

## Estructura del proyecto

```
config/config.yaml        Configuración externalizada (rutas, pesos del índice, umbrales)
data/raw/                 Las 9 tablas Olist originales
src/etl.py                Carga, validación de calidad y construcción del dataset maestro
src/metrics.py            Índice de desempeño + datasets estadísticos para los paneles
src/visualization_builder.py   Genera los tres dashboards HTML (Canvas 2D propio, sin librerías externas)
src/logging_config.py     Logging centralizado (consola + archivo rotativo)
src/main.py                Orquestador del pipeline
tests/test_metrics.py     Tests unitarios (haversine, normalización, índice compuesto)
outputs/                  CSVs + dashboard_flujos.html + dashboard_estadisticas.html + mapa_animado.html
logs/                     pipeline.log (rotativo, 5 MB x 3 respaldos)
```
