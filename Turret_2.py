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

MY_TEAM = "3"   # turret id (string)

HOST = ""
PORT = 8080

ANGLE_TOLERANCE_DEG = 0.8

CALIB_FILE = "calibration.json"

# Laser settings
LASER_PIN = 17        # GPIO17, active HIGH
LASER_ON_SECONDS = 3  # seconds to fire

# ------------------ Globals ------------------
s = None
m_az = None
m_el = None

positions = {}
my_turret = None
processed_targets = []   # list of dicts {label, kind, az_deg_raw, el_deg_raw, az_deg_applied, el_deg_applied, distance, ...}
raw_target_angles = {}   # map label -> {'az': raw, 'el': raw}
calibration = {}         # map label -> {'az': offset_deg, 'el': offset_deg}

# ------------------ JSON loading & conversion ------------------
def load_positions():
    global positions
    try:
        if USE_LOCAL_JSON:
            if not os.path.exists(LOCAL_JSON_FILE):
                print(f"ERROR: local JSON '{LOCAL_JSON_FILE}' not found", file=sys.stderr)
                positions = {}
                return False
            with open(LOCAL_JSON_FILE, 'r') as f:
                positions = json.load(f)
        else:
            import urllib.request
            with urllib.request.urlopen(JSON_URL, timeout=6) as resp:
                positions = json.loads(resp.read().decode('utf-8'))
        return True
    except Exception as e:
        print("Error loading positions:", e, file=sys.stderr)
        positions = {}
        return False

def polar_to_cartesian_cm(r_cm, theta_rad, z_cm=0.0):
    x = r_cm * math.cos(theta_rad)
    y = r_cm * math.sin(theta_rad)
    return x, y, z_cm

def normalize_deg(angle):
    # returns in [0,360)
    return (angle % 360.0 + 360.0) % 360.0

def compute_az_el(tur_r, tur_theta, tgt_r, tgt_theta, tgt_z):
    tx, ty, tz = polar_to_cartesian_cm(tur_r, tur_theta, 0.0)
    px, py, pz = polar_to_cartesian_cm(tgt_r, tgt_theta, tgt_z)
    dx = px - tx; dy = py - ty; dz = pz - tz
    az_rad = math.atan2(dy, dx)
    az_deg = normalize_deg(math.degrees(az_rad))
    horiz = math.hypot(dx, dy)
    el_deg = math.degrees(math.atan2(dz, horiz))
    dist = math.sqrt(dx*dx + dy*dy + dz*dz)
    return az_deg, el_deg, dist

def build_processed_targets():
    """
    Populate processed_targets and raw_target_angles from loaded positions.
    Labels: turret<id> for other turrets, globe1..N for globes.
    Also compute 'applied' az/el using calibration offsets (if any).
    """
    global processed_targets, my_turret, raw_target_angles
    processed_targets = []
    raw_target_angles = {}

    turrets = positions.get("turrets", {})
    globes = positions.get("globes", [])

    my_turret = turrets.get(MY_TEAM)
    if my_turret is None:
        print(f"ERROR: MY_TEAM '{MY_TEAM}' not found in JSON", file=sys.stderr)
        return False

    # other turrets
    for k, v in turrets.items():
        if k == MY_TEAM:
            continue
        label = f"turret{k}"
        az_raw, el_raw, dist = compute_az_el(my_turret["r"], my_turret["theta"], v["r"], v["theta"], 0.0)
        raw_target_angles[label] = {"az": az_raw, "el": el_raw}
        # apply calibration offsets if present
        c = calibration.get(label, {"az": 0.0, "el": 0.0})
        az_applied = normalize_deg(az_raw + c.get("az", 0.0))
        el_applied = el_raw + c.get("el", 0.0)
        processed_targets.append({
            "label": label,
            "kind": "turret",
            "id": k,
            "r": v["r"], "theta": v["theta"], "z": 0.0,
            "az_deg_raw": az_raw, "el_deg_raw": el_raw,
            "az_deg_applied": az_applied, "el_deg_applied": el_applied,
            "distance": dist
        })

    # globes
    for i, g in enumerate(globes, start=1):
        label = f"globe{i}"
        az_raw, el_raw, dist = compute_az_el(my_turret["r"], my_turret["theta"], g["r"], g["theta"], g.get("z", 0.0))
        raw_target_angles[label] = {"az": az_raw, "el": el_raw}
        c = calibration.get(label, {"az": 0.0, "el": 0.0})
        az_applied = normalize_deg(az_raw + c.get("az", 0.0))
        el_applied = el_raw + c.get("el", 0.0)
        processed_targets.append({
            "label": label,
            "kind": "globe",
            "id": i-1,
            "r": g["r"], "theta": g["theta"], "z": g.get("z", 0.0),
            "az_deg_raw": az_raw, "el_deg_raw": el_raw,
            "az_deg_applied": az_applied, "el_deg_applied": el_applied,
            "distance": dist
        })

    return True

# ------------------ Calibration persistence ------------------
def load_calibration():
    global calibration
    if not os.path.exists(CALIB_FILE):
        calibration = {}
        save_calibration()  # create empty file
        return
    try:
        with open(CALIB_FILE, 'r') as f:
            calibration = json.load(f)
    except Exception as e:
        print("Error loading calibration.json:", e, file=sys.stderr)
        calibration = {}

def save_calibration():
    try:
        with open(CALIB_FILE, 'w') as f:
            json.dump(calibration, f, indent=2)
    except Exception as e:
        print("Error saving calibration.json:", e, file=sys.stderr)

# ------------------ Motor setup ------------------
def setup_motors():
    global s, m_az, m_el
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)
    s = Shifter(data=DATA_PIN, latch=LATCH_PIN, clock=CLOCK_PIN)
    lock1 = multiprocessing.Lock()
    lock2 = multiprocessing.Lock()
    # instantiate az then el
    m_az = Stepper(s, lock1)
    m_el = Stepper(s, lock2)
    m_az.zero()
    m_el.zero()
    print("Motors initialized and zeroed.")

# ------------------ Laser setup ------------------
def setup_laser():
    GPIO.setup(LASER_PIN, GPIO.OUT)
    GPIO.output(LASER_PIN, GPIO.LOW)   # ensure off

def fire_laser():
    """Turn laser on for LASER_ON_SECONDS (blocking inside thread)."""
    try:
        print("Laser ON")
        GPIO.output(LASER_PIN, GPIO.HIGH)
        time.sleep(LASER_ON_SECONDS)
    finally:
        GPIO.output(LASER_PIN, GPIO.LOW)
        print("Laser OFF")

def handle_laser_request():
    """Start a thread to fire the laser so HTTP handler returns quickly."""
    threading.Thread(target=fire_laser, daemon=True).start()

# ------------------ Motor helpers ------------------
def wait_for_motors(az_target, el_target, timeout=None):
    """Wait until both motors are within ANGLE_TOLERANCE_DEG or timeout."""
    start = time.time()
    if timeout is None:
        with m_az.angle.get_lock():
            az_now = m_az.angle.value
        with m_el.angle.get_lock():
            el_now = m_el.angle.value
        az_delta = abs((az_target - az_now + 180.0) % 360.0 - 180.0)
        el_delta = abs((el_target - el_now + 180.0) % 360.0 - 180.0)
        max_deg = max(az_delta, el_delta)
        est_steps = max_deg * m_az.steps_per_degree
        est_per_step = m_az.delay / 1e6
        timeout = est_steps * est_per_step + 0.8

    while True:
        with m_az.angle.get_lock():
            az_now = m_az.angle.value
        with m_el.angle.get_lock():
            el_now = m_el.angle.value
        az_err = abs((az_target - az_now + 180.0) % 360.0 - 180.0)
        el_err = abs((el_target - el_now + 180.0) % 360.0 - 180.0)
        if az_err <= ANGLE_TOLERANCE_DEG and el_err <= ANGLE_TOLERANCE_DEG:
            return True
        if time.time() - start > timeout:
            return False
        time.sleep(0.03)

# ------------------ Actions ------------------
def manual_step(axis, delta):
    """Relative motion using Stepper.rotate(delta)."""
    if axis == "az":
        m_az.rotate(float(delta))
    elif axis == "el":
        m_el.rotate(float(delta))

def set_zero():
    m_az.zero()
    m_el.zero()

def goto_target(label):
    """Start background thread that moves to processed target using applied angles (raw + calibration)."""
    tgt = next((t for t in processed_targets if t["label"] == label), None)
    if tgt is None:
        print("goto: target not found:", label)
        return False

    def worker():
        try:
            az_goal = float(tgt["az_deg_applied"])
            el_goal = float(tgt["el_deg_applied"])
            print(f"[GOTO] moving to {label}: AZ={az_goal:.2f}, EL={el_goal:.2f}")
            m_az.goAngle(az_goal)
            m_el.goAngle(el_goal)
            ok = wait_for_motors(az_goal, el_goal)
            print("[GOTO] done, reached:", ok)
        except Exception as e:
            print("Exception in goto worker:", e)
            traceback.print_exc()

    thr = threading.Thread(target=worker, daemon=True)
    thr.start()
    return True

def save_calibration_for_label(label):
    """
    Compute offsets = current_motor_angles - raw_angles and save to calibration dict & file.
    Uses raw_target_angles[label] which stores computed raw (no offsets).
    """
    if label not in raw_target_angles:
        return False, "label not found in raw angles"
    raw = raw_target_angles[label]
    # read current motor angles
    with m_az.angle.get_lock():
        cur_az = float(m_az.angle.value)
    with m_el.angle.get_lock():
        cur_el = float(m_el.angle.value)
    # compute offsets: offset = current - raw
    # be careful with wrap-around for azimuth (want shortest signed difference)
    raw_az = float(raw["az"])
    # compute signed shortest delta between raw_az and current - we want offset such that:
    # raw + offset -> cur  (offset possibly negative or >180/-180)
    # offset = shortest_signed(cur - raw)
    def shortest_signed(a):
        # returns value in (-180,180]
        x = ((a + 180.0) % 360.0) - 180.0
        return x

    az_diff = shortest_signed(cur_az - raw_az)
    el_diff = cur_el - float(raw["el"])  # elevation is not wrapped
    calibration[label] = {"az": az_diff, "el": el_diff}
    save_calibration()
    # update processed_targets to reflect saved calibration
    build_processed_targets()
    return True, {"az_offset": az_diff, "el_offset": el_diff}

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

# ------------------ Entry point ------------------
if __name__ == "__main__":
    try:
        load_calibration()
        setup_laser()
        setup_motors()
        ok = load_positions()
        if not ok:
            print("Warning: positions not loaded. Create positions.json or set JSON_URL.", file=sys.stderr)
            positions = {}
        built = build_processed_targets()
        if not built:
            print("Warning: processed_targets empty or failed. Check JSON / MY_TEAM.", file=sys.stderr)
        run_server()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        try:
            if s: s.shiftByte(0)
        except:
            pass
        GPIO.cleanup()
        print("GPIO cleaned up.")
