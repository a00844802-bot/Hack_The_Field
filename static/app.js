let analysis = null;

const $ = (id) => document.getElementById(id);
const fmt = (n) => new Intl.NumberFormat().format(n);

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
    ['Machines monitored', s.machines],
    ['Critical faults', s.critical],
    ['Predictive alerts', s.predictive],
    ['Healthy machines', s.healthy],
  ].map(([label, value]) => `<div class="metric"><span>${label}</span><strong>${value}</strong></div>`).join('');
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
        <span class="badge ${a.severity}">${a.severity}</span>
      </div>
      <p>${a.detail}. Current ${labelMetric(a.metric)}: <b>${a.current}</b>; threshold: <b>${a.threshold}</b>.</p>
      <p class="muted">${a.hoursToThreshold === 0 ? 'Fault is active now.' : `Predicted threshold crossing in ${a.hoursToThreshold ?? '—'} hours.`} Confidence: ${(a.confidence * 100).toFixed(0)}%.</p>
      <button onclick='preparePart(${JSON.stringify(a)})'>Prepare ${a.recommendedPart}</button>
    </article>`).join('') : '<p class="muted">No alerts match this filter.</p>';
}

function renderDealer() {
  const maxHours = Math.max(...analysis.dealer.usageByRegion.map(r => r.hours));
  $('regionUsage').innerHTML = analysis.dealer.usageByRegion.map(r => `
    <div class="bar-row">
      <div class="bar-meta"><span>${r.region}</span><span>${fmt(r.hours)} hrs • avg risk ${r.avgRisk}</span></div>
      <div class="bar-track"><div class="bar-fill" style="width:${Math.max(5, r.hours / maxHours * 100)}%"></div></div>
    </div>`).join('');

  $('partsForecast').innerHTML = analysis.dealer.partsForecast.length ? analysis.dealer.partsForecast.map(p => `
    <div class="part-card">
      <h3>${p.part}</h3>
      <p class="muted">SKU ${p.sku} • Suggested quantity: <b>${p.quantity}</b></p>
      <p>Machines: ${p.machines.join(', ')}</p>
    </div>`).join('') : '<p class="muted">No parts need preparation right now.</p>';
}

function renderFleet() {
  const q = $('searchBox').value.trim().toLowerCase();
  const rows = analysis.fleet.filter(f => `${f.machine.id} ${f.machine.customer} ${f.machine.model}`.toLowerCase().includes(q));
  $('fleetTable').innerHTML = rows.map(f => {
    const topTrends = f.tendencies
      .filter(t => t.direction !== 'stable')
      .slice(0, 3)
      .map(t => `${labelMetric(t.metric)} ${t.direction} (${t.trend24h > 0 ? '+' : ''}${t.trend24h}/24h)`)
      .join('<br>') || 'Stable';
    return `<tr>
      <td><b>${f.machine.id}</b></td>
      <td>${f.machine.customer}</td>
      <td>${f.machine.model}</td>
      <td>${fmt(f.machine.hours)}</td>
      <td class="risk"><b>${f.riskScore}</b><div class="risk-meter"><span style="width:${f.riskScore}%"></span></div></td>
      <td>${topTrends}</td>
      <td><span class="badge ${f.status === 'critical' ? 'critical' : f.status === 'warning' ? 'warning' : 'watch'}">${f.status}</span></td>
    </tr>`;
  }).join('');
}

function labelMetric(metric) {
  return metric.replaceAll('_', ' ').replace(/\b\w/g, c => c.toUpperCase());
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
  document.body.innerHTML = `<main><section class="card"><h1>Could not load dashboard</h1><p>${err.message}</p></section></main>`;
});
