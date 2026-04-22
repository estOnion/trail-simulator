// Trail Simulator front-end. Pure JS, no build step.
(() => {
  // Taipei City Hall area — central enough to see Xinyi, Daan, Zhongshan.
  const TAIPEI = [25.0375, 121.5637];

  const map = L.map('map').setView(TAIPEI, 14);
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '© OpenStreetMap',
  }).addTo(map);

  // Picking mode: 'origin' | 'dest' | null
  let pickMode = 'origin';
  let originMarker = null;
  // Ordered destination queue — each entry { marker, latlng }.
  const destinations = [];
  let currentMarker = null;
  let breadcrumb = null;
  const breadcrumbPoints = [];

  const el = (id) => document.getElementById(id);
  const fmt = (ll) => `${ll.lat.toFixed(5)}, ${ll.lng.toFixed(5)}`;

  function destPayload() {
    return destinations.map((d) => ({ lat: d.latlng.lat, lon: d.latlng.lng }));
  }

  function renderDestList() {
    const list = el('dest-list');
    list.innerHTML = '';
    if (destinations.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'empty';
      empty.textContent = 'click the map to add destinations';
      list.appendChild(empty);
      return;
    }
    destinations.forEach((d, i) => {
      const row = document.createElement('div');
      row.className = 'dest-row';
      const num = document.createElement('span');
      num.className = 'num';
      num.textContent = `#${i + 1}`;
      const coord = document.createElement('span');
      coord.className = 'coord';
      coord.textContent = fmt(d.latlng);
      const x = document.createElement('button');
      x.type = 'button';
      x.className = 'x';
      x.textContent = '×';
      x.title = 'remove destination';
      x.onclick = () => removeDest(i);
      row.append(num, coord, x);
      list.appendChild(row);
    });
  }

  function renumberDestMarkers() {
    destinations.forEach((d, i) => {
      const label = `#${i + 1}`;
      if (d.marker.getTooltip()) d.marker.unbindTooltip();
      d.marker.bindTooltip(label, { permanent: true, direction: 'top' });
    });
  }

  function updateLabels() {
    el('origin-label').textContent = originMarker ? fmt(originMarker.getLatLng()) : 'click the map';
    renderDestList();
    el('walk').disabled = !(originMarker && destinations.length > 0) || isActive();
  }

  function setPickMode(mode) {
    pickMode = mode;
    el('pick-origin').classList.toggle('active', mode === 'origin');
    el('pick-dest').classList.toggle('active', mode === 'dest');
    document.body.classList.toggle('picking', mode !== null);
  }

  function placeOrigin(latlng) {
    if (originMarker) {
      originMarker.setLatLng(latlng);
    } else {
      originMarker = L.marker(latlng, {
        draggable: true,
        title: 'origin',
      })
        .addTo(map)
        .bindTooltip('origin', { permanent: true, direction: 'top' });
      originMarker.on('drag dragend', updateLabels);
    }
    updateLabels();
  }

  function addDest(latlng) {
    const marker = L.marker(latlng, { draggable: true }).addTo(map);
    const entry = { marker, latlng };
    destinations.push(entry);
    renumberDestMarkers();

    marker.on('drag', () => {
      entry.latlng = marker.getLatLng();
      updateLabels();
    });
    marker.on('dragend', () => {
      entry.latlng = marker.getLatLng();
      onDestChanged();
    });
    updateLabels();
  }

  function removeDest(i) {
    const [removed] = destinations.splice(i, 1);
    if (removed) map.removeLayer(removed.marker);
    renumberDestMarkers();
    updateLabels();
    onDestChanged();
  }

  async function onDestChanged() {
    if (!isActive()) return;
    if (destinations.length === 0) return;
    el('error').textContent = '';
    const r = await fetch('/api/retarget', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        destinations: destPayload(),
        loop: el('loop-toggle').checked,
      }),
    });
    if (!r.ok) {
      const j = await r.json().catch(() => ({}));
      el('error').textContent = typeof j.detail === 'string'
        ? j.detail : `retarget error: ${r.status}`;
    }
  }

  function clearCurrent() {
    if (currentMarker) { map.removeLayer(currentMarker); currentMarker = null; }
    if (breadcrumb) { map.removeLayer(breadcrumb); breadcrumb = null; }
    breadcrumbPoints.length = 0;
  }

  function isActive() {
    const s = el('state').textContent;
    return s === 'running' || s === 'starting' || s === 'paused';
  }

  map.on('click', (e) => {
    if (pickMode === 'origin') {
      if (isActive()) return; // no origin re-pick mid-session
      placeOrigin(e.latlng);
      // auto-advance to destination picking if none placed yet
      setPickMode(destinations.length === 0 ? 'dest' : null);
    } else if (pickMode === 'dest') {
      addDest(e.latlng);
      if (isActive()) onDestChanged();
      // keep pick-dest mode active so user can append more
    }
  });

  el('pick-origin').onclick = () => setPickMode(pickMode === 'origin' ? null : 'origin');
  el('pick-dest').onclick   = () => setPickMode(pickMode === 'dest'   ? null : 'dest');

  el('reset-pins').onclick = () => {
    if (originMarker) { map.removeLayer(originMarker); originMarker = null; }
    destinations.forEach((d) => map.removeLayer(d.marker));
    destinations.length = 0;
    clearCurrent();
    setPickMode('origin');
    updateLabels();
  };

  const speedSlider = el('speed');
  speedSlider.oninput = () => {
    el('speed-val').textContent = Number(speedSlider.value).toFixed(1);
  };
  speedSlider.onchange = async () => {
    if (!isActive()) return;
    el('error').textContent = '';
    const r = await fetch('/api/speed', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ speed_kmh: Number(speedSlider.value) }),
    });
    if (!r.ok) {
      const j = await r.json().catch(() => ({}));
      el('error').textContent = typeof j.detail === 'string'
        ? j.detail : `speed error: ${r.status}`;
    }
  };

  el('loop-toggle').onchange = () => {
    // Push loop flag server-side via retarget if active.
    if (isActive()) onDestChanged();
  };

  async function postSession(body) {
    return fetch('/api/session', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  }

  el('walk').onclick = async () => {
    el('error').textContent = '';
    clearCurrent();
    const body = {
      start_lat: originMarker.getLatLng().lat,
      start_lon: originMarker.getLatLng().lng,
      destinations: destPayload(),
      speed_kmh: Number(speedSlider.value),
      loop: el('loop-toggle').checked,
    };
    let r = await postSession(body);
    if (!r.ok) {
      const j = await r.json().catch(() => ({}));
      const detail = j.detail;
      if (detail && typeof detail === 'object' && detail.cooldown) {
        const msg = `Cooldown would block this jump.\n\n${detail.reason}\n\nSkip cooldown and start anyway?`;
        if (window.confirm(msg)) {
          r = await postSession({ ...body, skip_cooldown: true });
          if (!r.ok) {
            const j2 = await r.json().catch(() => ({}));
            const d2 = j2.detail;
            el('error').textContent = typeof d2 === 'string' ? d2 : `error: ${r.status}`;
          }
        } else {
          el('error').textContent = detail.reason;
        }
      } else {
        el('error').textContent = typeof detail === 'string' ? detail : `error: ${r.status}`;
      }
      return;
    }
  };

  el('pause').onclick  = () => fetch('/api/pause',  { method: 'POST' });
  el('resume').onclick = () => fetch('/api/resume', { method: 'POST' });
  el('stop').onclick   = () => fetch('/api/stop',   { method: 'POST' });

  function setMarkerInteractivity(active) {
    // Lock only the origin during an active session — destination markers
    // stay draggable so the queue can be edited live.
    if (originMarker) {
      if (active) originMarker.dragging.disable();
      else        originMarker.dragging.enable();
    }
    destinations.forEach((d) => {
      if (!d.marker.dragging.enabled()) d.marker.dragging.enable();
    });
  }

  function renderSnapshot(s) {
    el('state').textContent = s.state;
    el('progress').textContent = `${Math.round(s.progress_m)} / ${Math.round(s.total_m)} m`;
    el('cooldown').textContent = s.cooldown_remaining_s > 0
      ? `${Math.ceil(s.cooldown_remaining_s)}s` : '—';
    el('error').textContent = s.last_error || '';

    const running = s.state === 'running';
    const paused  = s.state === 'paused';
    const active  = running || paused || s.state === 'starting';
    el('walk').disabled   = active || !(originMarker && destinations.length > 0);
    el('pause').disabled  = !running;
    el('resume').disabled = !paused;
    el('stop').disabled   = !active && s.state !== 'error';

    setMarkerInteractivity(active);

    if (s.current_lat != null && s.current_lon != null) {
      const ll = [s.current_lat, s.current_lon];
      if (!currentMarker) {
        currentMarker = L.circleMarker(ll, {
          radius: 7, color: '#0a7', fillColor: '#0a7', fillOpacity: 0.85,
        }).addTo(map).bindTooltip('current');
      } else {
        currentMarker.setLatLng(ll);
      }
      breadcrumbPoints.push(ll);
      if (!breadcrumb) {
        breadcrumb = L.polyline(breadcrumbPoints, { color: '#0a7', weight: 3, opacity: 0.6 }).addTo(map);
      } else {
        breadcrumb.setLatLngs(breadcrumbPoints);
      }
    }
  }

  function openWs() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const ws = new WebSocket(`${proto}://${location.host}/ws/live`);
    ws.onmessage = (ev) => { try { renderSnapshot(JSON.parse(ev.data)); } catch {} };
    ws.onclose = () => setTimeout(openWs, 1500);
  }
  openWs();

  setPickMode('origin');
  updateLabels();
})();
