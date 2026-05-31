let analysis = null;
let selectedMachine = null;

const $ = (id) => document.getElementById(id);
const fmt = (n) => new Intl.NumberFormat().format(n);
const vehicleImages = ['media/vehiculo1.png', 'media/vehiculo2.png', 'media/vehiculo3.png'];

function getVehicleImage(index) {
  return vehicleImages[index % vehicleImages.length];
}

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
  grid.innerHTML = analysis.fleet.map((f, index) => {
    const vehicleImage = getVehicleImage(index);
    f.vehicleImage = vehicleImage;
    const hours = f.machine.hours;
    const maxHours = 5400;
    const usagePercent = Math.min(100, (hours / maxHours) * 100);
    const colorVar = getColorForUsage(hours);
    const riskStatus = getRiskStatus(f.riskScore);
    
    return `
      <div class="tractor-card" onclick="openTractorDetail('${f.machine.id}')">
        <div class="tractor-icon-box">
          <img src="${vehicleImage}" alt="${f.machine.model}" class="tractor-preview" />
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
  const detailImage = $('tractorImage');
  if (detailImage) {
    detailImage.src = selectedMachine.vehicleImage || getVehicleImage(0);
    detailImage.alt = machine.model;
  }

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

// CHATBOT FUNCTIONS
function openChatbot() {
  $('chatbotDialog').showModal();
  $('chatInput').focus();
}

function closeChatbot() {
  $('chatbotDialog').close();
}

function addChatMessage(text, isUser = true) {
  const messagesDiv = $('chatMessages');
  const messageEl = document.createElement('div');
  messageEl.className = `chat-message ${isUser ? 'user' : 'bot'}`;
  messageEl.innerHTML = `<div class="message-bubble ${isUser ? 'user' : 'bot'}">${text}</div>`;
  messagesDiv.appendChild(messageEl);
  messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

function getChatbotResponse(query) {
  if (!analysis) return "Cargando datos...";
  
  const queryLower = query.toLowerCase();
  const fleet = analysis.fleet;
  const allAlerts = analysis.alerts;
  
  // Respuestas según palabras clave
  if (queryLower.includes('hola') || queryLower.includes('hola')) {
    return "¡Hola! Soy tu asistente de mantenimiento predictivo 🤖. Puedo ayudarte con:\n- Estado de máquinas\n- Alertas activas\n- Máquinas con problemas\n- Piezas próximas a cambiar";
  }
  
  if (queryLower.includes('cuántas máquinas') || queryLower.includes('cuantas maquinas') || queryLower.includes('total de máquinas')) {
    return `Tienes ${fleet.length} máquinas en la flota. ${fleet.filter(f => f.status === 'critical').length} en estado crítico, ${fleet.filter(f => f.status === 'warning').length} con advertencias.`;
  }
  
  if (queryLower.includes('crítica') || queryLower.includes('critical') || queryLower.includes('problema')) {
    const critical = fleet.filter(f => f.status === 'critical');
    if (critical.length === 0) return "¡Excelente! No hay máquinas en estado crítico.";
    return `${critical.length} máquina(s) en estado crítico:\n${critical.map(f => `• ${f.machine.id} (${f.machine.customer})`).join('\n')}`;
  }
  
  if (queryLower.includes('alertas') || queryLower.includes('alertas activas')) {
    const criticalAlerts = allAlerts.filter(a => a.severity === 'critical');
    const warningAlerts = allAlerts.filter(a => a.severity === 'warning');
    return `Alertas activas:\n• Críticas: ${criticalAlerts.length}\n• Advertencias: ${warningAlerts.length}\n• Total: ${allAlerts.length}`;
  }
  
  if (queryLower.includes('piezas') || queryLower.includes('mantenimiento') || queryLower.includes('cambio')) {
    const topAlerts = allAlerts.slice(0, 3);
    if (topAlerts.length === 0) return "Todas las máquinas están en buen estado.";
    return `Próximas piezas a cambiar:\n${topAlerts.map(a => `• ${a.recommendedPart} (${a.machineId})`).join('\n')}`;
  }
  
  if (queryLower.includes('horas') || queryLower.includes('uso')) {
    const totalHours = fleet.reduce((sum, f) => sum + f.machine.hours, 0);
    const avgHours = Math.round(totalHours / fleet.length);
    return `Horas de uso:\n• Total: ${fmt(totalHours)}h\n• Promedio: ${fmt(avgHours)}h\n• Máxima: ${fmt(Math.max(...fleet.map(f => f.machine.hours)))}h`;
  }
  
  if (queryLower.includes('máquina') || queryLower.includes('maquina') || queryLower.includes('vehicle')) {
    const machineMatch = fleet.find(f => f.machine.id.toLowerCase().includes(queryLower.replace(/máquina|maquina|machine|vehicle/gi, '').trim()) || f.machine.customer.toLowerCase().includes(queryLower));
    if (machineMatch) {
      return `${machineMatch.machine.id} (${machineMatch.machine.customer}):\n• Modelo: ${machineMatch.machine.model}\n• Horas: ${fmt(machineMatch.machine.hours)}\n• Estado: ${machineMatch.status}\n• Riesgo: ${machineMatch.riskScore}/100`;
    }
  }
  
  if (queryLower.includes('riesgo') || queryLower.includes('risk')) {
    const highRisk = fleet.filter(f => f.riskScore >= 60).sort((a, b) => b.riskScore - a.riskScore);
    if (highRisk.length === 0) return "Todas las máquinas tienen riesgo bajo.";
    return `Máquinas con mayor riesgo:\n${highRisk.slice(0, 3).map(f => `• ${f.machine.customer}: ${f.riskScore}/100`).join('\n')}`;
  }
  
  if (queryLower.includes('sano') || queryLower.includes('bien') || queryLower.includes('saludables')) {
    const healthy = fleet.filter(f => f.status === 'healthy');
    return `${healthy.length} máquina(s) en buen estado: ${healthy.map(f => f.machine.customer).join(', ')}`;
  }
  
  return "No entiendo bien tu pregunta. Prueba preguntar sobre:\n• Estado de máquinas\n• Alertas activas\n• Piezas a cambiar\n• Horas de uso\n• Máquinas con riesgo";
}

function sendChatMessage() {
  const input = $('chatInput');
  const message = input.value.trim();
  if (!message) return;
  
  addChatMessage(message, true);
  input.value = '';
  
  setTimeout(() => {
    const response = getChatbotResponse(message);
    addChatMessage(response, false);
  }, 500);
}

// Allow Enter key to send message
$('chatInput')?.addEventListener('keypress', (e) => {
  if (e.key === 'Enter') sendChatMessage();
});
