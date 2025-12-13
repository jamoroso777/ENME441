#!/usr/bin/env python3
"""
turret_server_calibration.py (with laser on GPIO17 active-HIGH)

- Relative manual control (±0.5°, ±1°, ±5°) via buttons
- Dropdown of targets (turret1.. turretN, globe1.. globeM)
- "Go" button moves to selected target (background thread)
- "Save Calibration" saves per-target az/el offsets to calibration.json (use current motor angles)
- "Reload Targets" reloads positions.json and recomputes raw angles
- Zero Motors button
- /angles endpoint to poll current motor angles
- Laser button fires laser for 3 seconds (GPIO17 active HIGH)
"""

import socket
import time
import json
import os
import math
import threading
import sys
import traceback
from urllib.parse import unquote_plus
import multiprocessing
import RPi.GPIO as GPIO

from shifter import Shifter
from stepper_class_shiftregister_multiprocessing import Stepper

# ------------------ Configuration ------------------
DATA_PIN  = 16
LATCH_PIN = 20
CLOCK_PIN = 21

USE_LOCAL_JSON = True
LOCAL_JSON_FILE = "positions.json"
JSON_URL = "http://192.168.1.254:8000/positions.json"

MY_TEAM = "3"

HOST = ""
PORT = 8080

ANGLE_TOLERANCE_DEG = 0.8
CALIB_FILE = "calibration.json"

# Laser
LASER_PIN = 17
LASER_ON_SECONDS = 3

# -------- Elevation behavior (NEW) --------
EL_INVERT = True        # +elevation = UP
EL_MIN_DEG = -10.0      # down limit
EL_MAX_DEG = 90.0       # up limit

# ------------------ Globals ------------------
s = None
m_az = None
m_el = None

positions = {}
my_turret = None
processed_targets = []
raw_target_angles = {}
calibration = {}

# ------------------ Helpers ------------------
def normalize_deg(angle):
    return (angle % 360.0 + 360.0) % 360.0

def apply_elevation_limits(el_deg):
    if EL_INVERT:
        el_deg = -el_deg
    return max(EL_MIN_DEG, min(EL_MAX_DEG, el_deg))

# ------------------ JSON loading ------------------
def load_positions():
    global positions
    try:
        if USE_LOCAL_JSON:
            with open(LOCAL_JSON_FILE, 'r') as f:
                positions = json.load(f)
        else:
            import urllib.request
            with urllib.request.urlopen(JSON_URL, timeout=6) as resp:
                positions = json.loads(resp.read().decode())
        return True
    except Exception as e:
        print("Error loading positions:", e)
        positions = {}
        return False

def polar_to_cartesian_cm(r, theta, z=0):
    return (
        r * math.cos(theta),
        r * math.sin(theta),
        z
    )

def compute_az_el(tur_r, tur_theta, tgt_r, tgt_theta, tgt_z):
    tx, ty, _ = polar_to_cartesian_cm(tur_r, tur_theta, 0)
    px, py, pz = polar_to_cartesian_cm(tgt_r, tgt_theta, tgt_z)

    dx = px - tx
    dy = py - ty
    dz = pz

    az = normalize_deg(math.degrees(math.atan2(dy, dx)))
    el = math.degrees(math.atan2(dz, math.hypot(dx, dy)))
    dist = math.sqrt(dx*dx + dy*dy + dz*dz)
    return az, el, dist

def build_processed_targets():
    global processed_targets, raw_target_angles, my_turret
    processed_targets = []
    raw_target_angles = {}

    turrets = positions.get("turrets", {})
    globes = positions.get("globes", [])

    my_turret = turrets.get(MY_TEAM)
    if not my_turret:
        return False

    for k, v in turrets.items():
        if k == MY_TEAM:
            continue
        label = f"turret{k}"
        az, el, d = compute_az_el(my_turret["r"], my_turret["theta"],
                                  v["r"], v["theta"], 0)
        raw_target_angles[label] = {"az": az, "el": el}
        c = calibration.get(label, {"az": 0, "el": 0})
        processed_targets.append({
            "label": label,
            "kind": "turret",
            "az_deg_raw": az,
            "el_deg_raw": el,
            "az_deg_applied": normalize_deg(az + c["az"]),
            "el_deg_applied": el + c["el"],
            "distance": d
        })

    for i, g in enumerate(globes, start=1):
        label = f"globe{i}"
        az, el, d = compute_az_el(my_turret["r"], my_turret["theta"],
                                  g["r"], g["theta"], g.get("z", 0))
        raw_target_angles[label] = {"az": az, "el": el}
        c = calibration.get(label, {"az": 0, "el": 0})
        processed_targets.append({
            "label": label,
            "kind": "globe",
            "az_deg_raw": az,
            "el_deg_raw": el,
            "az_deg_applied": normalize_deg(az + c["az"]),
            "el_deg_applied": el + c["el"],
            "distance": d
        })
    return True

# ------------------ Calibration ------------------
def load_calibration():
    global calibration
    if os.path.exists(CALIB_FILE):
        with open(CALIB_FILE) as f:
            calibration = json.load(f)
    else:
        calibration = {}

def save_calibration():
    with open(CALIB_FILE, 'w') as f:
        json.dump(calibration, f, indent=2)

# ------------------ Motors ------------------
def setup_motors():
    global s, m_az, m_el
    GPIO.setmode(GPIO.BCM)
    s = Shifter(DATA_PIN, LATCH_PIN, CLOCK_PIN)
    m_az = Stepper(s, multiprocessing.Lock())
    m_el = Stepper(s, multiprocessing.Lock())
    m_az.zero()
    m_el.zero()

# ------------------ Laser ------------------
def setup_laser():
    GPIO.setup(LASER_PIN, GPIO.OUT)
    GPIO.output(LASER_PIN, GPIO.LOW)

def fire_laser():
    GPIO.output(LASER_PIN, GPIO.HIGH)
    time.sleep(LASER_ON_SECONDS)
    GPIO.output(LASER_PIN, GPIO.LOW)

# ------------------ Motion ------------------
def manual_step(axis, delta):
    delta = float(delta)
    if axis == "az":
        m_az.rotate(delta)
    elif axis == "el":
        if EL_INVERT:
            delta = -delta
        with m_el.angle.get_lock():
            new_el = m_el.angle.value + delta
        if EL_MIN_DEG <= new_el <= EL_MAX_DEG:
            m_el.rotate(delta)

def goto_target(label):
    tgt = next(t for t in processed_targets if t["label"] == label)

    def worker():
        az = tgt["az_deg_applied"]
        el = apply_elevation_limits(tgt["el_deg_applied"])
        m_az.goAngle(az)
        m_el.goAngle(el)

    threading.Thread(target=worker, daemon=True).start()

def save_calibration_for_label(label):
    raw = raw_target_angles[label]
    with m_az.angle.get_lock():
        cur_az = m_az.angle.value
    with m_el.angle.get_lock():
        cur_el = m_el.angle.value
    if EL_INVERT:
        cur_el = -cur_el

    def shortest(a):
        return ((a + 180) % 360) - 180

    calibration[label] = {
        "az": shortest(cur_az - raw["az"]),
        "el": cur_el - raw["el"]
    }
    save_calibration()
    build_processed_targets()
    return calibration[label]

# ------------------ Server ------------------
# ------------------ HTTP helpers ------------------
def recv_request(conn):
    try:
        return conn.recv(8192).decode('utf-8', errors='ignore')
    except:
        return ''

def parse_request_line(req_text):
    first = req_text.split("\r\n", 1)[0]
    parts = first.split()
    return (parts[0], parts[1]) if len(parts) >= 2 else ("GET", "/")

def parse_post_body(req_text):
    i = req_text.find("\r\n\r\n")
    if i < 0:
        return {}
    body = req_text[i+4:]
    out = {}
    for pair in body.split("&"):
        if "=" in pair:
            k, v = pair.split("=", 1)
            out[k] = unquote_plus(v)
    return out

def send_html(conn, html, status=200):
    try:
        b = html.encode()
        header = f"HTTP/1.1 {status} OK\r\nContent-Type: text/html\r\nConnection: close\r\nContent-Length: {len(b)}\r\n\r\n"
        conn.sendall(header.encode() + b)
    except Exception as e:
        print("send_html error:", e)

def send_json(conn, obj_dict):
    try:
        b = json.dumps(obj_dict).encode()
        header = f"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: {len(b)}\r\n\r\n"
        conn.sendall(header.encode() + b)
    except Exception as e:
        print("send_json error:", e)

# ------------------ UI HTML ------------------
def page_html():
    return """<!doctype html>
<html><head><meta charset="utf-8"><title>Turret Control (Calibration)</title>
<style>
body { font-family: Arial, sans-serif; margin: 16px; }
button { padding: 8px 12px; margin: 6px; }
.sect { border: 1px solid #ddd; padding: 12px; margin-bottom: 12px; border-radius: 6px; max-width: 760px; }
#angles { white-space: pre; background: #f7f7f7; padding: 8px; border-radius: 4px; }
#targetsDebug { max-height: 220px; overflow: auto; background: #f4f4f4; padding: 8px; }
</style>
</head><body>
<h1>Turret Control — Calibration</h1>

<div class="sect">
  <h3>Manual</h3>
  <div><strong>Azimuth</strong><br>
    <button onclick="api('/laser','POST')">Laser (3s)</button>
    <button onclick="step('az',-5)">◀ -5°</button>
    <button onclick="step('az',-1)">◀ -1°</button>
    <button onclick="step('az',-0.5)">◀ -0.5°</button>
    <button onclick="step('az',0.5)">0.5° ▶</button>
    <button onclick="step('az',1)">1° ▶</button>
    <button onclick="step('az',5)">5° ▶</button>
  </div>
  <div style="margin-top:8px"><strong>Elevation</strong><br>
    <button onclick="step('el',-5)">▼ -5°</button>
    <button onclick="step('el',-1)">▼ -1°</button>
    <button onclick="step('el',-0.5)">▼ -0.5°</button>
    <button onclick="step('el',0.5)">0.5° ▲</button>
    <button onclick="step('el',1)">1° ▲</button>
    <button onclick="step('el',5)">5° ▲</button>
  </div>
  <div style="margin-top:10px;"><button onclick="zero()">Zero Motors</button></div>
</div>

<div class="sect">
  <h3>Targets & Calibration</h3>
  <select id="targetSelect" style="width:320px;padding:8px;font-size:14px"></select>
  <div style="margin-top:10px">
    <button onclick="gotoSelected()">Go to selected target</button>
    <button onclick="saveCalibration()">Save Calibration (use current motor angles)</button>
    <button onclick="reloadTargets()">Reload Targets</button>
    <span id="targetMsg" style="margin-left:8px"></span>
  </div>
  <div style="margin-top:10px"><strong>Processed Targets (raw & applied):</strong>
    <pre id="targetsDebug"></pre>
  </div>
</div>

<div class="sect">
  <h3>Current Angles</h3>
  <div id="angles">Loading...</div>
</div>

<script>
async function api(path, method='GET', body=null){
  const opts = { method, headers: {} };
  if(body){
    opts.headers['Content-Type'] = 'application/x-www-form-urlencoded';
    opts.body = new URLSearchParams(body).toString();
  }
  const r = await fetch(path, opts);
  return r;
}

function step(axis, delta){
  api('/step','POST',{axis:axis, delta:String(delta)})
    .then(r=>r.json())
    .then(j=>{ if(!j.ok) alert('Step failed: '+(j.error||'')); });
}

function zero(){
  api('/zero','POST').then(r=>r.json()).then(j=>{ if(j.ok) alert('Zeroed'); });
}

function gotoSelected(){
  const sel = document.getElementById('targetSelect');
  const label = sel.value;
  if(!label){ alert('Select a target'); return; }
  document.getElementById('targetMsg').textContent = 'Going to '+label+'...';
  api('/goto','POST',{target:label}).then(r=>r.json()).then(j=>{
    if(j.ok) document.getElementById('targetMsg').textContent = 'Started moving to '+label;
    else document.getElementById('targetMsg').textContent = 'Error: '+(j.error||'');
    setTimeout(()=>document.getElementById('targetMsg').textContent='',2500);
  });
}

function saveCalibration(){
  const sel = document.getElementById('targetSelect');
  const label = sel.value;
  if(!label){ alert('Select a target'); return; }
  document.getElementById('targetMsg').textContent = 'Saving calibration for '+label+'...';
  api('/save_calibration','POST',{target:label}).then(r=>r.json()).then(j=>{
    if(j.ok){
      document.getElementById('targetMsg').textContent = 'Saved: az_offset=' + j.result.az_offset.toFixed(3) + '°, el_offset=' + j.result.el_offset.toFixed(3) + '°';
      // refresh processed targets list
      setTimeout(()=>reloadTargets(), 300);
    } else {
      document.getElementById('targetMsg').textContent = 'Error: ' + (j.error||'');
    }
    setTimeout(()=>document.getElementById('targetMsg').textContent = '', 3500);
  });
}

function reloadTargets(){
  api('/reload','POST').then(r=>r.json()).then(j=>{
    if(j.ok){ populateTargets(j.targets); }
    else alert('Reload failed: '+(j.error||''));
  });
}

function populateTargets(list){
  const sel = document.getElementById('targetSelect');
  sel.innerHTML = '';
  const dbg = document.getElementById('targetsDebug');
  dbg.textContent = JSON.stringify(list, null, 2);
  for(const t of list){
    const opt = document.createElement('option');
    opt.value = t.label;
    opt.text = t.label + ' (' + t.kind + ') rawA=' + t.az_deg_raw.toFixed(2) + '°, rawE=' + t.el_deg_raw.toFixed(2) + '°';
    sel.appendChild(opt);
  }
}

async function refreshAngles(){
  try{
    const r = await api('/angles');
    if(!r.ok) throw 'bad';
    const j = await r.json();
    document.getElementById('angles').textContent = 'Azimuth: ' + j.az.toFixed(2) + '°\\nElevation: ' + j.el.toFixed(2) + '°';
  }catch(e){
    document.getElementById('angles').textContent = 'Error fetching angles';
  }
}

async function initialLoad(){
  const r = await api('/targets');
  if(r.ok){
    const j = await r.json();
    populateTargets(j.targets);
  }
  setInterval(refreshAngles, 700);
  refreshAngles();
}
initialLoad();
</script>
</body></html>
"""

# ------------------ Endpoint handlers ------------------
def handle_step(req_text):
    data = parse_post_body(req_text)
    axis = data.get("axis", "")
    delta = float(data.get("delta", "0"))
    try:
        manual_step(axis, delta)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def handle_zero(req_text):
    try:
        set_zero()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def handle_goto(req_text):
    data = parse_post_body(req_text)
    tgt = data.get("target", "")
    if not tgt:
        return {"ok": False, "error": "no target specified"}
    ok = goto_target(tgt)
    if ok:
        return {"ok": True}
    else:
        return {"ok": False, "error": "target not found"}

def handle_reload(req_text):
    ok = load_positions()
    if not ok:
        return {"ok": False, "error": "reload failed"}
    ok2 = build_processed_targets()
    if not ok2:
        return {"ok": False, "error": "processing failed"}
    return {"ok": True, "targets": processed_targets}

def handle_targets(req_text=None):
    return {"ok": True, "targets": processed_targets}

def handle_angles(req_text=None):
    try:
        with m_az.angle.get_lock():
            az = float(m_az.angle.value)
        with m_el.angle.get_lock():
            el = float(m_el.angle.value)
        return {"ok": True, "az": az, "el": el}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def handle_save_calibration(req_text):
    data = parse_post_body(req_text)
    tgt = data.get("target", "")
    if not tgt:
        return {"ok": False, "error": "no target specified"}
    ok, result = save_calibration_for_label(tgt)
    if not ok:
        return {"ok": False, "error": result}
    # return the offsets in result dict
    return {"ok": True, "result": result}

def handle_laser(req_text=None):
    """Trigger laser in background and return quickly."""
    handle_laser_request()
    return {"ok": True, "message": f"Laser firing for {LASER_ON_SECONDS}s"}

# ------------------ Server loop ------------------
def run_server():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((HOST, PORT))
    sock.listen(5)
    print(f"Serving on http://<pi-ip>:{PORT} - open in browser from another device on same Wi-Fi")

    while True:
        conn, addr = sock.accept()
        try:
            req = recv_request(conn)
            if not req:
                conn.close(); continue
            method, path = parse_request_line(req)
            print("Request:", method, path, "from", addr)

            if method == "GET":
                if path == "/targets":
                    send_json(conn, handle_targets())
                elif path == "/angles":
                    send_json(conn, handle_angles())
                else:
                    send_html(conn, page_html())
            elif method == "POST":
                if path == "/step":
                    res = handle_step(req); send_json(conn, res)
                elif path == "/zero":
                    res = handle_zero(req); send_json(conn, res)
                elif path == "/goto":
                    res = handle_goto(req); send_json(conn, res)
                elif path == "/reload":
                    res = handle_reload(req); send_json(conn, res)
                elif path == "/save_calibration":
                    res = handle_save_calibration(req); send_json(conn, res)
                elif path == "/laser":
                    res = handle_laser(req); send_json(conn, res)
                else:
                    send_json(conn, {"ok": False, "error": "unknown POST"})
            else:
                send_html(conn, "<html><body>unsupported method</body></html>")
        except Exception as e:
            print("Exception handling request:", e)
            traceback.print_exc()
        finally:
            conn.close()

# ENTRY POINT
if __name__ == "__main__":
    try:
        load_calibration()
        setup_laser()
        setup_motors()
        load_positions()
        build_processed_targets()
        print("System ready.")
        # run_server()  ← your existing server call
    finally:
        GPIO.cleanup()
