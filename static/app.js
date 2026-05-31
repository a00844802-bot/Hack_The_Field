let analysis = null;
let selectedMachine = null;

const $ = (id) => document.getElementById(id);
const fmt = (n) => new Intl.NumberFormat().format(n);

async function loadAnalysis() {
  const res = await fetch('/api/analysis');
  analysis = await res.json();
  render();
}

function render() {
  renderFleetGrid();
}

function getColorForUsage(hours, maxHours = 5400) {
  const percent = Math.min(100, (hours / maxHours) * 100);
  if (percent < 30) return '--ok';
  if (percent < 60) return '--warning';
  return '--danger';
}

function getRiskStatus(riskScore) {
  if (riskScore >= 60) return 'critical';
  if (riskScore >= 30) return 'warning';
  return 'healthy';
}

function renderFleetGrid() {
  const grid = $('tractorsGrid');
  grid.innerHTML = analysis.fleet.map(f => {
    const hours = f.machine.hours;
    const maxHours = 5400;
    const usagePercent = Math.min(100, (hours / maxHours) * 100);
    const colorVar = getColorForUsage(hours);
    const riskStatus = getRiskStatus(f.riskScore);
    
    return `
      <div class="tractor-card" onclick="openTractorDetail('${f.machine.id}')">
        <div class="tractor-icon-box">
          <svg viewBox="0 0 200 120" xmlns="http://www.w3.org/2000/svg">
            <rect x="20" y="50" width="160" height="30" rx="5" fill="#367C2B" stroke="#27251F" stroke-width="2"/>
            <circle cx="40" cy="85" r="15" fill="#27251F" stroke="#666" stroke-width="1"/>
            <circle cx="160" cy="85" r="15" fill="#27251F" stroke="#666" stroke-width="1"/>
            <rect x="110" y="35" width="40" height="20" rx="3" fill="#FFDE00" stroke="#27251F" stroke-width="2"/>
            <text x="130" y="50" text-anchor="middle" font-size="12" fill="#27251F" font-weight="bold">JD</text>
          </svg>
        </div>
        
        <div class="tractor-info">
          <h3>${f.machine.id}</h3>
          <p>${f.machine.model}</p>
          <p>${f.machine.customer}</p>
        </div>

        <div class="tractor-meter">
          <div class="meter-label">
            <span class="meter-label-left">Horas de Uso</span>
            <span class="meter-label-right">${fmt(hours)} h</span>
          </div>
          <div class="meter-bar">
            <div class="meter-fill meter-fill-${riskStatus}" 
                 style="width: ${usagePercent}%"></div>
          </div>
        </div>

        <div class="status-badge ${riskStatus}">
          ${riskStatus === 'critical' ? '🔴' : riskStatus === 'warning' ? '🟡' : '🟢'} 
          ${riskStatus}
        </div>
      </div>
    `;
  }).join('');
}

async function openTractorDetail(machineId) {
  selectedMachine = analysis.fleet.find(f => f.machine.id === machineId);
  if (!selectedMachine) return;

  const machine = selectedMachine.machine;
  const hours = machine.hours;
  const maxHours = 5400;
  const usagePercent = Math.min(100, (hours / maxHours) * 100);
  const riskStatus = getRiskStatus(selectedMachine.riskScore);
  
  // Llenar header
  $('detailEyebrow').textContent = machine.model;
  $('detailTitle').textContent = machine.id;
  $('detailSubtitle').textContent = `${machine.customer} • ${machine.dealer_region}`;

  // Llenar barra de horas
  $('horasBar').style.width = usagePercent + '%';
  $('horasText').textContent = `${fmt(hours)} horas (${usagePercent.toFixed(0)}% del desgaste esperado)`;

  // Llenar risk circle
  const riskCircle = $('riskCircle');
  riskCircle.className = `risk-circle ${riskStatus}`;
  $('riskValue').textContent = selectedMachine.riskScore;

  // Llenar top 3 piezas
  const topAlertsForParts = selectedMachine.alerts
    .slice(0, 3);
  
  if (topAlertsForParts.length === 0) {
    $('topParts').innerHTML = '<p class="muted">✅ Toda la maquinaria en buen estado</p>';
  } else {
    $('topParts').innerHTML = topAlertsForParts.map((alert, idx) => {
      const hoursLeft = alert.hoursToThreshold || (Math.random() * 48 + 12);
      const progressPercent = Math.min(100, 100 - ((hoursLeft / 72) * 100));
      
      return `
        <div class="part-item">
          <div class="part-name">${['⚠️', '🔴', '🟠'][idx]} ${alert.recommendedPart}</div>
          <div class="part-sku">SKU: ${alert.sku}</div>
          
          <div class="part-time-row">
            <span class="part-time-label">Tiempo Restante</span>
            <span class="part-time-value">${hoursLeft.toFixed(0)} hrs</span>
          </div>
          
          <div class="part-progress">
            <div class="part-progress-bar" style="width: ${progressPercent}%"></div>
          </div>
          
          <p style="margin: 0.8rem 0 0; font-size: 0.85rem; color: var(--muted);">
            ${alert.title}: ${alert.detail}
          </p>
          
          <button onclick='prepareSinglePart(${JSON.stringify(alert)})' 
                  style="width: 100%; margin-top: 0.8rem; background: var(--jd-green); color: white; border: none;">
            Preparar Pieza
          </button>
        </div>
      `;
    }).join('');
  }

  $('tractorDetail').showModal();
}

function closeTractorDetail() {
  $('tractorDetail').close();
  selectedMachine = null;
}

async function prepareSinglePart(alert) {
  const res = await fetch('/api/prepare-part', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      machineId: alert.machineId,
      sku: alert.sku,
      part: alert.recommendedPart,
      reason: alert.title
    })
  });
  const data = await res.json();
  $('dialogMessage').textContent = data.message || data.error;
  $('partDialog').showModal();
}

document.getElementById('prepareAllBtn')?.addEventListener('click', async () => {
  if (!selectedMachine) return;
  
  const alerts = selectedMachine.alerts.slice(0, 3);
  for (const alert of alerts) {
    await prepareSinglePart(alert);
  }
  
  loadAnalysis();
  closeTractorDetail();
});

$('refreshBtn').addEventListener('click', loadAnalysis);

loadAnalysis().catch(err => {
  document.body.innerHTML = `<main><section class="card"><h1>Error al cargar</h1><p>${err.message}</p></section></main>`;
});
