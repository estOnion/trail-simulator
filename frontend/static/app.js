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
    return s === 'running' || s === 'starting' || s === 'paused' || s === 'reconnecting';
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

  // ---- POI search bar ------------------------------------------------------
  const searchInput = el('search-input');
  const searchResults = el('search-results');
  let searchDebounce = null;
  let searchAbort = null;

  function hideSearchResults() {
    searchResults.innerHTML = '';
    searchResults.classList.remove('open');
  }

  function renderSearchResults(results) {
    searchResults.innerHTML = '';
    if (!results || results.length === 0) {
      hideSearchResults();
      return;
    }
    results.forEach((res) => {
      const li = document.createElement('li');
      li.textContent = res.display_name;
      li.title = res.display_name;
      li.onclick = (ev) => { ev.stopPropagation(); pickSearchResult(res); };
      searchResults.appendChild(li);
    });
    searchResults.classList.add('open');
  }

  function pickSearchResult(res) {
    const latlng = L.latLng(res.lat, res.lon);
    if (pickMode === 'origin') {
      if (isActive()) {
        el('error').textContent = 'cannot re-pick origin during an active session';
        return;
      }
      placeOrigin(latlng);
      setPickMode(destinations.length === 0 ? 'dest' : null);
    } else {
      addDest(latlng);
      if (isActive()) onDestChanged();
    }
    map.setView(latlng, 16);
    searchInput.value = '';
    hideSearchResults();
  }

  async function runSearch(q) {
    if (searchAbort) searchAbort.abort();
    searchAbort = new AbortController();
    try {
      const r = await fetch(`/api/search?q=${encodeURIComponent(q)}`, {
        signal: searchAbort.signal,
      });
      if (!r.ok) {
        const j = await r.json().catch(() => ({}));
        el('error').textContent = typeof j.detail === 'string'
          ? j.detail : `search error: ${r.status}`;
        hideSearchResults();
        return;
      }
      const j = await r.json();
      renderSearchResults(j.results || []);
    } catch (e) {
      if (e.name === 'AbortError') return;
      el('error').textContent = `search error: ${e.message || e}`;
      hideSearchResults();
    }
  }

  searchInput.oninput = () => {
    const q = searchInput.value.trim();
    if (searchDebounce) clearTimeout(searchDebounce);
    if (q.length < 3) { hideSearchResults(); return; }
    searchDebounce = setTimeout(() => runSearch(q), 250);
  };

  searchInput.onkeydown = (e) => {
    if (e.key === 'Escape') { searchInput.value = ''; hideSearchResults(); }
  };

  document.addEventListener('click', (ev) => {
    if (!ev.target.closest('.search')) hideSearchResults();
  });

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

  // Layer 2: single-flight guard so rapid clicks during the in-flight
  // window (Walk → server ack → next WS broadcast) can't generate
  // racing /api/session requests. After the action finishes we
  // explicitly re-sync from /api/status — some error paths (e.g.
  // validation 409) don't trigger a broadcast and would otherwise
  // leave the buttons stuck disabled.
  let lifecycleBusy = false;
  async function runLifecycle(fn) {
    if (lifecycleBusy) return;
    lifecycleBusy = true;
    el('walk').disabled = true;
    el('stop').disabled = true;
    try { await fn(); }
    finally {
      lifecycleBusy = false;
      try {
        const r = await fetch('/api/status');
        if (r.ok) renderSnapshot(await r.json());
      } catch (_) { /* WS will eventually catch up */ }
    }
  }

  // Layer 3: poll /api/status until state matches or timeout — used for
  // 409 recovery (we triggered a stop, now wait for it to settle).
  async function waitForState(target, timeoutMs) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      try {
        const r = await fetch('/api/status');
        if (r.ok) {
          const s = await r.json();
          if (s.state === target) return true;
        }
      } catch (_) { /* keep polling */ }
      await new Promise((res) => setTimeout(res, 150));
    }
    return false;
  }

  async function attemptStart(body) {
    let r = await postSession(body);
    if (!r.ok) {
      const j = await r.json().catch(() => ({}));
      const detail = j.detail;

      // Layer 3: 409 = lifecycle race slipped past Layers 1+2 (e.g. server
      // restart, manual API caller). Force-stop, wait for idle, retry once.
      if (r.status === 409) {
        await fetch('/api/stop', { method: 'POST' });
        const settled = await waitForState('idle', 3000);
        if (settled) {
          r = await postSession(body);
          if (r.ok) return;
        }
        el('error').textContent =
          'Session was stuck. Tried to reset — please click Walk again.';
        return;
      }

      if (detail && typeof detail === 'object' && detail.cooldown) {
        const msg = `Cooldown would block this jump.\n\n${detail.reason}\n\nSkip cooldown and start anyway?`;
        if (window.confirm(msg)) {
          return attemptStart({ ...body, skip_cooldown: true });
        }
        el('error').textContent = detail.reason;
        return;
      }
      el('error').textContent = typeof detail === 'string'
        ? detail : `error: ${r.status}`;
    }
  }

  el('walk').onclick = () => runLifecycle(async () => {
    el('error').textContent = '';
    clearCurrent();
    const body = {
      start_lat: originMarker.getLatLng().lat,
      start_lon: originMarker.getLatLng().lng,
      destinations: destPayload(),
      speed_kmh: Number(speedSlider.value),
      loop: el('loop-toggle').checked,
    };
    await attemptStart(body);
  });

  el('pause').onclick  = () => fetch('/api/pause',  { method: 'POST' });
  el('resume').onclick = () => fetch('/api/resume', { method: 'POST' });
  el('stop').onclick   = () => runLifecycle(async () => {
    await fetch('/api/stop', { method: 'POST' });
  });

  el('reset-gps').onclick = () => runLifecycle(async () => {
    await fetch('/api/reset', { method: 'POST' });
  });

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
    el('state').className = s.state;
    el('progress').textContent = `${Math.round(s.progress_m)} / ${Math.round(s.total_m)} m`;
    const companions = s.step_companions || [];
    const container = el('step-companions');
    if (companions.length === 0) {
      container.innerHTML = '<span class="step-companion-row step-companion-none">no step companions connected</span>';
    } else {
      const now = Date.now();
      container.innerHTML = companions.map(c => {
        const hbMs = now - new Date(c.last_heartbeat_iso).getTime();
        const hbS = Math.round(hbMs / 1000);
        const ack = c.total_acked.toLocaleString();
        return `<span class="step-companion-row">${c.label} · ack ${ack} · hb ${hbS}s ago</span>`;
      }).join('');
    }
    el('cooldown').textContent = s.cooldown_remaining_s > 0
      ? `${Math.ceil(s.cooldown_remaining_s)}s` : '—';

    const deviceError = s.last_error && s.last_error.startsWith('device:');
    if (s.state === 'reconnecting') {
      el('error').textContent = 'Connection lost — reconnecting automatically…';
    } else if (s.state === 'error' && deviceError) {
      el('error').textContent = (s.last_error || '') +
        '\n\nEnsure \'sudo pymobiledevice3 remote tunneld\' is running, then click Walk to resume.';
    } else {
      el('error').textContent = s.last_error || '';
    }

    const running = s.state === 'running';
    const paused  = s.state === 'paused';
    const reconnecting = s.state === 'reconnecting';
    const active  = running || paused || s.state === 'starting' || reconnecting;
    el('walk').disabled   = active || !(originMarker && destinations.length > 0);
    el('pause').disabled  = !running;
    el('resume').disabled = !paused;
    el('stop').disabled   = !active && s.state !== 'error' && s.state !== 'reconnecting';
    // Reset is offered only when settled and the phone is still holding a
    // spoofed point (frozen). Once reset, current_lat goes null.
    el('reset-gps').disabled = !(s.state === 'idle' && s.current_lat != null);

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
      // Only grow the breadcrumb while a session is actually walking.
      // Snapshots during idle/stopping/error/reconnecting still carry the
      // iPhone's last-known position; pushing them would splice the old
      // route's tail onto the new route's head.
      const inSession = s.state === 'starting' || s.state === 'running' || s.state === 'paused';
      if (inSession) {
        breadcrumbPoints.push(ll);
        if (!breadcrumb) {
          breadcrumb = L.polyline(breadcrumbPoints, { color: '#0a7', weight: 3, opacity: 0.6 }).addTo(map);
        } else {
          breadcrumb.setLatLngs(breadcrumbPoints);
        }
      }
    } else if (currentMarker) {
      map.removeLayer(currentMarker);
      currentMarker = null;
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
