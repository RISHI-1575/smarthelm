/* SmartHelm Dashboard — polling logic */

(function () {
  'use strict';

  const els = {
    alertBanner:   document.getElementById('alert-banner'),
    eyeBadge:      document.getElementById('eye-state-badge'),
    eyeOverlay:    document.getElementById('eye-state-overlay'),
    confidenceVal: document.getElementById('confidence-val'),
    earVal:        document.getElementById('ear-val'),
    perclosVal:    document.getElementById('perclos-val'),
    perclosBar:    document.getElementById('perclos-bar-fill'),
    closureVal:    document.getElementById('closure-val'),
    fpsDisplay:    document.getElementById('fps-display'),
    fpsVal:        document.getElementById('fps-val'),
    latencyVal:    document.getElementById('latency-val'),
    faceVal:       document.getElementById('face-val'),
    modeVal:       document.getElementById('mode-val'),
    modeBadge:     document.getElementById('detection-mode'),
    connectionDot: document.getElementById('connection-dot'),
    eventList:     document.getElementById('event-list'),
    eventCount:    document.getElementById('event-count'),
    hrVal:         document.getElementById('hr-val'),
    spo2Val:       document.getElementById('spo2-val'),
    fingerVal:     document.getElementById('finger-val'),
    buzzerStatus:  document.getElementById('buzzer-status'),
  };

  let connected = false;

  // ── Status polling — every 500ms ──────────────────────────────────
  function pollStatus() {
    fetch('/api/status')
      .then(r => { if (!r.ok) throw new Error(); return r.json(); })
      .then(data => { setConnected(true); updateStatus(data); })
      .catch(() => setConnected(false));
  }

  function updateStatus(d) {
    // Eye state
    const state = (d.eye_state || 'UNKNOWN').toLowerCase();
    setEyeState(state, d.eye_state, d.confidence, d.ear_smoothed);

    // PERCLOS
    const pc = parseFloat(d.perclos) || 0;
    els.perclosVal.textContent = pc.toFixed(1);
    els.perclosBar.style.width = Math.min(pc, 100) + '%';
    els.perclosBar.className = 'perclos-bar-fill' +
      (pc >= 30 ? ' danger' : pc >= 20 ? ' warning' : '');

    // Continuous closure
    els.closureVal.textContent = (parseFloat(d.continuous_closure_sec) || 0).toFixed(1);

    // Performance
    const fps = parseFloat(d.fps) || 0;
    els.fpsDisplay.textContent = fps.toFixed(1) + ' FPS';
    els.fpsVal.textContent     = fps.toFixed(1);
    els.latencyVal.textContent = (parseFloat(d.latency_ms) || 0).toFixed(0) + ' ms';
    els.faceVal.textContent    = d.face_detected ? 'Yes' : 'No';
    els.modeVal.textContent    = d.detection_mode || '--';
    if (els.modeBadge) els.modeBadge.textContent = d.detection_mode || '--';

    // Vital signs — MAX30102
    els.hrVal.textContent   = d.heart_rate  != null ? d.heart_rate  : '--';
    els.spo2Val.textContent = d.spo2        != null ? d.spo2        : '--';

    if (d.finger_detected) {
      els.fingerVal.textContent = 'Detected ✓';
      els.fingerVal.className   = 'finger-badge finger-on';
    } else {
      els.fingerVal.textContent = 'Not detected';
      els.fingerVal.className   = 'finger-badge finger-off';
    }

    // Alert banner
    setAlert(d.alert);
  }

  // ── Eye state helpers ─────────────────────────────────────────────
  function setEyeState(stateLower, stateLabel, confidence, ear) {
    els.eyeBadge.className   = 'badge ' + stateLower;
    els.eyeBadge.textContent = stateLabel || 'UNKNOWN';
    els.eyeOverlay.className   = 'eye-state-overlay ' + stateLower;
    els.eyeOverlay.textContent = stateLabel || 'UNKNOWN';
    els.confidenceVal.textContent = ((parseFloat(confidence) || 0) * 100).toFixed(0) + '%';
    els.earVal.textContent        = (parseFloat(ear) || 0).toFixed(3);
  }

  // ── Alert banner ──────────────────────────────────────────────────
  function setAlert(active) {
    els.alertBanner.classList.toggle('hidden', !active);
    document.body.classList.toggle('alert-active', !!active);
  }

  // ── Connection dot ────────────────────────────────────────────────
  function setConnected(ok) {
    if (ok === connected) return;
    connected = ok;
    els.connectionDot.className = 'dot ' + (ok ? 'dot-green' : 'dot-red');
    els.connectionDot.title     = ok ? 'Connected' : 'Disconnected';
  }

  // ── Event history polling — every 3s ──────────────────────────────
  function pollEvents() {
    fetch('/api/events')
      .then(r => r.json())
      .then(events => { if (Array.isArray(events)) renderEvents(events); })
      .catch(() => {});
  }

  function renderEvents(events) {
    if (events.length === 0) {
      els.eventList.innerHTML = '<tr><td colspan="4" class="no-events">No alerts yet</td></tr>';
      els.eventCount.textContent = '0 events';
      return;
    }
    const sorted = [...events].reverse();
    els.eventCount.textContent = sorted.length + ' event' + (sorted.length !== 1 ? 's' : '');
    els.eventList.innerHTML = sorted.map(e => {
      const t       = new Date(e.ts * 1000).toLocaleTimeString();
      const type    = (e.type || 'ALERT').toUpperCase();
      const typeClass = 'event-type-' + type.toLowerCase().replace('_', '-');
      return `<tr>
        <td>${t}</td>
        <td class="${typeClass}">${type}</td>
        <td>${(parseFloat(e.perclos) || 0).toFixed(1)}%</td>
        <td>${(parseFloat(e.continuous_sec) || 0).toFixed(1)}s</td>
      </tr>`;
    }).join('');
  }

  // ── Test buzzer ───────────────────────────────────────────────────
  window.testBuzzer = function () {
    els.buzzerStatus.textContent = 'Triggering...';
    fetch('/api/test_buzzer')
      .then(r => r.json())
      .then(d => {
        els.buzzerStatus.textContent = d.status === 'triggered'
          ? '✓ Buzzer triggered — did you hear it?'
          : '✗ ' + (d.status || 'error');
        setTimeout(() => { els.buzzerStatus.textContent = ''; }, 4000);
      })
      .catch(() => {
        els.buzzerStatus.textContent = '✗ Request failed';
        setTimeout(() => { els.buzzerStatus.textContent = ''; }, 4000);
      });
  };

  // ── Video feeds — load only when button clicked ───────────────────
  let feedsLoaded = false;

  function startSnapshots(imgId, endpoint, dotSelector, fps) {
    const img = document.getElementById(imgId);
    if (!img) return;
    const dot = document.querySelector(dotSelector);
    let t = Date.now();
    function next() { img.src = endpoint + '?t=' + (++t); }
    img.onload = function () { if (dot) dot.classList.add('active'); };
    next();
    setInterval(next, fps);
  }

  window.startCameras = function () {
    if (feedsLoaded) return;
    feedsLoaded = true;
    const btn = document.getElementById('start-cam-btn');
    if (btn) { btn.textContent = 'Cameras ON ✓'; btn.disabled = true; }
    startSnapshots('cam1-img', '/snapshot/cam1', '.cam-primary .cam-dot',    150); // ~7fps
    startSnapshots('cam2-img', '/snapshot/cam2', '.cam-secondary-group .cam-box:nth-child(1) .cam-dot', 200); // ~5fps
    startSnapshots('cam3-img', '/snapshot/cam3', '.cam-secondary-group .cam-box:nth-child(2) .cam-dot', 200);
  };

  // ── Start ─────────────────────────────────────────────────────────
  pollStatus();
  pollEvents();
  setInterval(pollStatus, 1000);
  setInterval(pollEvents, 5000);

})();
