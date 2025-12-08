#!/usr/bin/env python3
"""
turret_server_dropdown.py

- Loads positions.json (local or URL) and converts (r,theta,z) -> az/el (deg)
- Serves a small HTTP UI (socket-based) with:
    - manual step buttons (±0.5°, ±1°, ±5°)
    - dropdown of targets (turret1.. turretN, globe1.. globeM)
    - Go button to move to selected target (background thread)
    - Reload targets button
    - Zero motors button
- Uses your Shifter and Stepper classes (BYJ48 + shift register)
"""
import socket, time, json, os, math, threading, sys, traceback
from urllib.parse import unquote_plus
import multiprocessing
import RPi.GPIO as GPIO

from shifter import Shifter
from stepper_class_shiftregister_multiprocessing import Stepper

# ------------------ Config ------------------
DATA_PIN  = 16
LATCH_PIN = 20
CLOCK_PIN = 21

USE_LOCAL_JSON = True
LOCAL_JSON_FILE = "positions.json"
JSON_URL = "http://192.168.1.254:8000/positions.json"

MY_TEAM = "3"   # your turret id as string

HOST = ""
PORT = 8080

ANGLE_TOLERANCE_DEG = 0.8

# ------------------ Globals ------------------
s = None
m_az = None
m_el = None

positions = {}
my_turret = None
processed_targets = []   # list of dicts: { label, kind, az_deg, el_deg, r, theta, z, distance }

# ------------------ JSON load & conversion ------------------
def load_positions():
    global positions
    try:
        if USE_LOCAL_JSON:
            if not os.path.exists(LOCAL_JSON_FILE):
                print(f"ERROR: local JSON '{LOCAL_JSON_FILE}' not found", file=sys.stderr)
                return None
            with open(LOCAL_JSON_FILE,'r') as f:
                positions = json.load(f)
        else:
            import urllib.request
            with urllib.request.urlopen(JSON_URL, timeout=6) as resp:
                positions = json.loads(resp.read().decode('utf-8'))
        return positions
    except Exception as e:
        print("Error loading positions:", e, file=sys.stderr)
        return None

def polar_to_cartesian_cm(r_cm, theta_rad, z_cm=0.0):
    x = r_cm * math.cos(theta_rad)
    y = r_cm * math.sin(theta_rad)
    return x, y, z_cm

def normalize_deg(angle):
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
    """Build processed_targets list from positions"""
    global processed_targets, my_turret
    processed_targets = []
    turrets = positions.get("turrets", {})
    globes = positions.get("globes", [])

    my_turret = turrets.get(MY_TEAM)
    if my_turret is None:
        print(f"ERROR: MY_TEAM {MY_TEAM} not found in JSON", file=sys.stderr)
        return False

    # other turrets first
    for k, v in turrets.items():
        if k == MY_TEAM: continue
        az, el, dist = compute_az_el(my_turret["r"], my_turret["theta"], v["r"], v["theta"], 0.0)
        processed_targets.append({
            "label": f"turret{k}",
            "kind": "turret",
            "id": k,
            "r": v["r"], "theta": v["theta"], "z": 0.0,
            "az_deg": az, "el_deg": el, "distance": dist
        })

    # globes
    for i, g in enumerate(globes, start=1):
        az, el, dist = compute_az_el(my_turret["r"], my_turret["theta"], g["r"], g["theta"], g.get("z",0.0))
        processed_targets.append({
            "label": f"globe{i}",
            "kind": "globe",
            "id": i-1,
            "r": g["r"], "theta": g["theta"], "z": g.get("z",0.0),
            "az_deg": az, "el_deg": el, "distance": dist
        })
    return True

# ------------------ Motors ------------------
def setup_motors():
    global s, m_az, m_el
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)
    s = Shifter(data=DATA_PIN, latch=LATCH_PIN, clock=CLOCK_PIN)
    lock1 = multiprocessing.Lock()
    lock2 = multiprocessing.Lock()
    m_az = Stepper(s, lock1)
    m_el = Stepper(s, lock2)
    m_az.zero()
    m_el.zero()
    print("Motors ready (zeroed).")

# ------------------ motor wait ------------------
def wait_for_motors(az_target, el_target, timeout=None):
    t0 = time.time()
    if timeout is None:
        # estimate based on steps
        with m_az.angle.get_lock():
            a_now = m_az.angle.value
        with m_el.angle.get_lock():
            e_now = m_el.angle.value
        max_deg = max(abs((az_target - a_now + 180)%360 - 180), abs((el_target - e_now + 180)%360 - 180))
        est_steps = max_deg * m_az.steps_per_degree
        timeout = est_steps * (m_az.delay / 1e6) + 0.8

    while True:
        with m_az.angle.get_lock():
            a_now = m_az.angle.value
        with m_el.angle.get_lock():
            e_now = m_el.angle.value
        a_err = abs((az_target - a_now + 180)%360 - 180)
        e_err = abs((el_target - e_now + 180)%360 - 180)
        if a_err <= ANGLE_TOLERANCE_DEG and e_err <= ANGLE_TOLERANCE_DEG:
            return True
        if time.time() - t0 > timeout:
            return False
        time.sleep(0.03)

# ------------------ Actions ------------------
def manual_step(axis, delta):
    if axis == "az":
        m_az.rotate(delta)
    elif axis == "el":
        m_el.rotate(delta)

def set_zero():
    m_az.zero(); m_el.zero()

def goto_target_by_label(label):
    """Start a background thread that moves to the target with label (non-blocking HTTP)."""
    tgt = next((t for t in processed_targets if t["label"] == label), None)
    if tgt is None:
        print("Requested target not found:", label)
        return False

    def worker():
        try:
            az_goal = tgt["az_deg"]
            el_goal = tgt["el_deg"]
            print(f"[GOTO] moving to {label} AZ={az_goal:.2f} EL={el_goal:.2f}")
            m_az.goAngle(az_goal)
            m_el.goAngle(el_goal)
            ok = wait_for_motors(az_goal, el_goal)
            print("[GOTO] reached?" , ok)
        except Exception as e:
            print("Exception in goto worker:", e)
    threading.Thread(target=worker, daemon=True).start()
    return True

# ------------------ HTTP helpers ------------------
def recv_request(conn):
    try:
        return conn.recv(8192).decode('utf-8', errors='ignore')
    except:
        return ''

def parse_request_line(req_text):
    first = req_text.split("\r\n",1)[0]
    parts = first.split()
    return (parts[0], parts[1]) if len(parts)>=2 else ("GET","/")

def parse_post_body(req_text):
    i = req_text.find("\r\n\r\n")
    if i < 0: return {}
    body = req_text[i+4:]
    out = {}
    for pair in body.split("&"):
        if "=" in pair:
            k,v = pair.split("=",1)
            out[k] = unquote_plus(v)
    return out

def send_html(conn, html, status=200):
    try:
        b = html.encode()
        header = f"HTTP/1.1 {status} OK\r\nContent-Type: text/html\r\nConnection: close\r\nContent-Length: {len(b)}\r\n\r\n"
        conn.sendall(header.encode()+b)
    except Exception as e:
        print("send_html error:", e)

def send_json(conn, obj_dict):
    try:
        b = json.dumps(obj_dict).encode()
        header = f"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: {len(b)}\r\n\r\n"
        conn.sendall(header.encode()+b)
    except Exception as e:
        print("send_json error:", e)

# ------------------ UI HTML ------------------
FIELD_IMG_PATH = "/mnt/data/504aa1b2-e1f5-4d32-a3e6-d773904686aa.png"
def page_html():
    # The dropdown is populated client-side by fetching /targets
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Turret Control</title>
<style>body{{font-family:Arial;margin:16px}}button{{padding:8px 12px;margin:6px}}.sect{{border:1px solid #ddd;padding:12px;margin-bottom:12px;border-radius:6px;max-width:760px}}#angles{{white-space:pre;background:#f7f7f7;padding:8px;border-radius:4px}}</style>
</head><body>
<h1>Turret Control</h1>

<div class="sect">
  <h3>Manual</h3>
  <div><strong>Azimuth</strong><br>
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
  <h3>Targets</h3>
  <select id="targetSelect" style="width:320px;padding:8px;font-size:14px"></select>
  <div style="margin-top:10px">
    <button onclick="gotoSelected()">Go to selected target</button>
    <button onclick="reloadTargets()">Reload Targets</button>
    <span id="targetMsg"></span>
  </div>
  <div style="margin-top:10px"><strong>Processed Targets:</strong>
    <pre id="targetsDebug" style="max-height:220px;overflow:auto;background:#f4f4f4;padding:8px"></pre>
  </div>
</div>

<div class="sect">
  <h3>Current Angles</h3>
  <div id="angles">Loading...</div>
</div>

<div class="sect">
  <h3>Field Diagram</h3>
  <img src="/field_diagram" style="max-width:100%;"/>
</div>

<script>
async function api(path, method='GET', body=null){
  const opts = {method, headers:{}};
  if(body){
    opts.headers['Content-Type']='application/x-www-form-urlencoded';
    opts.body = new URLSearchParams(body).toString();
  }
  const r = await fetch(path, opts);
  return r;
}

function step(axis, delta){
  api('/step','POST',{axis:axis, delta:String(delta)})
    .then(r=>r.json()).then(j=>{ if(!j.ok) alert('step error');});
}

function zero(){
  api('/zero','POST').then(r=>r.json()).then(j=>{ if(j.ok) alert('zeroed');});
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

function reloadTargets(){
  api('/reload','POST').then(r=>r.json()).then(j=>{
    if(j.ok){ populateTargets(j.targets); }
    else alert('Reload failed');
  });
}

function populateTargets(list){
  const sel = document.getElementById('targetSelect');
  sel.innerHTML = '';
  const dbg = document.getElementById('targetsDebug');
  dbg.textContent = JSON.stringify(list, null, 2);
  for(const t of list){
    const opt = document.createElement('option');
    opt.value = t.label; opt.text = t.label + ' ('+t.kind+')</option>';
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
    document.getElementById('angles').textContent = 'Error';
  }
}

async function initialLoad(){
  // load targets
  const r = await api('/targets');
  if(r.ok){ const j = await r.json(); populateTargets(j.targets); }
  // set angles poll
  setInterval(refreshAngles, 700);
  refreshAngles();
}
initialLoad();
</script>
</body></html>"""

# ------------------ Handlers for endpoints ------------------
def handle_step(req_text):
    data = parse_post_body(req_text)
    axis = data.get("axis","")
    delta = float(data.get("delta","0"))
    manual_step(axis, delta)
    return {"ok": True}

def handle_zero(req_text):
    set_zero()
    return {"ok": True}

def handle_goto(req_text):
    data = parse_post_body(req_text)
    tgt = data.get("target","")
    if not tgt:
        return {"ok": False, "error": "no target"}
    ok = goto_target_by_label(tgt)
    if ok:
        return {"ok": True}
    else:
        return {"ok": False, "error": "target not found"}

def handle_reload(req_text):
    ok = load_positions()
    if not ok:
        return {"ok": False, "error": "reload failed"}
    build_processed_targets()
    # return processed targets for UI
    return {"ok": True, "targets": processed_targets}

def handle_targets(req_text=None):
    # return processed targets list
    return {"ok": True, "targets": processed_targets}

def handle_angles(req_text=None):
    with m_az.angle.get_lock():
        az = m_az.angle.value
    with m_el.angle.get_lock():
        el = m_el.angle.value
    return {"ok": True, "az": float(az), "el": float(el)}

# ------------------ Server loop ------------------
def run_server():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((HOST, PORT))
    sock.listen(5)
    print(f"Serving on http://<pi-ip>:{PORT}")

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
                elif path == "/field_diagram":
                    try:
                        with open(FIELD_IMG_PATH, "rb") as f:
                            data = f.read()
                        header = "HTTP/1.1 200 OK\r\nContent-Type: image/png\r\nConnection: close\r\nContent-Length: %d\r\n\r\n" % len(data)
                        conn.sendall(header.encode() + data)
                    except:
                        send_html(conn, "<html><body>diagram not found</body></html>")
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
                else:
                    send_json(conn, {"ok": False, "error": "unknown POST"})
            else:
                send_html(conn, "<html><body>unsupported</body></html>")
        except Exception as e:
            print("Exception:", e); traceback.print_exc()
        finally:
            conn.close()

# ------------------ Main ------------------
if __name__ == "__main__":
    try:
        setup_motors()
        ok = load_positions()
        if not ok:
            print("Warning: positions not loaded. Create positions.json or set JSON_URL.", file=sys.stderr)
            positions = {}
        build_processed_targets()
        run_server()
    except KeyboardInterrupt:
        print("Shutting down...")
    finally:
        try:
            if s: s.shiftByte(0)
        except: pass
        GPIO.cleanup()
        print("Cleaned up.")
