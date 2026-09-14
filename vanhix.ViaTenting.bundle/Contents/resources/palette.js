(function () {
  'use strict';

  var maskMode = 'off';
  var vias = [];
  var groups = [];
  var selectedGroupIds = {};
  var visibleLayers = [];

  function send(action, data) {
    if (window.adsk && adsk.fusionSendData) {
      adsk.fusionSendData(action, data || '');
    }
  }

  function setStatus(text, kind) {
    var box = document.getElementById('status');
    if (!text) {
      box.textContent = '';
      box.className = 'status hidden';
      box.hidden = true;
      return;
    }
    box.textContent = text;
    box.className = 'status' + (kind ? ' ' + kind : '');
    box.hidden = false;
  }

  var isBusy = false;

  function setBusy(kind) {
    var refreshBtn = document.getElementById('refreshBtn');
    var applyBtn = document.getElementById('applyBtn');
    var busy = !!kind;
    isBusy = busy;
    refreshBtn.disabled = busy;
    applyBtn.disabled = busy;
    document.getElementById('groupMode').disabled = busy;
    if (kind === 'scan') {
      refreshBtn.textContent = 'Scanning…';
    } else if (kind === 'apply') {
      applyBtn.textContent = 'Applying…';
    } else {
      refreshBtn.textContent = 'Refresh';
      applyBtn.textContent = 'Apply to selected';
    }
  }

  function formatDrill(value) {
    var num = Number(value);
    if (!isFinite(num)) return '—';
    return num.toFixed(3) + ' mm';
  }

  function maskLabel(value) {
    var text = String(value || 'auto').toLowerCase();
    if (text === 'off') return 'Off';
    if (text === 'offset') return 'Offset';
    if (text === 'on') return 'Auto';
    return 'Auto';
  }

  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function dominantMask(maskCounts) {
    var best = 'auto';
    var bestCount = -1;
    Object.keys(maskCounts).forEach(function (key) {
      if (maskCounts[key] > bestCount) {
        bestCount = maskCounts[key];
        best = key;
      }
    });
    if (Object.keys(maskCounts).length > 1) {
      return best + '+';
    }
    return best;
  }

  function groupKey(via, mode) {
    var net = via.net || '(no net)';
    var drill = Number(via.drill).toFixed(3);
    if (mode === 'net') return 'net:' + net;
    if (mode === 'drill') return 'drill:' + drill;
    return 'net_drill:' + net + '|' + drill;
  }

  function buildGroups(items, mode) {
    var map = {};
    items.forEach(function (via) {
      var key = groupKey(via, mode);
      if (!map[key]) {
        map[key] = {
          id: key,
          net: via.net || '(no net)',
          drill: Number(via.drill),
          drillLabel: formatDrill(via.drill),
          vias: [],
          maskCounts: { auto: 0, off: 0, offset: 0 }
        };
      }
      map[key].vias.push(via);
      var mask = String(via.mask || 'auto').toLowerCase();
      if (map[key].maskCounts[mask] === undefined) {
        map[key].maskCounts[mask] = 0;
      }
      map[key].maskCounts[mask] += 1;
    });

    return Object.keys(map).sort(function (a, b) {
      var ga = map[a];
      var gb = map[b];
      if (mode === 'drill') {
        return ga.drill - gb.drill || ga.net.localeCompare(gb.net);
      }
      if (mode === 'net') {
        return ga.net.localeCompare(gb.net) || ga.drill - gb.drill;
      }
      return ga.net.localeCompare(gb.net) || ga.drill - gb.drill;
    }).map(function (key) {
      var group = map[key];
      group.count = group.vias.length;
      group.mask = dominantMask(group.maskCounts);
      if (mode === 'net' && group.vias.length > 0) {
        var drills = {};
        group.vias.forEach(function (v) {
          drills[Number(v.drill).toFixed(3)] = true;
        });
        var uniqueDrills = Object.keys(drills);
        group.drillLabel = uniqueDrills.length === 1
          ? formatDrill(group.drill)
          : uniqueDrills.length + ' sizes';
      }
      if (mode === 'drill') {
        var nets = {};
        group.vias.forEach(function (v) {
          nets[v.net || '(no net)'] = true;
        });
        var netNames = Object.keys(nets).sort();
        group.net = netNames.length === 1 ? netNames[0] : netNames.length + ' nets';
        group.drillLabel = formatDrill(group.drill);
      }
      return group;
    });
  }

  function selectedViaCount() {
    var total = 0;
    groups.forEach(function (group) {
      if (selectedGroupIds[group.id]) {
        total += group.count;
      }
    });
    return total;
  }

  function selectedViasPayload() {
    var payload = [];
    groups.forEach(function (group) {
      if (!selectedGroupIds[group.id]) return;
      group.vias.forEach(function (via) {
        payload.push({ x: via.x, y: via.y });
      });
    });
    return payload;
  }

  function syncSelectAllCheckbox() {
    var selectAll = document.getElementById('selectAll');
    if (!groups.length) {
      selectAll.checked = false;
      selectAll.indeterminate = false;
      return;
    }
    var selectedCount = groups.filter(function (g) { return selectedGroupIds[g.id]; }).length;
    selectAll.checked = selectedCount === groups.length;
    selectAll.indeterminate = selectedCount > 0 && selectedCount < groups.length;
  }

  function renderTable() {
    var body = document.getElementById('viaTableBody');
    body.innerHTML = '';

    if (!groups.length) {
      var empty = document.createElement('tr');
      empty.className = 'empty-row';
      var emptyCell = document.createElement('td');
      emptyCell.colSpan = 5;
      emptyCell.textContent = vias.length ? 'No groups match the current view' : 'No vias found on this board';
      empty.appendChild(emptyCell);
      body.appendChild(empty);
      syncSelectAllCheckbox();
      return;
    }

    groups.forEach(function (group) {
      var row = document.createElement('tr');
      if (selectedGroupIds[group.id]) {
        row.className = 'row-selected';
      }

      var maskClass = String(group.mask).replace('+', '');
      var maskText = maskLabel(maskClass);
      if (String(group.mask).indexOf('+') >= 0) {
        maskText += ' +';
      }

      row.innerHTML =
        '<td class="col-check"><input type="checkbox" class="row-check" data-id="' + escapeHtml(group.id) + '"' +
          (selectedGroupIds[group.id] ? ' checked' : '') + ' aria-label="Select group"></td>' +
        '<td>' + escapeHtml(group.drillLabel) + '</td>' +
        '<td title="' + escapeHtml(group.net) + '">' + escapeHtml(group.net) + '</td>' +
        '<td class="col-qty">' + group.count + '</td>' +
        '<td><span class="mask-pill mask-' + escapeHtml(maskClass) + '">' + maskText + '</span></td>';

      body.appendChild(row);
    });

    body.querySelectorAll('.row-check').forEach(function (checkbox) {
      checkbox.addEventListener('change', function (e) {
        var id = e.target.getAttribute('data-id');
        if (e.target.checked) {
          selectedGroupIds[id] = true;
        } else {
          delete selectedGroupIds[id];
        }
        renderTable();
        updateSummary();
      });
    });

    syncSelectAllCheckbox();
  }

  function updateSummary() {
    var hint = document.getElementById('viaCountHint');
    if (!vias.length) {
      hint.textContent = 'No vias found on the open board';
      return;
    }

    var counts = { auto: 0, off: 0, offset: 0 };
    vias.forEach(function (via) {
      var key = String(via.mask || 'auto').toLowerCase();
      if (key === 'on') key = 'auto';
      if (counts[key] !== undefined) counts[key] += 1;
      else counts.auto += 1;
    });

    var selectedGroups = groups.filter(function (g) { return selectedGroupIds[g.id]; }).length;
    var selectedVias = selectedViaCount();
    hint.textContent = vias.length + ' vias in ' + groups.length + ' groups · selected ' +
      selectedVias + ' (' + selectedGroups + ' groups) · Auto ' + counts.auto +
      ' · Off ' + counts.off + (counts.offset ? ' · Offset ' + counts.offset : '');
  }

  function rebuildGroups() {
    var mode = document.getElementById('groupMode').value;
    var previous = selectedGroupIds;
    groups = buildGroups(vias, mode);
    selectedGroupIds = {};
    groups.forEach(function (group) {
      if (previous[group.id]) {
        selectedGroupIds[group.id] = true;
      }
    });
    renderTable();
    updateSummary();
  }

  function applyPayload(data) {
    try {
      var parsed = typeof data === 'string' ? JSON.parse(data) : data;
      vias = parsed.vias || [];
      if (parsed.layers && parsed.layers.length) {
        visibleLayers = parsed.layers;
      }
      rebuildGroups();
    } catch (err) {
      setStatus('Could not read via scan results.', 'err');
    }
  }

  function setMaskMode(mode) {
    maskMode = mode;
    var btnAuto = document.getElementById('btnMaskAuto');
    var btnOff = document.getElementById('btnMaskOff');
    var btnOffset = document.getElementById('btnMaskOffset');
    if (btnAuto) btnAuto.className = mode === 'auto' ? 'active' : '';
    if (btnOff) btnOff.className = mode === 'off' ? 'active' : '';
    if (btnOffset) btnOffset.className = mode === 'offset' ? 'active' : '';
  }

  window.fusionJavaScriptHandler = {
    handle: function (action, data) {
      if (action === 'busy') {
        setBusy(data || '');
        return;
      }
      if (action === 'scanResult') {
        setBusy('');
        applyPayload(data);
        setStatus('Loaded ' + vias.length + ' via' + (vias.length === 1 ? '' : 's') + '.', 'ok');
        return;
      }
      if (action === 'applyDone') {
        setBusy('');
        try {
          var parsed = typeof data === 'string' ? JSON.parse(data) : data;
          applyPayload(data);
          var applied = parsed.appliedCount || 0;
          var appliedMode = parsed.maskMode || maskMode;
          var msg = 'Applied ' + maskLabel(appliedMode) + ' to ' + applied +
            ' via' + (applied === 1 ? '' : 's') + '.';
          if (parsed.maskLimitUpdated) {
            var targetMil = parsed.targetLimitMil !== undefined && parsed.targetLimitMil !== null
              ? parsed.targetLimitMil
              : 999;
            msg += ' Mask limit set to ' + targetMil + ' mil in Design Preferences.';
          }
          setStatus(msg, 'ok');
        } catch (err) {
          setStatus('Applied — click Refresh to update the list.', 'ok');
        }
        return;
      }
      if (action === 'error') {
        setBusy('');
        setStatus(data || 'Something went wrong.', 'err');
      }
    }
  };

  var btnAutoEl = document.getElementById('btnMaskAuto');
  var btnOffEl = document.getElementById('btnMaskOff');
  var btnOffsetEl = document.getElementById('btnMaskOffset');
  if (btnAutoEl) btnAutoEl.addEventListener('click', function () { setMaskMode('auto'); });
  if (btnOffEl) btnOffEl.addEventListener('click', function () { setMaskMode('off'); });
  if (btnOffsetEl) btnOffsetEl.addEventListener('click', function () { setMaskMode('offset'); });

  document.getElementById('groupMode').addEventListener('change', function () {
    rebuildGroups();
  });

  document.getElementById('selectAll').addEventListener('change', function (e) {
    if (e.target.checked) {
      groups.forEach(function (group) {
        selectedGroupIds[group.id] = true;
      });
    } else {
      selectedGroupIds = {};
    }
    renderTable();
    updateSummary();
  });

  document.getElementById('refreshBtn').addEventListener('click', function () {
    if (isBusy) return;
    setBusy('scan');
    setStatus('Scanning board vias…');
    send('scan');
  });

  document.getElementById('applyBtn').addEventListener('click', function () {
    if (isBusy) return;
    var selected = selectedViasPayload();
    if (!selected.length) {
      setStatus('Select at least one group (checkbox) before applying.', 'err');
      return;
    }
    setBusy('apply');
    setStatus('Applying solder mask to ' + selected.length + ' selected via' + (selected.length === 1 ? '' : 's') + '…');
    var isAll = (vias.length > 0 && selected.length === vias.length);
    send('apply', JSON.stringify({
      maskMode: maskMode,
      vias: selected,
      isAll: isAll,
      totalCount: vias.length,
      visibleLayers: visibleLayers
    }));
  });

  document.getElementById('closeBtn').addEventListener('click', function () {
    send('cancel');
  });

  setMaskMode('off');
})();
