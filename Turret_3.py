#!/usr/bin/env python3
"""
turret_server_calibration.py

- Manual az/el control
- Target dropdown (turrets + globes)
- Go-to-target
- Per-target calibration save
- Reload targets
- Laser fire button (GPIO17 active HIGH, 3s)
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

MY_TEAM = "3"

HOST = ""
PORT = 8080

ANGLE_TOLERANCE_DEG = 0.8
CALIB_FILE = "calibration.json"

# Laser
LASER_PIN = 17
LASER_ON_SECONDS = 3

# Elevation behavior
EL_MIN_DEG = -10.0    # down
EL_MAX_DEG = 90.0     # up

# ------------------ Globals ------------------
s = None
m_az = None
m_el = None

positions = {}
my_turret = None
processed_targets = []
raw_target_angles = {}
calibration = {}

# ------------------ Utility ------------------
def normalize_deg(a):
    return (a + 360.0) % 360.0

def clamp(val, lo, hi):
    return max(lo, min(hi, val))

# ------------------ JSON & Geometry ------------------
def load_positions():
    global positions
    try:
        with open(LOCAL_JSON_FILE, "r") as f:
            positions = json.load(f)
        return True
    except Exception as e:
        print("Error loading positions.json:", e)
        positions = {}
        return False

def polar_to_cartesian(r, theta, z=0):
    return r * math.cos(theta), r * math.sin(theta), z

def compute_az_el(tr, tt, rr, rt, rz):
    tx, ty, _ = polar_to_cartesian(tr, tt, 0)
    px, py, pz = polar_to_cartesian(rr, rt, rz)

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
        az, el, d = compute_az_el(
            my_turret["r"], my_turret["theta"],
            v["r"], v["theta"], 0.0
        )
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
        az, el, d = compute_az_el(
            my_turret["r"], my_turret["theta"],
            g["r"], g["theta"], g.get("z", 0.0)
        )
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
        with open(CALIB_FILE, "r") as f:
            calibration = json.load(f)
    else:
        calibration = {}

def save_calibration():
    with open(CALIB_FILE, "w") as f:
        json.dump(calibration, f, indent=2)

def save_calibration_for_label(label):
    raw = raw_target_angles[label]

    with m_az.angle.get_lock():
        cur_az = m_az.angle.value
    with m_el.angle.get_lock():
        cur_el = m_el.angle.value

    def shortest(a):
        return ((a + 180) % 360) - 180

    calibration[label] = {
        "az": shortest(cur_az - raw["az"]),
        "el": cur_el - raw["el"]
    }
    save_calibration()
    build_processed_targets()
    return calibration[label]

# ------------------ Hardware ------------------
def setup_motors():
    global s, m_az, m_el
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)

    s = Shifter(DATA_PIN, LATCH_PIN, CLOCK_PIN)
    m_az = Stepper(s, multiprocessing.Lock())
    m_el = Stepper(s, multiprocessing.Lock())

    m_az.zero()
    m_el.zero()
    print("Motors zeroed")

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
        with m_el.angle.get_lock():
            next_el = m_el.angle.value + delta
        if EL_MIN_DEG <= next_el <= EL_MAX_DEG:
            m_el.rotate(delta)

def goto_target(label):
    tgt = next(t for t in processed_targets if t["label"] == label)

    def worker():
        az = tgt["az_deg_applied"]
        el = clamp(tgt["el_deg_applied"], EL_MIN_DEG, EL_MAX_DEG)
        m_az.goAngle(az)
        m_el.goAngle(el)

    threading.Thread(target=worker, daemon=True).start()

# ------------------ HTTP Helpers ------------------
def parse_post(req):
    body = req.split("\r\n\r\n", 1)[-1]
    out = {}
    for p in body.split("&"):
        if "=" in p:
            k, v = p.split("=", 1)
            out[k] = unquote_plus(v)
    return out

def send_json(conn, obj):
    b = json.dumps(obj).encode()
    conn.sendall(
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: application/json\r\n"
        b"Content-Length: " + str(len(b)).encode() + b"\r\n\r\n" + b
    )

def send_html(conn, html):
    b = html.encode()
    conn.sendall(
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: text/html\r\n"
        b"Content-Length: " + str(len(b)).encode() + b"\r\n\r\n" + b
    )

# ------------------ Web Page ------------------
def page_html():
    return """<!doctype html>
<html><body>
<h2>Turret Control</h2>

<button onclick="fetch('/laser',{method:'POST'})">Laser (3s)</button><br><br>

<button onclick="step('az',-1)">AZ -</button>
<button onclick="step('az',1)">AZ +</button><br>

<button onclick="step('el',-1)">EL -</button>
<button onclick="step('el',1)">EL +</button><br><br>

<select id="tgt"></select><br>
<button onclick="go()">Go</button>
<button onclick="saveCal()">Save Calibration</button>

<script>
function step(a,d){ fetch('/step',{method:'POST',body:'axis='+a+'&delta='+d}); }
function go(){ fetch('/goto',{method:'POST',body:'target='+tgt.value}); }
function saveCal(){ fetch('/save_calibration',{method:'POST',body:'target='+tgt.value}); }

fetch('/targets').then(r=>r.json()).then(j=>{
  let s=document.getElementById('tgt');
  j.targets.forEach(t=>{
    let o=document.createElement('option');
    o.value=t.label; o.text=t.label;
    s.appendChild(o);
  });
});
</script>
</body></html>"""

# ------------------ Server ------------------
def run_server():
    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((HOST, PORT))
    sock.listen(5)
    print(f"Server running on port {PORT}")

    while True:
        conn, _ = sock.accept()
        try:
            req = conn.recv(4096).decode()
            method, path = req.split(" ", 2)[:2]

            if method == "GET":
                if path == "/targets":
                    send_json(conn, {"targets": processed_targets})
                else:
                    send_html(conn, page_html())

            elif method == "POST":
                if path == "/step":
                    d = parse_post(req)
                    manual_step(d["axis"], d["delta"])
                    send_json(conn, {"ok": True})
                elif path == "/goto":
                    goto_target(parse_post(req)["target"])
                    send_json(conn, {"ok": True})
                elif path == "/save_calibration":
                    res = save_calibration_for_label(parse_post(req)["target"])
                    send_json(conn, {"ok": True, "result": res})
                elif path == "/laser":
                    threading.Thread(target=fire_laser, daemon=True).start()
                    send_json(conn, {"ok": True})
        except Exception:
            traceback.print_exc()
        finally:
            conn.close()

# ------------------ Entry Point ------------------
if __name__ == "__main__":
    try:
        load_calibration()
        setup_laser()
        setup_motors()
        load_positions()
        build_processed_targets()
        run_server()
    except KeyboardInterrupt:
        print("Shutting down")
    finally:
        GPIO.cleanup()
