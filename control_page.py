<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Turret - 2 DOF Control</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 18px; }
    button { margin:6px; padding:8px 12px; }
    .box { border:1px solid #ddd; padding:12px; margin-bottom:12px; border-radius:6px; max-width:420px; }
    pre { background:#f7f7f7; padding:10px; border-radius:4px; }
  </style>
</head>
<body>
  <h2>Turret Control (2 DOF)</h2>

  <div class="box">
    <h3>Azimuth (rotate around)</h3>
    <div>
      <button onclick="move('az', -5)">◀ -5°</button>
      <button onclick="move('az', -1)">◀ -1°</button>
      <button onclick="move('az', 1)">+1° ▶</button>
      <button onclick="move('az', 5)">+5° ▶</button>
      <button onclick="setZero('az')">Set Az Zero</button>
    </div>
  </div>

  <div class="box">
    <h3>Elevation (tilt)</h3>
    <div>
      <button onclick="move('el', -5)">▼ -5°</button>
      <button onclick="move('el', -1)">▼ -1°</button>
      <button onclick="move('el', 1)">▲ +1°</button>
      <button onclick="move('el', 5)">▲ +5°</button>
      <button onclick="setZero('el')">Set El Zero</button>
    </div>
  </div>

  <div class="box">
    <h3>Current Angles</h3>
    <pre id="angles">Loading...</pre>
    <button onclick="refreshAngles()">Refresh now</button>
  </div>

  <div class="box">
    <h3>Field Diagram (optional)</h3>
    <img src="/static/field_diagram" alt="field" style="max-width:100%;">
  </div>

<script>
function api(path, method='GET', body=null){
  const opts = { method, headers: {} };
  if(body){
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  return fetch(path, opts).then(r => r.json());
}

function move(axis, delta){
  api('/api/move', 'POST', {axis:axis, delta: delta})
    .then(j => {
      if(!j.ok) alert('Error: ' + (j.error || 'unknown'));
    });
}

function setZero(axis){
  api('/api/set_zero', 'POST', {axis:axis})
    .then(j => {
      if(j.ok) alert(axis + ' zero set');
    });
}

function refreshAngles(){
  api('/api/angles').then(j => {
    if(j.ok){
      document.getElementById('angles').textContent = 
        'Azimuth: ' + j.az.toFixed(2) + '°\\nElevation: ' + j.el.toFixed(2) + '°';
    } else {
      document.getElementById('angles').textContent = 'Error fetching angles';
    }
  });
}

// poll angles every 800 ms
setInterval(refreshAngles, 800);
refreshAngles();
</script>
</body>
</html>
