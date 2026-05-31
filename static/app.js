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
const chatHistory = []; // [{role: 'user'|'assistant', content: string}]

function openChatbot() {
  $('chatbotDialog').showModal();
  if ($('chatMessages').children.length === 0) {
    addChatMessage('¡Hola! Soy <strong>DeereMagic Assistant</strong> 🤖<br>Puedo ayudarte con el estado de tu flota, alertas, piezas próximas a cambiar y más. ¿En qué te ayudo?', false);
  }
  $('chatInput').focus();
}

function closeChatbot() {
  $('chatbotDialog').close();
}

function addChatMessage(html, isUser = true) {
  const messagesDiv = $('chatMessages');
  const messageEl = document.createElement('div');
  messageEl.className = `chat-message ${isUser ? 'user' : 'bot'}`;
  messageEl.innerHTML = `<div class="message-bubble ${isUser ? 'user' : 'bot'}">${html}</div>`;
  messagesDiv.appendChild(messageEl);
  messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

function addTypingIndicator() {
  const messagesDiv = $('chatMessages');
  const el = document.createElement('div');
  el.className = 'chat-message bot';
  el.id = 'typingIndicator';
  el.innerHTML = '<div class="message-bubble bot typing-indicator"><span></span><span></span><span></span></div>';
  messagesDiv.appendChild(el);
  messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

function removeTypingIndicator() {
  const el = $('typingIndicator');
  if (el) el.remove();
}

async function sendChatMessage() {
  const input = $('chatInput');
  const message = input.value.trim();
  if (!message) return;

  const sendBtn = document.querySelector('.chat-send-btn');
  input.disabled = true;
  sendBtn.disabled = true;

  addChatMessage(message, true);
  chatHistory.push({ role: 'user', content: message });
  input.value = '';

  addTypingIndicator();

  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, history: chatHistory.slice(0, -1) }),
    });
    const data = await res.json();
    removeTypingIndicator();

    if (data.error) {
      addChatMessage(`⚠️ Error: ${data.error}`, false);
    } else {
      // Render line breaks and keep markdown-like newlines
      const htmlReply = data.reply
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\n/g, '<br>');
      addChatMessage(htmlReply, false);
      chatHistory.push({ role: 'assistant', content: data.reply });
    }
  } catch (err) {
    removeTypingIndicator();
    addChatMessage('⚠️ No se pudo conectar con el asistente. Verifica que el servidor esté corriendo con <code>ANTHROPIC_API_KEY</code> configurada.', false);
  }

  input.disabled = false;
  sendBtn.disabled = false;
  input.focus();
}

// Allow Enter key to send message
$('chatInput')?.addEventListener('keypress', (e) => {
  if (e.key === 'Enter') sendChatMessage();
});