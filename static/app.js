let analysis = null;

const $ = (id) => document.getElementById(id);
const fmt = (n) => new Intl.NumberFormat('es-ES').format(n);

const metricLabels = {
  engine_temp: 'temperatura del motor',
  oil_pressure: 'presión de aceite',
  hydraulic_pressure: 'presión hidráulica',
  vibration: 'vibración',
  battery_voltage: 'voltaje de batería',
  dpf_load: 'carga del DPF',
  usage_hours: 'horas de uso',
  cycles: 'ciclos de trabajo',
};

const severityLabels = {
  critical: 'Crítico',
  warning: 'Advertencia',
  watch: 'Observación',
};

const statusLabels = {
  critical: 'Crítico',
  warning: 'Advertencia',
  watch: 'Observación',
};

const WS_PORT = 8001;
const wsUrl = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.hostname}:${WS_PORT}/ws`;
let ws = null;
let reconnectTimer = null;

function connectWebSocket() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
    return;
  }

  ws = new WebSocket(wsUrl);
  ws.addEventListener('open', () => {
    console.info('Realtime websocket connected');
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
  });

  ws.addEventListener('message', (event) => {
    try {
      const payload = JSON.parse(event.data);
      if (payload.type === 'analysis' && payload.data) {
        analysis = payload.data;
        render();
      }
    } catch (error) {
      console.warn('Invalid websocket payload', error);
    }
  });

  ws.addEventListener('close', () => {
    console.info('Realtime websocket disconnected, retrying...');
    reconnectTimer = setTimeout(connectWebSocket, 2000);
  });

  ws.addEventListener('error', () => {
    ws.close();
  });
}

async function loadAnalysis() {
  const res = await fetch('/api/analysis');
  analysis = await res.json();
  render();
}

function render() {
  renderSummary();
  renderAlerts();
  renderDealer();
  renderFleet();
}

function renderSummary() {
  const s = analysis.dealer.summary;
  $('summaryCards').innerHTML = [
    ['Máquinas monitorizadas', s.machines],
    ['Fallas críticas', s.critical],
    ['Alertas predictivas', s.predictive],
    ['Máquinas saludables', s.healthy],
  ].map(([label, value]) => `<div class="metric"><span>${label}</span><strong>${fmt(value)}</strong></div>`).join('');
}

function renderAlerts() {
  const filter = $('severityFilter').value;
  const alerts = analysis.alerts.filter(a => filter === 'all' || a.severity === filter);
  $('alertsList').innerHTML = alerts.length ? alerts.map(a => `
    <article class="alert ${a.severity}">
      <div class="alert-top">
        <div>
          <h3>${a.title}</h3>
          <p class="muted">${a.machineId} • ${a.customer} • ${a.model}</p>
        </div>
        <span class="badge ${a.severity}">${severityLabels[a.severity] || a.severity}</span>
      </div>
      <p>${a.detail}. Actual ${labelMetric(a.metric)}: <b>${a.current}</b>; umbral: <b>${a.threshold}</b>.</p>
      <p class="muted">${a.hoursToThreshold === 0 ? 'El fallo está activo ahora.' : `Umbral previsto en ${a.hoursToThreshold ?? '—'} horas.`} Confianza: ${(a.confidence * 100).toFixed(0)}%.</p>
      <button onclick='preparePart(${JSON.stringify(a)})'>Preparar ${a.recommendedPart}</button>
    </article>`).join('') : '<p class="muted">No hay alertas que coincidan con este filtro.</p>';
}

function renderDealer() {
  const maxHours = Math.max(...analysis.dealer.usageByRegion.map(r => r.hours));
  $('regionUsage').innerHTML = analysis.dealer.usageByRegion.map(r => `
    <div class="bar-row">
      <div class="bar-meta"><span>${r.region}</span><span>${fmt(r.hours)} h • riesgo medio ${r.avgRisk}</span></div>
      <div class="bar-track"><div class="bar-fill" style="width:${Math.max(5, (r.hours / maxHours) * 100)}%"></div></div>
    </div>`).join('');

  $('partsForecast').innerHTML = analysis.dealer.partsForecast.length ? analysis.dealer.partsForecast.map(p => `
    <div class="part-card">
      <h3>${p.part}</h3>
      <p class="muted">SKU ${p.sku} • Cantidad sugerida: <b>${p.quantity}</b></p>
      <p>Máquinas: ${p.machines.join(', ')}</p>
    </div>`).join('') : '<p class="muted">No se necesitan repuestos ahora mismo.</p>';
}

function renderFleet() {
  const q = $('searchBox').value.trim().toLowerCase();
  const rows = analysis.fleet.filter(f => `${f.machine.id} ${f.machine.customer} ${f.machine.model}`.toLowerCase().includes(q));
  $('fleetTable').innerHTML = rows.map(f => {
    const topTrends = f.tendencies
      .filter(t => t.direction !== 'stable')
      .slice(0, 3)
      .map(t => `${labelMetric(t.metric)} ${translateDirection(t.direction)} (${t.trend24h > 0 ? '+' : ''}${t.trend24h}/24h)`)
      .join('<br>') || 'Estable';
    return `<tr>
      <td><b>${f.machine.id}</b></td>
      <td>${f.machine.customer}</td>
      <td>${f.machine.model}</td>
      <td>${fmt(f.machine.hours)}</td>
      <td class="risk"><b>${f.riskScore}</b><div class="risk-meter"><span style="width:${f.riskScore}%"></span></div></td>
      <td>${topTrends}</td>
      <td><span class="badge ${f.status === 'critical' ? 'critical' : f.status === 'warning' ? 'warning' : 'watch'}">${statusLabels[f.status] || f.status}</span></td>
    </tr>`;
  }).join('');
}

function labelMetric(metric) {
  return metricLabels[metric] || metric.replaceAll('_', ' ').replace(/\b\w/g, c => c.toUpperCase());
}

function translateDirection(direction) {
  return direction === 'increasing'
    ? 'aumenta'
    : direction === 'decreasing'
    ? 'disminuye'
    : 'estable';
}

async function preparePart(alert) {
  const res = await fetch('/api/prepare-part', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ machineId: alert.machineId, sku: alert.sku, part: alert.recommendedPart, reason: alert.title })
  });
  const data = await res.json();
  $('dialogMessage').textContent = data.message || data.error;
  $('partDialog').showModal();
}

$('refreshBtn').addEventListener('click', loadAnalysis);
$('severityFilter').addEventListener('change', renderAlerts);
$('searchBox').addEventListener('input', renderFleet);

loadAnalysis().catch(err => {
  document.body.innerHTML = `<main><section class="card"><h1>No se pudo cargar el panel</h1><p>${err.message}</p></section></main>`;
}).finally(() => {
  connectWebSocket();
});

setInterval(loadAnalysis, 5000);

// Dealer keyword-based chat widget
(function(){
  function initChat(){
    const toggle = document.getElementById('chatToggle');
    const popup = document.getElementById('chatPopup');
    const closeBtn = document.getElementById('chatClose');
    const form = document.getElementById('chatForm');
    const input = document.getElementById('chatInput');
    const messages = document.getElementById('chatMessages');

    if(!toggle || !popup || !form || !input || !messages) return;

    function appendMessage(who, text){
      const el = document.createElement('div');
      el.className = 'chat-message ' + (who === 'user' ? 'user' : 'bot');
      el.textContent = text;
      messages.appendChild(el);
      messages.scrollTop = messages.scrollHeight;
    }

    function botReply(text){
      appendMessage('bot', text);
    }

    function helpText(){
      return "Prueba palabras clave: 'resumen', 'alertas recientes', 'repuestos', 'máquinas', 'riesgo', 'últimos eventos'.";
    }

    function summarizeAnalysis(){
      if(!analysis) return 'Análisis no disponible.';
      const s = analysis.dealer.summary;
      return `Resumen: ${s.machines} máquinas — Críticos: ${s.critical}, Predictivos: ${s.predictive}, Saludables: ${s.healthy}. Generado: ${analysis.generatedAt}`;
    }

    function recentAlerts(){
      if(!analysis) return 'Análisis no disponible.';
      const list = analysis.alerts.slice(0,5);
      if(list.length === 0) return 'No hay alertas recientes.';
      return list.map(a => `${a.machineId}: ${a.title} (${a.severity}) — ${a.detail}`).join('\n');
    }

    function partsForecast(){
      if(!analysis) return 'Análisis no disponible.';
      const parts = analysis.dealer.partsForecast.slice(0,5);
      if(parts.length === 0) return 'No hay repuestos sugeridos ahora.';
      return parts.map(p => `${p.part} (SKU ${p.sku}) — Cantidad ${p.quantity}`).join('\n');
    }

    function topRisk(){
      if(!analysis) return 'Análisis no disponible.';
      const top = analysis.fleet.slice().sort((a,b)=>b.riskScore - a.riskScore).slice(0,3);
      if(top.length===0) return 'Sin datos de riesgo.';
      return top.map(t => `${t.machine.id} — ${t.customer} — Riesgo ${t.riskScore}`).join('\n');
    }

    function handleQuery(q){
      q = q.toLowerCase();
      if(q.includes('resumen') || q.includes('summary') || q.includes('important')) return summarizeAnalysis();
      if(q.includes('alert') || q.includes('alertas') || q.includes('reciente') || q.includes('recent')) return recentAlerts();
      if(q.includes('repuesto') || q.includes('parts') || q.includes('repuestos')) return partsForecast();
      if(q.includes('máquina') || q.includes('maquina') || q.includes('machines') || q.includes('fleet')) return `Máquinas monitorizadas: ${analysis ? analysis.dealer.summary.machines : '—'}`;
      if(q.includes('riesgo') || q.includes('risk') || q.includes('top risk')) return topRisk();
      if(q.includes('evento') || q.includes('event') || q.includes('último') || q.includes('ultimo')) return recentAlerts();
      return "No he entendido. " + helpText();
    }

    toggle.addEventListener('click', ()=>{
      const hidden = popup.getAttribute('aria-hidden') === 'true';
      popup.setAttribute('aria-hidden', String(!hidden));
      if(!hidden) input.focus();
    });
    closeBtn.addEventListener('click', ()=> popup.setAttribute('aria-hidden','true'));

    form.addEventListener('submit', (ev)=>{
      ev.preventDefault();
      const q = input.value.trim();
      if(!q) return;
      appendMessage('user', q);
      const reply = handleQuery(q);
      // small delay to simulate thinking
      setTimeout(()=> botReply(reply), 250);
      input.value = '';
    });

    // welcome message
    appendMessage('bot', 'Hola — soy el asistente del concesionario. ' + helpText());
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initChat);
  else initChat();
})();
