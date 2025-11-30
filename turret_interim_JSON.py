# turret_interim_JSON.py
#
# Interim checkpoint with JSON loading:
# - Reads turret + globe coordinates from a local file OR URL
# - Separates our team (team 3)
# - Provides /coords endpoint for debugging
# - Everything else remains identical to your original server

import socket
import time
import multiprocessing
import json
import urllib.request
import os
import RPi.GPIO as GPIO

from shifter import Shifter
from stepper_class_shiftregister_multiprocessing import Stepper


# ----------------- CONFIG -----------------

# Shift register pins (BCM)
DATA_PIN  = 16
LATCH_PIN = 20
CLOCK_PIN = 21

# Slider limits
AZ_MIN = -180
AZ_MAX =  180
EL_MIN = -90
EL_MAX =  90

HOST = ""   # listen on all interfaces
PORT = 8080

# ---------- JSON CONFIG ----------
USE_LOCAL_JSON = True
LOCAL_JSON_FILE = "positions.json"
JSON_URL = "http://192.168.1.254:8000/positions.json"

MY_TEAM = "3"  # <--- OUR TEAM NUMBER
# ---------------------------------


# Globals
s = None
m_az = None
m_el = None

positions = {}
my_turret = None
other_turrets = {}
globes = []


# ===========================================================
#       ### JSON LOADING SECTION ###
# ===========================================================

def load_positions():
    """Load turret/globe JSON from local file or URL."""
    if USE_LOCAL_JSON:
        if not os.path.exists(LOCAL_JSON_FILE):
            print(f"ERROR: Local file '{LOCAL_JSON_FILE}' not found!")
            return None
        print(f"Loading JSON from local file: {LOCAL_JSON_FILE}")
        with open(LOCAL_JSON_FILE, "r") as f:
            return json.load(f)
    else:
        print(f"Loading JSON from URL: {JSON_URL}")
        with urllib.request.urlopen(JSON_URL) as response:
            data = response.read().decode("utf-8")
            return json.loads(data)


def process_positions():
    """Separate our team, other teams, and globes."""
    global positions, my_turret, other_turrets, globes

    if positions is None:
        return

    turrets = positions.get("turrets", {})
    globes = positions.get("globes", [])

    my_turret = turrets.get(MY_TEAM)
    
    other_turrets = {
        team: coords for team, coords in turrets.items()
        if team != MY_TEAM
    }

    # --- PRINT EVERYTHING FOR DEBUGGING ---
    print("\n===== JSON DATA LOADED =====")

    print("\n--- YOUR TURRET (Team 3) ---")
    if my_turret:
        print(f"Team {MY_TEAM}: r={my_turret['r']}, theta={my_turret['theta']}")
    else:
        print("ERROR: Team 3 not found in JSON!")

    print("\n--- OTHER TEAMS ---")
    for team, coords in other_turrets.items():
        print(f"Team {team}: r={coords['r']}, theta={coords['theta']}")

    print("\n--- GLOBES ---")
    for i, g in enumerate(globes):
        print(f"Globe {i+1}: r={g['r']}, theta={g['theta']}, z={g['z']}")

    print("================================\n")


# ===========================================================
#              MOTOR + SERVER SECTION
# ===========================================================

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
    print("Motors initialized at 0°.")


# ---- HTTP Helpers ----

def recv_request(conn):
    return conn.recv(8192).decode("utf-8", errors="ignore")

def parse_request_line(req_text):
    first = req_text.split("\r\n", 1)[0]
    parts = first.split()
    return parts[0], parts[1] if len(parts) >= 2 else ( "GET", "/" )

def parse_post_body(req_text):
    i = req_text.find("\r\n\r\n")
    if i < 0: return {}
    body = req_text[i+4:]
    out = {}
    for pair in body.split("&"):
        if "=" in pair:
            k, v = pair.split("=", 1)
            out[k] = v
    return out

def send_html(conn, html):
    conn.sendall((
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: text/html\r\n"
        "Connection: close\r\n\r\n"
    ).encode() + html.encode())

def send_json(conn, obj):
    conn.sendall((
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: application/json\r\n"
        "Connection: close\r\n\r\n"
    ).encode() + obj.encode())


# ---- HTML PAGE SAME AS BEFORE ----
def page_html():
    return f"""<!doctype html>
<html>
<head><meta charset="utf-8"><title>ENME441 Turret Control</title></head>
<body>
  <h1>IoT Laser Turret</h1>

  <h2>Manual Control</h2>

  <div>
    <label>Azimuth</label>
    <input id="az" type="range" min="{AZ_MIN}" max="{AZ_MAX}" value="0">
    <span id="az_val">0</span>°
  </div>

  <div>
    <label>Elevation</label>
    <input id="el" type="range" min="{EL_MIN}" max="{EL_MAX}" value="0">
    <span id="el_val">0</span>°
  </div>

  <button onclick="zeroAll()">Zero Motors</button>

<script>
async function sendAngle(axis, angle) {{
  await fetch("/set", {{
    method: "POST",
    headers: {{ "Content-Type": "application/x-www-form-urlencoded" }},
    body: "axis="+axis+"&angle="+angle
  }});
}}

document.getElementById("az").oninput = e => {{
  az_val.textContent = e.target.value;
  sendAngle("az", e.target.value);
}};
document.getElementById("el").oninput = e => {{
  el_val.textContent = e.target.value;
  sendAngle("el", e.target.value);
}};

async function zeroAll() {{
  await fetch("/zero", {{method:"POST"}});
  az.value=0; el.value=0;
  az_val.textContent=0; el_val.textContent=0;
}}
</script>

</body>
</html>"""


# ---- POST Handlers ----

def handle_post_set(req_text):
    data = parse_post_body(req_text)
    axis = data.get("axis", "")
    angle = float(data.get("angle", "0"))

    if axis == "az":  m_az.goAngle(angle)
    if axis == "el":  m_el.goAngle(angle)

def handle_post_zero():
    m_az.zero()
    m_el.zero()


# ---- MAIN SERVER LOOP ----

def run_server():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((HOST, PORT))
    sock.listen(5)

    print(f"Serving at http://raspberrypi.local:{PORT}")

    while True:
        conn, addr = sock.accept()
        req = recv_request(conn)
        method, path = parse_request_line(req)

        if method == "GET":
            if path == "/coords":
                send_json(conn, json.dumps(positions, indent=2))
            else:
                send_html(conn, page_html())

        elif method == "POST":
            if path == "/set":
                handle_post_set(req)
                send_json(conn, '{"status":"ok"}')
            elif path == "/zero":
                handle_post_zero()
                send_json(conn, '{"status":"zeroed"}')

        conn.close()


# ===========================================================
#                     MAIN ENTRY
# ===========================================================

if __name__ == "__main__":
    try:
        setup_motors()

        global positions
        positions = load_positions()
        process_positions()  # <-- prints your turret, others, globes

        run_server()

    except KeyboardInterrupt:
        print("Shutting down...")

    finally:
        if s:
            s.shiftByte(0)
        GPIO.cleanup()
        print("GPIO cleaned up.")
