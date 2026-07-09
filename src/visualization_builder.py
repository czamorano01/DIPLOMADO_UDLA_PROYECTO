"""
visualization_builder.py

Genera dos dashboards HTML autocontenidos y livianos, enfocados solo en
despliegue de resultados estadísticos (sin mapa animado, sin canvas de
partículas, sin ruleta 3D ni intro escenificada):

  - dashboard_flujos.html         Rutas nacionales y urbanas por volumen e
                                   índice de desempeño logístico.
  - dashboard_estadisticas.html   Los 8 paneles estadísticos del negocio
                                   (dispersión, atraso vs. satisfacción,
                                   serie de tiempo, top categorías, métodos
                                   de pago, top estados, correlación).

CERO dependencias externas: los gráficos NO usan Chart.js desde CDN (eso
causaba pantallas en blanco cuando el navegador no podía cargar el script
remoto -- firewall, antivirus, red sin salida a internet, etc.). En su lugar,
todo se dibuja con un mini motor de gráficos propio sobre <canvas> 2D, escrito
en este mismo archivo y embebido en el HTML. Cada archivo embebe únicamente
los datos que usa (no el payload completo). No hay servidor, no hay caché,
no hay red: son archivos que se abren con doble clic y funcionan sin
conexión a internet.

Este módulo NO ejecuta análisis: solo recibe el payload ya calculado
(dict serializable a JSON) y arma el HTML final.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from src.logging_config import configurar_logging

logger = configurar_logging(__name__)


_ESTILOS_CSS = r"""
* { box-sizing: border-box; }
html, body {
  margin: 0; padding: 0;
  background: #0d0d0d;
  color: #c3c2b7;
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
}
body { padding: 24px 28px 48px; }
header { margin-bottom: 22px; }
h1 { font-size: 20px; font-weight: 600; margin: 0 0 4px; color: #ffffff; }
header p { margin: 0; font-size: 13px; color: #898781; }
nav.tabs { margin-top: 14px; display: flex; gap: 8px; }
nav.tabs a {
  font-size: 12.5px; color: #c3c2b7; text-decoration: none;
  padding: 6px 12px; border-radius: 7px; border: 1px solid rgba(255,255,255,0.10);
}
nav.tabs a.activa { color: #ffffff; border-color: #3987e5; background: rgba(57,135,229,0.12); }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 16px; }
.card {
  background: #1a1a19; border: 1px solid rgba(255,255,255,0.10); border-radius: 10px;
  padding: 14px 16px;
}
.card h3 { margin: 0 0 10px; font-size: 13.5px; font-weight: 600; color: #ffffff; }
.card canvas { display: block; }
.card-botones { display: flex; gap: 8px; margin-top: 10px; }
.card-botones button {
  flex: 1; font-size: 11.5px; padding: 6px 8px; border-radius: 6px;
  border: 1px solid rgba(255,255,255,0.15); background: rgba(255,255,255,0.04);
  color: #c3c2b7; cursor: pointer;
}
.card-botones button:hover { background: rgba(255,255,255,0.10); }
.ranking { margin-top: 10px; padding-top: 10px; border-top: 1px solid rgba(255,255,255,0.10); font-size: 12px; }
.ranking b { color: #ffffff; font-size: 12px; display: block; margin-bottom: 6px; }
.ranking div { display: flex; justify-content: space-between; margin: 3px 0; color: #c3c2b7; }
footer { margin-top: 28px; font-size: 11.5px; color: #898781; }
"""

# Utilidades comunes: descarga de CSV/JPEG y el mini motor de gráficos en
# Canvas 2D puro (sin dependencias externas -- ver docstring del módulo).
_UTILIDADES_JS = r"""
function descargarTextoComoArchivo(texto, nombreArchivo, tipoMime) {
  const blob = new Blob([texto], { type: tipoMime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = nombreArchivo; a.click();
  URL.revokeObjectURL(url);
}

function arrayObjetosACSV(filas) {
  if (!filas || !filas.length) return '';
  const columnas = Object.keys(filas[0]);
  const lineas = [columnas.join(',')];
  for (const fila of filas) lineas.push(columnas.map(c => fila[c]).join(','));
  return lineas.join('\n');
}

function descargarCanvasComoJPEG(canvas, nombreArchivo) {
  const tmp = document.createElement('canvas');
  tmp.width = canvas.width; tmp.height = canvas.height;
  const ctx = tmp.getContext('2d');
  ctx.fillStyle = '#1a1a19';
  ctx.fillRect(0, 0, tmp.width, tmp.height);
  ctx.drawImage(canvas, 0, 0);
  const a = document.createElement('a');
  a.href = tmp.toDataURL('image/jpeg', 0.92);
  a.download = nombreArchivo;
  a.click();
}

/* ------------------------------------------------------------------ */
/* Mini motor de gráficos (Canvas 2D, cero dependencias externas)      */
/* ------------------------------------------------------------------ */

const MC_COLOR_EJE = '#383835';
const MC_COLOR_TEXTO = '#c3c2b7';

let mcTooltipEl = null;
function mcTooltip() {
  if (!mcTooltipEl) {
    mcTooltipEl = document.createElement('div');
    mcTooltipEl.style.cssText =
      'position:fixed;pointer-events:none;background:#1a1a19;' +
      'border:1px solid rgba(255,255,255,0.18);border-radius:6px;padding:6px 9px;' +
      'font-size:11px;color:#ffffff;z-index:50;display:none;white-space:pre-line;' +
      'box-shadow:0 4px 14px rgba(0,0,0,0.45);max-width:220px;';
    document.body.appendChild(mcTooltipEl);
  }
  return mcTooltipEl;
}
function mcMostrarTooltip(clientX, clientY, texto) {
  const el = mcTooltip();
  el.textContent = texto;
  el.style.left = (clientX + 14) + 'px';
  el.style.top = (clientY + 14) + 'px';
  el.style.display = 'block';
}
function mcOcultarTooltip() { if (mcTooltipEl) mcTooltipEl.style.display = 'none'; }

function mcPrepararCanvas(canvas, alturaCss) {
  // Resta el padding horizontal de la tarjeta (.card { padding: 14px 16px })
  // para que el buffer del canvas coincida con su ancho real renderizado.
  const ancho = Math.max(140, canvas.parentElement.clientWidth - 32);
  const alto = alturaCss;
  const dpr = window.devicePixelRatio || 1;
  canvas.style.width = ancho + 'px';
  canvas.style.height = alto + 'px';
  canvas.width = Math.max(1, Math.round(ancho * dpr));
  canvas.height = Math.max(1, Math.round(alto * dpr));
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, ancho, alto);
  return { ctx, ancho, alto };
}

function mcTruncar(ctx, texto, anchoMax) {
  texto = String(texto);
  if (ctx.measureText(texto).width <= anchoMax) return texto;
  let t = texto;
  while (t.length > 1 && ctx.measureText(t + '…').width > anchoMax) t = t.slice(0, -1);
  return t + '…';
}

const MC_REGISTRO_RESIZE = [];
let mcResizeTimer = null;
window.addEventListener('resize', () => {
  clearTimeout(mcResizeTimer);
  mcResizeTimer = setTimeout(() => MC_REGISTRO_RESIZE.forEach(fn => fn()), 150);
});

function mcColorResuelto(colores, i, porDefecto) {
  if (typeof colores === 'function') return colores(i);
  if (Array.isArray(colores)) return colores[i % colores.length];
  return colores || porDefecto;
}

function mcBarrasHorizontales(canvas, opciones) {
  function render() {
    const n = opciones.valores.length;
    const alturaFila = opciones.alturaFila || 20;
    const alto = Math.max(140, n * alturaFila + 26);
    const { ctx, ancho } = mcPrepararCanvas(canvas, alto);
    const margenIzq = opciones.margenIzq || 128;
    const margenDer = 12;
    const margenSup = 8;
    const margenInf = 18;
    const anchoBarras = Math.max(10, ancho - margenIzq - margenDer);
    const altoBarras = alto - margenSup - margenInf;
    const filaAlto = altoBarras / Math.max(1, n);
    const maxValor = Math.max(...opciones.valores, 1);

    ctx.strokeStyle = MC_COLOR_EJE;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(margenIzq + 0.5, margenSup);
    ctx.lineTo(margenIzq + 0.5, alto - margenInf);
    ctx.stroke();

    ctx.font = '10px system-ui, sans-serif';
    ctx.textBaseline = 'middle';
    const hitboxes = [];
    for (let i = 0; i < n; i++) {
      const y = margenSup + i * filaAlto;
      const h = Math.max(3, filaAlto - 5);
      const w = (opciones.valores[i] / maxValor) * anchoBarras;
      const color = mcColorResuelto(opciones.colores, i, '#3987e5');
      ctx.fillStyle = color;
      ctx.fillRect(margenIzq, y + (filaAlto - h) / 2, Math.max(1.5, w), h);

      ctx.fillStyle = MC_COLOR_TEXTO;
      ctx.textAlign = 'right';
      ctx.fillText(mcTruncar(ctx, opciones.etiquetas[i], margenIzq - 8), margenIzq - 8, y + filaAlto / 2);

      hitboxes.push({ x0: 0, y0: y, x1: ancho, y1: y + filaAlto, i });
    }

    canvas.onmousemove = (ev) => {
      const rect = canvas.getBoundingClientRect();
      const mx = ev.clientX - rect.left, my = ev.clientY - rect.top;
      const hit = hitboxes.find(h => mx >= h.x0 && mx <= h.x1 && my >= h.y0 && my <= h.y1);
      if (hit) mcMostrarTooltip(ev.clientX, ev.clientY, opciones.formatoTooltip(hit.i));
      else mcOcultarTooltip();
    };
    canvas.onmouseleave = mcOcultarTooltip;
  }
  render();
  MC_REGISTRO_RESIZE.push(render);
}

function mcBarrasVerticales(canvas, opciones) {
  function render() {
    const alto = opciones.alto || 220;
    const { ctx, ancho } = mcPrepararCanvas(canvas, alto);
    const n = opciones.valores.length;
    const margenIzq = 36, margenDer = 10, margenSup = 10, margenInf = 46;
    const anchoBarras = Math.max(10, ancho - margenIzq - margenDer);
    const altoBarras = alto - margenSup - margenInf;
    const maxValor = Math.max(...opciones.valores, 0.0001);
    const anchoCol = anchoBarras / Math.max(1, n);

    ctx.strokeStyle = MC_COLOR_EJE;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(margenIzq, margenSup);
    ctx.lineTo(margenIzq, alto - margenInf);
    ctx.lineTo(margenIzq + anchoBarras, alto - margenInf);
    ctx.stroke();

    ctx.font = '9px system-ui, sans-serif';
    ctx.fillStyle = MC_COLOR_TEXTO;
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    ctx.fillText(maxValor.toFixed(1), margenIzq - 6, margenSup + 4);
    ctx.fillText('0', margenIzq - 6, alto - margenInf);

    const hitboxes = [];
    for (let i = 0; i < n; i++) {
      const x = margenIzq + i * anchoCol;
      const h = (opciones.valores[i] / maxValor) * altoBarras;
      const color = mcColorResuelto(opciones.color, i, '#3987e5');
      ctx.fillStyle = color;
      ctx.fillRect(x + 3, alto - margenInf - h, Math.max(1.5, anchoCol - 6), h);

      ctx.save();
      ctx.fillStyle = MC_COLOR_TEXTO;
      ctx.textAlign = 'right';
      ctx.translate(x + anchoCol / 2 + 3, alto - margenInf + 6);
      ctx.rotate(-Math.PI / 4);
      ctx.fillText(mcTruncar(ctx, opciones.etiquetas[i], 70), 0, 0);
      ctx.restore();

      hitboxes.push({ x0: x, y0: margenSup, x1: x + anchoCol, y1: alto - margenInf, i });
    }

    canvas.onmousemove = (ev) => {
      const rect = canvas.getBoundingClientRect();
      const mx = ev.clientX - rect.left, my = ev.clientY - rect.top;
      const hit = hitboxes.find(h => mx >= h.x0 && mx <= h.x1 && my >= h.y0 && my <= h.y1);
      if (hit) mcMostrarTooltip(ev.clientX, ev.clientY, opciones.formatoTooltip(hit.i));
      else mcOcultarTooltip();
    };
    canvas.onmouseleave = mcOcultarTooltip;
  }
  render();
  MC_REGISTRO_RESIZE.push(render);
}

function mcDispersion(canvas, opciones) {
  function render() {
    const alto = opciones.alto || 220;
    const { ctx, ancho } = mcPrepararCanvas(canvas, alto);
    const margenIzq = 42, margenDer = 12, margenSup = 10, margenInf = 28;
    const anchoPlot = Math.max(10, ancho - margenIzq - margenDer);
    const altoPlot = alto - margenSup - margenInf;
    const xs = opciones.puntos.map(p => p.x), ys = opciones.puntos.map(p => p.y);
    let xMin = Math.min(...xs), xMax = Math.max(...xs);
    let yMin = Math.min(...ys), yMax = Math.max(...ys);
    if (xMin === xMax) xMax = xMin + 1;
    if (yMin === yMax) yMax = yMin + 1;
    const escalaX = (v) => margenIzq + ((v - xMin) / (xMax - xMin)) * anchoPlot;
    const escalaY = (v) => margenSup + altoPlot - ((v - yMin) / (yMax - yMin)) * altoPlot;

    ctx.strokeStyle = MC_COLOR_EJE;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(margenIzq, margenSup);
    ctx.lineTo(margenIzq, margenSup + altoPlot);
    ctx.lineTo(margenIzq + anchoPlot, margenSup + altoPlot);
    ctx.stroke();

    ctx.font = '9px system-ui, sans-serif';
    ctx.fillStyle = MC_COLOR_TEXTO;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    ctx.fillText(xMin.toFixed(0), margenIzq, margenSup + altoPlot + 6);
    ctx.fillText(xMax.toFixed(0), margenIzq + anchoPlot, margenSup + altoPlot + 6);
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    ctx.fillText(yMax.toFixed(0), margenIzq - 6, margenSup);
    ctx.fillText(yMin.toFixed(0), margenIzq - 6, margenSup + altoPlot);

    const puntosPx = opciones.puntos.map(p => ({
      x: escalaX(p.x), y: escalaY(p.y), r: p.r || 3, orig: p,
    }));
    ctx.fillStyle = opciones.color || 'rgba(57,135,229,0.55)';
    for (const p of puntosPx) {
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fill();
    }

    canvas.onmousemove = (ev) => {
      const rect = canvas.getBoundingClientRect();
      const mx = ev.clientX - rect.left, my = ev.clientY - rect.top;
      let cercano = null, distMin = 10;
      for (const p of puntosPx) {
        const d = Math.hypot(mx - p.x, my - p.y);
        if (d < Math.max(distMin, p.r + 3)) { cercano = p; distMin = d; }
      }
      if (cercano) mcMostrarTooltip(ev.clientX, ev.clientY, opciones.formatoTooltip(cercano.orig));
      else mcOcultarTooltip();
    };
    canvas.onmouseleave = mcOcultarTooltip;
  }
  render();
  MC_REGISTRO_RESIZE.push(render);
}

function mcLinea(canvas, opciones) {
  function render() {
    const alto = opciones.alto || 220;
    const { ctx, ancho } = mcPrepararCanvas(canvas, alto);
    const margenIzq = 46, margenDer = 12, margenSup = 12, margenInf = 26;
    const anchoPlot = Math.max(10, ancho - margenIzq - margenDer);
    const altoPlot = alto - margenSup - margenInf;
    const n = opciones.valores.length;
    const valMin = Math.min(...opciones.valores, 0);
    const valMax = Math.max(...opciones.valores, 1);
    const escalaX = (i) => margenIzq + (n <= 1 ? anchoPlot / 2 : (i / (n - 1)) * anchoPlot);
    const escalaY = (v) => margenSup + altoPlot - ((v - valMin) / (valMax - valMin || 1)) * altoPlot;

    ctx.strokeStyle = MC_COLOR_EJE;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(margenIzq, margenSup);
    ctx.lineTo(margenIzq, margenSup + altoPlot);
    ctx.lineTo(margenIzq + anchoPlot, margenSup + altoPlot);
    ctx.stroke();

    ctx.font = '9px system-ui, sans-serif';
    ctx.fillStyle = MC_COLOR_TEXTO;
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    ctx.fillText(valMax.toFixed(0), margenIzq - 6, margenSup);
    ctx.fillText(valMin.toFixed(0), margenIzq - 6, margenSup + altoPlot);

    const puntos = opciones.valores.map((v, i) => ({ x: escalaX(i), y: escalaY(v), i }));

    ctx.beginPath();
    ctx.moveTo(puntos[0].x, margenSup + altoPlot);
    puntos.forEach(p => ctx.lineTo(p.x, p.y));
    ctx.lineTo(puntos[puntos.length - 1].x, margenSup + altoPlot);
    ctx.closePath();
    ctx.fillStyle = opciones.colorRelleno || 'rgba(0,131,0,0.15)';
    ctx.fill();

    ctx.beginPath();
    puntos.forEach((p, i) => (i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y)));
    ctx.strokeStyle = opciones.color || '#008300';
    ctx.lineWidth = 2;
    ctx.stroke();

    ctx.fillStyle = MC_COLOR_TEXTO;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'alphabetic';
    const indicesEtiqueta = n > 1 ? [0, Math.floor((n - 1) / 2), n - 1] : [0];
    indicesEtiqueta.forEach(i => {
      ctx.fillText(mcTruncar(ctx, opciones.etiquetas[i], 60), puntos[i].x, alto - margenInf + 16);
    });

    canvas.onmousemove = (ev) => {
      const rect = canvas.getBoundingClientRect();
      const mx = ev.clientX - rect.left;
      let cercano = puntos[0], distMin = Infinity;
      for (const p of puntos) {
        const d = Math.abs(mx - p.x);
        if (d < distMin) { cercano = p; distMin = d; }
      }
      if (distMin < 24) mcMostrarTooltip(ev.clientX, ev.clientY, opciones.formatoTooltip(cercano.i));
      else mcOcultarTooltip();
    };
    canvas.onmouseleave = mcOcultarTooltip;
  }
  render();
  MC_REGISTRO_RESIZE.push(render);
}

function mcDona(canvas, opciones) {
  function render() {
    const alto = opciones.alto || 220;
    const { ctx, ancho } = mcPrepararCanvas(canvas, alto);
    const total = opciones.valores.reduce((a, b) => a + b, 0) || 1;
    const cx = ancho / 2, cy = (alto - 34) / 2 + 6;
    const radioExt = Math.max(20, Math.min(cx, cy) - 10);
    const radioInt = radioExt * 0.55;

    let anguloActual = -Math.PI / 2;
    const segmentos = [];
    opciones.valores.forEach((v, i) => {
      const angulo = (v / total) * Math.PI * 2;
      const color = mcColorResuelto(opciones.colores, i, '#3987e5');
      ctx.beginPath();
      ctx.arc(cx, cy, radioExt, anguloActual, anguloActual + angulo);
      ctx.arc(cx, cy, radioInt, anguloActual + angulo, anguloActual, true);
      ctx.closePath();
      ctx.fillStyle = color;
      ctx.fill();
      segmentos.push({ inicio: anguloActual, fin: anguloActual + angulo, i });
      anguloActual += angulo;
    });

    ctx.font = '9.5px system-ui, sans-serif';
    ctx.textBaseline = 'middle';
    let ly = alto - 22;
    let lx = 10;
    opciones.etiquetas.forEach((etq, i) => {
      const color = mcColorResuelto(opciones.colores, i, '#3987e5');
      const anchoTxt = ctx.measureText(etq).width;
      if (lx + 14 + anchoTxt + 14 > ancho) { lx = 10; ly += 14; }
      ctx.fillStyle = color;
      ctx.fillRect(lx, ly - 4, 8, 8);
      ctx.fillStyle = MC_COLOR_TEXTO;
      ctx.textAlign = 'left';
      ctx.fillText(etq, lx + 12, ly);
      lx += 14 + anchoTxt + 14;
    });

    canvas.onmousemove = (ev) => {
      const rect = canvas.getBoundingClientRect();
      const mx = ev.clientX - rect.left, my = ev.clientY - rect.top;
      const dx = mx - cx, dy = my - cy;
      const dist = Math.hypot(dx, dy);
      if (dist >= radioInt && dist <= radioExt) {
        let ang = Math.atan2(dy, dx);
        if (ang < -Math.PI / 2) ang += Math.PI * 2;
        const seg = segmentos.find(s => ang >= s.inicio && ang <= s.fin);
        if (seg) { mcMostrarTooltip(ev.clientX, ev.clientY, opciones.formatoTooltip(seg.i)); return; }
      }
      mcOcultarTooltip();
    };
    canvas.onmouseleave = mcOcultarTooltip;
  }
  render();
  MC_REGISTRO_RESIZE.push(render);
}
"""

_PLANTILLA_FLUJOS = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>Flujos y desempeño logístico · Olist</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
__ESTILOS__
</style>
</head>
<body>
<header>
  <h1>Flujos y desempeño logístico</h1>
  <p id="meta-info"></p>
  <nav class="tabs">
    <a class="activa" href="dashboard_flujos.html">Flujos</a>
    <a href="dashboard_estadisticas.html">Estadísticas</a>
    <a href="mapa_animado.html">Mapa animado</a>
  </nav>
</header>

<div class="grid">
  <div class="card">
    <h3>Top rutas nacionales por volumen (color = índice de desempeño)</h3>
    <canvas id="chart-nacional"></canvas>
    <div class="card-botones">
      <button id="btn-csv-nacional">Descargar CSV</button>
      <button id="btn-jpeg-nacional">Descargar JPEG</button>
    </div>
    <div class="ranking" id="ranking-nacional"></div>
  </div>

  <div class="card">
    <h3>Top rutas urbanas — São Paulo (color = índice de desempeño)</h3>
    <canvas id="chart-urbano"></canvas>
    <div class="card-botones">
      <button id="btn-csv-urbano">Descargar CSV</button>
      <button id="btn-jpeg-urbano">Descargar JPEG</button>
    </div>
    <div class="ranking" id="ranking-urbano"></div>
  </div>
</div>

<footer>Geografía de ventas · Dashboard 360 — Olist Brazilian E-commerce · gráficos sin dependencias externas</footer>

<script>
__UTILIDADES__

const DATA = __PAYLOAD_DATA__;

document.getElementById('meta-info').textContent =
  `${DATA.meta.total_pedidos.toLocaleString('es-CL')} pedidos · GMV ${DATA.meta.gmv_total_fmt} · ${DATA.meta.periodo}`;

const RAMPA_AZUL = ['#b7d3f6', '#86b6ef', '#5598e7', '#256abf', '#104281'];
function colorPorIndice(indice) {
  const t = Math.max(0, Math.min(100, indice || 0)) / 100;
  const i = Math.min(RAMPA_AZUL.length - 1, Math.floor(t * RAMPA_AZUL.length));
  return RAMPA_AZUL[i];
}

function nombreOrigen(f) { return f.seller_state || f.seller_city || '?'; }
function nombreDestino(f) { return f.customer_state || f.customer_city || '?'; }

function construirPanelFlujos(idCanvas, idRanking, idBtnCsv, idBtnJpeg, flujos, nombreArchivoCsv, limite) {
  const ordenados = [...flujos].sort((a, b) => b.volumen - a.volumen).slice(0, limite);
  const canvas = document.getElementById(idCanvas);

  mcBarrasHorizontales(canvas, {
    etiquetas: ordenados.map(f => `${nombreOrigen(f)} → ${nombreDestino(f)}`),
    valores: ordenados.map(f => f.volumen),
    colores: (i) => colorPorIndice(ordenados[i].indice_desempeno),
    alturaFila: 20,
    formatoTooltip: (i) => {
      const f = ordenados[i];
      return `${nombreOrigen(f)} → ${nombreDestino(f)}\nPedidos: ${f.volumen}\nÍndice de desempeño: ${f.indice_desempeno.toFixed(1)}`;
    },
  });

  const top5 = [...flujos].sort((a, b) => b.indice_desempeno - a.indice_desempeno).slice(0, 5);
  document.getElementById(idRanking).innerHTML =
    '<b>Top 5 por índice de desempeño</b>' +
    top5.map(f => `<div><span>${nombreOrigen(f)} → ${nombreDestino(f)}</span><span>${f.indice_desempeno.toFixed(1)}</span></div>`).join('');

  document.getElementById(idBtnCsv).addEventListener('click', () => {
    descargarTextoComoArchivo(arrayObjetosACSV(flujos), nombreArchivoCsv, 'text/csv');
  });
  document.getElementById(idBtnJpeg).addEventListener('click', () => {
    descargarCanvasComoJPEG(canvas, nombreArchivoCsv.replace('.csv', '.jpeg'));
  });
}

construirPanelFlujos('chart-nacional', 'ranking-nacional', 'btn-csv-nacional', 'btn-jpeg-nacional', DATA.flujos_nacionales, 'flujos_nacionales.csv', 20);
construirPanelFlujos('chart-urbano', 'ranking-urbano', 'btn-csv-urbano', 'btn-jpeg-urbano', DATA.flujos_urbanos, 'flujos_urbanos_sao_paulo.csv', 20);
</script>
</body>
</html>
"""

_PLANTILLA_ESTADISTICAS = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>Panel estadístico · Olist</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
__ESTILOS__
</style>
</head>
<body>
<header>
  <h1>Panel estadístico</h1>
  <p id="meta-info"></p>
  <nav class="tabs">
    <a href="dashboard_flujos.html">Flujos</a>
    <a class="activa" href="dashboard_estadisticas.html">Estadísticas</a>
    <a href="mapa_animado.html">Mapa animado</a>
  </nav>
</header>

<div class="grid">
  <div class="card">
    <h3>Distancia vs. días de entrega</h3>
    <canvas id="chart-entrega"></canvas>
    <div class="card-botones">
      <button id="btn-csv-entrega">CSV</button>
      <button id="btn-jpeg-entrega">JPEG</button>
    </div>
  </div>

  <div class="card">
    <h3>Distancia vs. costo de flete</h3>
    <canvas id="chart-flete"></canvas>
    <div class="card-botones">
      <button id="btn-csv-flete">CSV</button>
      <button id="btn-jpeg-flete">JPEG</button>
    </div>
  </div>

  <div class="card">
    <h3>Atraso vs. satisfacción</h3>
    <canvas id="chart-atraso"></canvas>
    <div class="card-botones">
      <button id="btn-csv-atraso">CSV</button>
      <button id="btn-jpeg-atraso">JPEG</button>
    </div>
  </div>

  <div class="card">
    <h3>GMV mensual</h3>
    <canvas id="chart-serie"></canvas>
    <div class="card-botones">
      <button id="btn-csv-serie">CSV</button>
      <button id="btn-jpeg-serie">JPEG</button>
    </div>
  </div>

  <div class="card">
    <h3>Top categorías (ticket promedio)</h3>
    <canvas id="chart-categorias"></canvas>
    <div class="card-botones">
      <button id="btn-csv-categorias">CSV</button>
      <button id="btn-jpeg-categorias">JPEG</button>
    </div>
  </div>

  <div class="card">
    <h3>Métodos de pago</h3>
    <canvas id="chart-pagos"></canvas>
    <div class="card-botones">
      <button id="btn-csv-pagos">CSV</button>
      <button id="btn-jpeg-pagos">JPEG</button>
    </div>
  </div>

  <div class="card">
    <h3>Top estados por GMV</h3>
    <canvas id="chart-estados"></canvas>
    <div class="card-botones">
      <button id="btn-csv-estados">CSV</button>
      <button id="btn-jpeg-estados">JPEG</button>
    </div>
  </div>

  <div class="card">
    <h3>Correlación entre variables</h3>
    <canvas id="chart-correlacion"></canvas>
    <div class="card-botones">
      <button id="btn-csv-correlacion">CSV</button>
      <button id="btn-jpeg-correlacion">JPEG</button>
    </div>
  </div>
</div>

<footer>Geografía de ventas · Dashboard 360 — Olist Brazilian E-commerce · gráficos sin dependencias externas</footer>

<script>
__UTILIDADES__

const DATA = __PAYLOAD_DATA__;

document.getElementById('meta-info').textContent =
  `${DATA.meta.total_pedidos.toLocaleString('es-CL')} pedidos · GMV ${DATA.meta.gmv_total_fmt} · ${DATA.meta.periodo}`;

function registrarDescargas(idBtnCsv, idBtnJpeg, canvas, filas, nombreBase) {
  document.getElementById(idBtnCsv).addEventListener('click', () => {
    descargarTextoComoArchivo(arrayObjetosACSV(filas), nombreBase + '.csv', 'text/csv');
  });
  document.getElementById(idBtnJpeg).addEventListener('click', () => {
    descargarCanvasComoJPEG(canvas, nombreBase + '.jpeg');
  });
}

// 1. Distancia vs. días de entrega
(() => {
  const d = DATA.stats.dispersion_distancia_entrega;
  const canvas = document.getElementById('chart-entrega');
  mcDispersion(canvas, {
    puntos: d.map(x => ({ x: x.distancia_km, y: x.dias_entrega, r: Math.max(2, Math.log2((x.count || 1) + 1) * 1.6), count: x.count })),
    color: 'rgba(57,135,229,0.55)',
    formatoTooltip: (p) => `Distancia: ${p.x} km\nDías entrega: ${p.y}\nPedidos: ${p.count != null ? p.count : '-'}`,
  });
  registrarDescargas('btn-csv-entrega', 'btn-jpeg-entrega', canvas, d, 'dispersion_distancia_entrega');
})();

// 2. Distancia vs. costo de flete
(() => {
  const d = DATA.stats.dispersion_distancia_flete;
  const canvas = document.getElementById('chart-flete');
  mcDispersion(canvas, {
    puntos: d.map(x => ({ x: x.distancia_km, y: x.freight_value, r: Math.max(2, Math.log2((x.count || 1) + 1) * 1.6), count: x.count })),
    color: 'rgba(217,89,38,0.55)',
    formatoTooltip: (p) => `Distancia: ${p.x} km\nFlete: R$ ${p.y}\nPedidos: ${p.count != null ? p.count : '-'}`,
  });
  registrarDescargas('btn-csv-flete', 'btn-jpeg-flete', canvas, d, 'dispersion_distancia_flete');
})();

// 3. Atraso vs. satisfacción
(() => {
  const d = DATA.stats.atraso_vs_satisfaccion;
  const canvas = document.getElementById('chart-atraso');
  mcBarrasVerticales(canvas, {
    etiquetas: d.map(x => x.bucket_atraso),
    valores: d.map(x => x.review_prom),
    color: '#c98500',
    formatoTooltip: (i) => `${d[i].bucket_atraso}\nReview promedio: ${d[i].review_prom}`,
  });
  registrarDescargas('btn-csv-atraso', 'btn-jpeg-atraso', canvas, d, 'atraso_vs_satisfaccion');
})();

// 4. Serie de tiempo de ventas
(() => {
  const d = DATA.stats.serie_tiempo_ventas;
  const canvas = document.getElementById('chart-serie');
  mcLinea(canvas, {
    etiquetas: d.map(x => x.mes_compra),
    valores: d.map(x => x.gmv),
    color: '#008300',
    colorRelleno: 'rgba(0,131,0,0.15)',
    formatoTooltip: (i) => `${d[i].mes_compra}\nGMV: R$ ${d[i].gmv}`,
  });
  registrarDescargas('btn-csv-serie', 'btn-jpeg-serie', canvas, d, 'serie_tiempo_ventas');
})();

// 5. Top categorías
(() => {
  const d = [...DATA.stats.top_categorias].sort((a, b) => b.ticket_prom - a.ticket_prom);
  const canvas = document.getElementById('chart-categorias');
  mcBarrasHorizontales(canvas, {
    etiquetas: d.map(x => x.product_category_name_english),
    valores: d.map(x => x.ticket_prom),
    colores: '#9085e9',
    alturaFila: 20,
    formatoTooltip: (i) => `${d[i].product_category_name_english}\nTicket promedio: R$ ${d[i].ticket_prom}`,
  });
  registrarDescargas('btn-csv-categorias', 'btn-jpeg-categorias', canvas, d, 'top_categorias');
})();

// 6. Métodos de pago
(() => {
  const d = DATA.stats.metodos_pago;
  const canvas = document.getElementById('chart-pagos');
  const colores = ['#3987e5', '#199e70', '#c98500', '#008300', '#9085e9', '#e66767'];
  mcDona(canvas, {
    etiquetas: d.map(x => x.payment_type),
    valores: d.map(x => x.n_pagos),
    colores,
    formatoTooltip: (i) => `${d[i].payment_type}\nPagos: ${d[i].n_pagos}`,
  });
  registrarDescargas('btn-csv-pagos', 'btn-jpeg-pagos', canvas, d, 'metodos_pago');
})();

// 7. Top estados por GMV
(() => {
  const d = [...DATA.stats.top_estados_gmv].sort((a, b) => b.gmv - a.gmv);
  const canvas = document.getElementById('chart-estados');
  mcBarrasHorizontales(canvas, {
    etiquetas: d.map(x => x.customer_state),
    valores: d.map(x => x.gmv),
    colores: '#e66767',
    alturaFila: 20,
    formatoTooltip: (i) => `${d[i].customer_state}\nGMV: R$ ${d[i].gmv}`,
  });
  registrarDescargas('btn-csv-estados', 'btn-jpeg-estados', canvas, d, 'top_estados_gmv');
})();

// 8. Matriz de correlación (mapa de calor divergente azul-rojo; polaridad -1..+1)
(() => {
  const columnas = DATA.stats.matriz_correlacion.columnas;
  const matriz = DATA.stats.matriz_correlacion.datos;
  const canvas = document.getElementById('chart-correlacion');
  const n = columnas.length;
  const tam = 260;
  const dpr = window.devicePixelRatio || 1;
  canvas.style.width = tam + 'px';
  canvas.style.height = tam + 'px';
  canvas.width = Math.round(tam * dpr);
  canvas.height = Math.round(tam * dpr);
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const celda = tam / n;

  function colorDivergente(valor) {
    const t = Math.max(-1, Math.min(1, valor));
    const gris = [56, 56, 53];
    const azul = [57, 135, 229];
    const rojo = [230, 103, 103];
    const objetivo = t >= 0 ? azul : rojo;
    const u = Math.abs(t);
    const r = Math.round(gris[0] + (objetivo[0] - gris[0]) * u);
    const g = Math.round(gris[1] + (objetivo[1] - gris[1]) * u);
    const b = Math.round(gris[2] + (objetivo[2] - gris[2]) * u);
    return `rgb(${r},${g},${b})`;
  }

  ctx.font = '9px system-ui, sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  for (let i = 0; i < n; i++) {
    for (let j = 0; j < n; j++) {
      const valor = matriz[i][j];
      ctx.fillStyle = colorDivergente(valor);
      ctx.fillRect(j * celda, i * celda, celda - 2, celda - 2);
      ctx.fillStyle = Math.abs(valor) > 0.55 ? '#ffffff' : '#c3c2b7';
      ctx.fillText(valor.toFixed(2), j * celda + celda / 2, i * celda + celda / 2);
    }
  }

  const filasCSV = columnas.map((c, i) => {
    const fila = { variable: c };
    columnas.forEach((c2, j) => { fila[c2] = matriz[i][j]; });
    return fila;
  });
  registrarDescargas('btn-csv-correlacion', 'btn-jpeg-correlacion', canvas, filasCSV, 'matriz_correlacion');
})();
</script>
</body>
</html>
"""


# CSS adicional solo para el mapa animado (canvas a todo ancho + leyenda).
_ESTILOS_MAPA = r"""
#mapa-card { padding: 14px 16px 16px; }
#mapa-canvas { width: 100%; height: 480px; display: block; border-radius: 8px; cursor: default; }
#leyenda-mapa {
  display: flex; flex-wrap: wrap; gap: 18px; margin-top: 12px; font-size: 11.5px; color: #c3c2b7;
}
#leyenda-mapa .grupo { display: flex; align-items: center; gap: 6px; }
#leyenda-mapa .rampa {
  width: 70px; height: 8px; border-radius: 4px;
  background: linear-gradient(90deg, #b7d3f6, #86b6ef, #5598e7, #256abf, #104281);
}
.layout-mapa { display: grid; grid-template-columns: minmax(0, 1fr) 260px; gap: 16px; align-items: start; }
@media (max-width: 860px) { .layout-mapa { grid-template-columns: 1fr; } }
"""

_PLANTILLA_MAPA = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>Mapa animado de flujos · Olist</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
__ESTILOS__
__ESTILOS_MAPA__
</style>
</head>
<body>
<header>
  <h1>Mapa animado de flujos nacionales</h1>
  <p id="meta-info"></p>
  <nav class="tabs">
    <a href="dashboard_flujos.html">Flujos</a>
    <a href="dashboard_estadisticas.html">Estadísticas</a>
    <a class="activa" href="mapa_animado.html">Mapa animado</a>
  </nav>
</header>

<div class="layout-mapa">
  <div class="card" id="mapa-card">
    <h3>Corrientes de pedidos entre estados (animación continua)</h3>
    <canvas id="mapa-canvas"></canvas>
    <div id="leyenda-mapa">
      <div class="grupo"><span>Menor índice</span><span class="rampa"></span><span>Mayor índice de desempeño</span></div>
      <div class="grupo">● Tamaño del nodo = volumen de pedidos</div>
    </div>
    <div class="card-botones">
      <button id="btn-csv-mapa">Descargar CSV</button>
      <button id="btn-jpeg-mapa">Descargar imagen (JPEG)</button>
    </div>
  </div>

  <div class="card">
    <h3>Top 5 por índice de desempeño</h3>
    <div class="ranking" id="ranking-mapa"></div>
  </div>
</div>

<footer>Geografía de ventas · Dashboard 360 — Olist Brazilian E-commerce · animación en Canvas puro, sin dependencias externas</footer>

<script>
__UTILIDADES__

const DATA = __PAYLOAD_DATA__;

document.getElementById('meta-info').textContent =
  `${DATA.meta.total_pedidos.toLocaleString('es-CL')} pedidos · GMV ${DATA.meta.gmv_total_fmt} · ${DATA.meta.periodo}`;

const RAMPA_AZUL = ['#b7d3f6', '#86b6ef', '#5598e7', '#256abf', '#104281'];
function colorPorIndice(indice) {
  const t = Math.max(0, Math.min(100, indice || 0)) / 100;
  const i = Math.min(RAMPA_AZUL.length - 1, Math.floor(t * RAMPA_AZUL.length));
  return RAMPA_AZUL[i];
}

/* ---- geometría: proyección lat/lng -> pixeles, dentro de los límites de los nodos ---- */
function calcularBounds(nodos) {
  return {
    latMin: Math.min(...nodos.map(n => n.lat)),
    latMax: Math.max(...nodos.map(n => n.lat)),
    lngMin: Math.min(...nodos.map(n => n.lng)),
    lngMax: Math.max(...nodos.map(n => n.lng)),
  };
}
function proyectar(lat, lng, bounds, ancho, alto) {
  const margen = 46;
  const rangoLat = Math.max(bounds.latMax - bounds.latMin, 0.0001);
  const rangoLng = Math.max(bounds.lngMax - bounds.lngMin, 0.0001);
  const rango = Math.max(rangoLat, rangoLng);
  const cx = (bounds.lngMin + bounds.lngMax) / 2;
  const cy = (bounds.latMin + bounds.latMax) / 2;
  const escala = (Math.min(ancho, alto) - margen * 2) / rango;
  return {
    x: ancho / 2 + (lng - cx) * escala,
    y: alto / 2 - (lat - cy) * escala,
  };
}

/* ---- envolvente convexa (Andrew's monotone chain) para dibujar la "silueta" del mapa,
   calculada a partir de los propios centroides de los estados -- nada de datos geográficos
   externos ni coordenadas hardcodeadas. ---- */
function envolventeConvexa(puntos) {
  const pts = [...puntos].sort((a, b) => a.x - b.x || a.y - b.y);
  if (pts.length < 3) return pts;
  const cruz = (o, a, b) => (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x);
  const inferior = [];
  for (const p of pts) {
    while (inferior.length >= 2 && cruz(inferior[inferior.length - 2], inferior[inferior.length - 1], p) <= 0) inferior.pop();
    inferior.push(p);
  }
  const superior = [];
  for (let i = pts.length - 1; i >= 0; i--) {
    const p = pts[i];
    while (superior.length >= 2 && cruz(superior[superior.length - 2], superior[superior.length - 1], p) <= 0) superior.pop();
    superior.push(p);
  }
  superior.pop(); inferior.pop();
  return inferior.concat(superior);
}

function dibujarSiluetaMapa(ctx, puntos) {
  const hull = envolventeConvexa(puntos);
  if (hull.length < 3) return;
  const cx = hull.reduce((s, p) => s + p.x, 0) / hull.length;
  const cy = hull.reduce((s, p) => s + p.y, 0) / hull.length;
  const inflado = hull.map(p => {
    const dx = p.x - cx, dy = p.y - cy;
    const d = Math.hypot(dx, dy) || 1;
    return { x: p.x + (dx / d) * 34, y: p.y + (dy / d) * 34 };
  });
  ctx.beginPath();
  const n = inflado.length;
  for (let i = 0; i < n; i++) {
    const p0 = inflado[i];
    const p1 = inflado[(i + 1) % n];
    const mx = (p0.x + p1.x) / 2, my = (p0.y + p1.y) / 2;
    if (i === 0) ctx.moveTo(mx, my);
    else ctx.quadraticCurveTo(p0.x, p0.y, mx, my);
  }
  ctx.closePath();
  ctx.fillStyle = 'rgba(57,135,229,0.07)';
  ctx.fill();
  ctx.strokeStyle = 'rgba(57,135,229,0.28)';
  ctx.lineWidth = 1.5;
  ctx.stroke();
}

/* ---- construcción de nodos (centroides por estado) y arcos a partir de los flujos ---- */
function construirNodos(flujos) {
  const mapa = new Map();
  function agregar(nombre, lat, lng, volumen, indice) {
    if (lat == null || lng == null) return;
    if (!mapa.has(nombre)) mapa.set(nombre, { nombre, lat, lng, volumen: 0, sumaIndice: 0, n: 0 });
    const n = mapa.get(nombre);
    n.volumen += volumen; n.sumaIndice += indice; n.n += 1;
  }
  flujos.forEach(f => {
    agregar(f.seller_state, f.lat_origen, f.lng_origen, f.volumen, f.indice_desempeno);
    agregar(f.customer_state, f.lat_destino, f.lng_destino, f.volumen, f.indice_desempeno);
  });
  return [...mapa.values()].map(n => ({ ...n, indiceProm: n.sumaIndice / n.n }));
}

const flujos = DATA.flujos_nacionales.filter(f => f.lat_origen != null && f.lat_destino != null);
const nodosBase = construirNodos(flujos);
const bounds = calcularBounds(nodosBase);
const volMaxNodo = Math.max(...nodosBase.map(n => n.volumen), 1);
const volMaxArco = Math.max(...flujos.map(f => f.volumen), 1);

const arcosBase = flujos.map(f => ({
  nombreOrigen: f.seller_state, nombreDestino: f.customer_state,
  origen: { lat: f.lat_origen, lng: f.lng_origen },
  destino: { lat: f.lat_destino, lng: f.lng_destino },
  indice: f.indice_desempeno, volumen: f.volumen,
  velocidad: 0.00032 + 0.00028 * Math.random(),
  fase: Math.random(),
}));

function puntoBezier(p0, p1, p2, t) {
  const u = 1 - t;
  return { x: u * u * p0.x + 2 * u * t * p1.x + t * t * p2.x, y: u * u * p0.y + 2 * u * t * p1.y + t * t * p2.y };
}
function calcularCurva(o, d, ancho, alto) {
  const po = proyectar(o.lat, o.lng, bounds, ancho, alto);
  const pd = proyectar(d.lat, d.lng, bounds, ancho, alto);
  const dx = pd.x - po.x, dy = pd.y - po.y;
  const dist = Math.hypot(dx, dy);
  const alturaArco = Math.max(16, dist * 0.22);
  return {
    p0: po,
    p1: { x: (po.x + pd.x) / 2, y: (po.y + pd.y) / 2 - alturaArco },
    p2: pd,
  };
}

/* ---- animación ---- */
const canvas = document.getElementById('mapa-canvas');
const ctx = canvas.getContext('2d');
let nodosProyectadosActuales = [];

function ajustarCanvas() {
  const dpr = window.devicePixelRatio || 1;
  const ancho = canvas.clientWidth || 600;
  const alto = canvas.clientHeight || 480;
  const anchoBuffer = Math.round(ancho * dpr);
  const altoBuffer = Math.round(alto * dpr);
  if (canvas.width !== anchoBuffer || canvas.height !== altoBuffer) {
    canvas.width = anchoBuffer;
    canvas.height = altoBuffer;
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ancho, alto };
}

function animar() {
  const { ancho, alto } = ajustarCanvas();
  ctx.clearRect(0, 0, ancho, alto);

  dibujarSiluetaMapa(ctx, nodosBase.map(n => proyectar(n.lat, n.lng, bounds, ancho, alto)));

  const t = performance.now();

  ctx.lineCap = 'round';
  for (const arco of arcosBase) {
    const curva = calcularCurva(arco.origen, arco.destino, ancho, alto);
    ctx.beginPath();
    ctx.moveTo(curva.p0.x, curva.p0.y);
    ctx.quadraticCurveTo(curva.p1.x, curva.p1.y, curva.p2.x, curva.p2.y);
    ctx.strokeStyle = colorPorIndice(arco.indice);
    ctx.globalAlpha = 0.18 + 0.35 * (arco.volumen / volMaxArco);
    ctx.lineWidth = 1 + 2 * (arco.volumen / volMaxArco);
    ctx.stroke();
  }
  ctx.globalAlpha = 1;

  for (const arco of arcosBase) {
    const curva = calcularCurva(arco.origen, arco.destino, ancho, alto);
    const u = (t * arco.velocidad + arco.fase) % 1;
    const p = puntoBezier(curva.p0, curva.p1, curva.p2, u);
    const color = colorPorIndice(arco.indice);
    ctx.beginPath();
    ctx.fillStyle = color;
    ctx.shadowColor = color;
    ctx.shadowBlur = 6;
    ctx.arc(p.x, p.y, 2.4, 0, Math.PI * 2);
    ctx.fill();
    ctx.shadowBlur = 0;
  }

  nodosProyectadosActuales = nodosBase.map(n => {
    const p = proyectar(n.lat, n.lng, bounds, ancho, alto);
    return { ...n, x: p.x, y: p.y, radio: 4 + 16 * Math.sqrt(n.volumen / volMaxNodo) };
  });
  for (const n of nodosProyectadosActuales) {
    ctx.beginPath();
    ctx.fillStyle = colorPorIndice(n.indiceProm);
    ctx.arc(n.x, n.y, n.radio, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = 'rgba(255,255,255,0.28)';
    ctx.lineWidth = 1;
    ctx.stroke();

    ctx.fillStyle = '#ffffff';
    ctx.font = '10px system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'bottom';
    ctx.fillText(n.nombre, n.x, n.y - n.radio - 3);
  }

  requestAnimationFrame(animar);
}
requestAnimationFrame(animar);

canvas.addEventListener('mousemove', (ev) => {
  const rect = canvas.getBoundingClientRect();
  const mx = ev.clientX - rect.left, my = ev.clientY - rect.top;
  const cercano = nodosProyectadosActuales.find(n => Math.hypot(mx - n.x, my - n.y) <= n.radio + 4);
  if (cercano) {
    mcMostrarTooltip(ev.clientX, ev.clientY,
      `${cercano.nombre}\nVolumen: ${cercano.volumen}\nÍndice de desempeño: ${cercano.indiceProm.toFixed(1)}`);
  } else {
    mcOcultarTooltip();
  }
});
canvas.addEventListener('mouseleave', mcOcultarTooltip);

const top5 = [...nodosBase].sort((a, b) => b.indiceProm - a.indiceProm).slice(0, 5);
document.getElementById('ranking-mapa').innerHTML =
  top5.map(n => `<div><span>${n.nombre}</span><span>${n.indiceProm.toFixed(1)}</span></div>`).join('');

document.getElementById('btn-csv-mapa').addEventListener('click', () => {
  descargarTextoComoArchivo(arrayObjetosACSV(DATA.flujos_nacionales), 'flujos_nacionales.csv', 'text/csv');
});
document.getElementById('btn-jpeg-mapa').addEventListener('click', () => {
  descargarCanvasComoJPEG(canvas, 'mapa_flujos_nacionales.jpeg');
});
</script>
</body>
</html>
"""


def _renderizar(plantilla: str, payload_recortado: Dict[str, Any]) -> str:
    payload_json = json.dumps(payload_recortado, ensure_ascii=False)
    payload_json = payload_json.replace('</script>', '<\\/script>')
    html = plantilla.replace('__ESTILOS__', _ESTILOS_CSS)
    html = html.replace('__ESTILOS_MAPA__', _ESTILOS_MAPA)
    html = html.replace('__UTILIDADES__', _UTILIDADES_JS)
    html = html.replace('__PAYLOAD_DATA__', payload_json)
    return html


def construir_dashboard_flujos_html(payload: Dict[str, Any], ruta_salida: Path) -> Path:
    """Escribe el dashboard de flujos nacionales/urbanos (liviano, sin mapa animado)."""
    ruta_salida.parent.mkdir(parents=True, exist_ok=True)
    payload_recortado = {
        "meta": payload["meta"],
        "flujos_nacionales": payload["flujos_nacionales"],
        "flujos_urbanos": payload["flujos_urbanos"],
    }
    html = _renderizar(_PLANTILLA_FLUJOS, payload_recortado)
    ruta_salida.write_text(html, encoding='utf-8')
    logger.info("Dashboard de flujos escrito en %s (%.1f KB)", ruta_salida, ruta_salida.stat().st_size / 1024)
    return ruta_salida


def construir_dashboard_estadisticas_html(payload: Dict[str, Any], ruta_salida: Path) -> Path:
    """Escribe el dashboard con los 8 paneles estadísticos (liviano, sin ruleta 3D)."""
    ruta_salida.parent.mkdir(parents=True, exist_ok=True)
    payload_recortado = {
        "meta": payload["meta"],
        "stats": payload["stats"],
    }
    html = _renderizar(_PLANTILLA_ESTADISTICAS, payload_recortado)
    ruta_salida.write_text(html, encoding='utf-8')
    logger.info("Dashboard estadístico escrito en %s (%.1f KB)", ruta_salida, ruta_salida.stat().st_size / 1024)
    return ruta_salida


def construir_mapa_animado_html(payload: Dict[str, Any], ruta_salida: Path) -> Path:
    """Escribe el mapa animado 2D (flujos nacionales en movimiento continuo, sin dependencias externas)."""
    ruta_salida.parent.mkdir(parents=True, exist_ok=True)
    payload_recortado = {
        "meta": payload["meta"],
        "flujos_nacionales": payload["flujos_nacionales"],
    }
    html = _renderizar(_PLANTILLA_MAPA, payload_recortado)
    ruta_salida.write_text(html, encoding='utf-8')
    logger.info("Mapa animado escrito en %s (%.1f KB)", ruta_salida, ruta_salida.stat().st_size / 1024)
    return ruta_salida
