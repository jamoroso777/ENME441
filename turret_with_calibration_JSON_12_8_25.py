import socket
import time
import multiprocessing
import json
import math
import urllib.request
import os
import RPi.GPIO as GPIO

from shifter import Shifter
from stepper_class_shiftregister_multiprocessing import Stepper


# Global Variables:

DATA_PIN  = 16   # GPIO Pins
LATCH_PIN = 20
CLOCK_PIN = 21

AZ_MIN = -180   # Slider limits
AZ_MAX =  180
EL_MIN = -90
EL_MAX =  90

HOST = ""   # Listen on all interfaces
PORT = 8080

USE_LOCAL_JSON = True          # local json for testing
LOCAL_JSON_FILE = "positions.json"
JSON_URL = "http://192.168.1.254:8000/positions.json"        # actual json url for final project

MY_TEAM = "3"  

# empty variable declarations for set up

s = None
m_az = None
m_el = None

positions = {}      # dict for turret and globe locations
my_turret = None
other_turrets = {}
globes = []


# json function defs

def load_positions():
    # load json from local file or url
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


# ----------------------------------------------------------
# Compute Azimuth and Elevation angles
# ----------------------------------------------------------
def compute_az_el(my_pos, target_pos):
    # unpack
    r1, th1, z1 = my_pos["r"], my_pos["theta"], my_pos.get("z", 0)
    r2, th2, z2 = target_pos["r"], target_pos["theta"], target_pos.get("z", 0)

    # convert to XY
    x1, y1 = polar_to_xy(r1, th1)
    x2, y2 = polar_to_xy(r2, th2)

    dx = x2 - x1
    dy = y2 - y1
    dz = z2 - z1

    # horizontal distance in XY plane
    horizontal_dist = math.sqrt(dx*dx + dy*dy)

    # --- AZIMUTH ---
    az = math.degrees(math.atan2(dy, dx))
    if az > 180: az -= 360
    if az < -180: az += 360

    # --- ELEVATION ---
    el = math.degrees(math.atan2(dz, horizontal_dist))

    return az, el


# ----------------------------------------------------------
#  Load / Save Aim Calibration File
# ----------------------------------------------------------
def load_aim_file():
    if os.path.exists(AIM_FILE):
        with open(AIM_FILE, "r") as f:
            return json.load(f)
    return {"calibration": {}, "angles": {}}


def save_aim_file(data):
    with open(AIM_FILE, "w") as f:
        json.dump(data, f, indent=2)


# ----------------------------------------------------------
# Compute angles for all targets + apply calibration
# ----------------------------------------------------------
def compute_all_target_angles(my_team, positions):
    turrets = positions["turrets"]
    globes = positions["globes"]

    my_pos = turrets[my_team]

    aim_data = load_aim_file()
    aim_data.setdefault("angles", {})
    aim_data["angles"].setdefault("turrets", {})
    aim_data["angles"].setdefault("globes", {})

    # ---- Turrets ----
    for tid, tpos in turrets.items():
        if tid == my_team: 
            continue
        az, el = compute_az_el(my_pos, tpos)

        cal_az = aim_data["calibration"].get(f"turret_{tid}_az", 0)
        cal_el = aim_data["calibration"].get(f"turret_{tid}_el", 0)

        aim_data["angles"]["turrets"][tid] = {
            "az": az + cal_az,
            "el": el + cal_el
        }

    # ---- Globes ----
    for i, gpos in enumerate(globes):
        az, el = compute_az_el(my_pos, gpos)

        cal_az = aim_data["calibration"].get(f"globe_{i}_az", 0)
        cal_el = aim_data["calibration"].get(f"globe_{i}_el", 0)

        aim_data["angles"]["globes"][i] = {
            "az": az + cal_az,
            "el": el + cal_el
        }

    save_aim_file(aim_data)
    return aim_data["angles"]



def process_positions():
    turrets = positions["turrets"]          # defining keys for the dict for turrets and globes
    globes = positions["globes"]

    MY_TEAM = "3"  # we are team 3
    my_turret = turrets.get(MY_TEAM)    # pull out our team location
    other_turrets = {t: c for t, c in turrets.items() if t != MY_TEAM}      # pull out the other team locations


    # Print it all out to check if its correct

    print("\n--- YOUR TURRET (Team 3) ---")
    print(my_turret)

    print("\n--- OTHER TEAMS ---")
    for t, c in other_turrets.items():
        print(t, c)

    print("\n--- GLOBES ---")
    for g in globes:
        print(g)

    print("================================\n")

# motor set up function

def setup_motors():
    global s, m_az, m_el

    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)

    # all the following is basically copied from the motor control script, its just setting up the mulitprocessing locks

    s = Shifter(data=DATA_PIN, latch=LATCH_PIN, clock=CLOCK_PIN)

    lock1 = multiprocessing.Lock()
    lock2 = multiprocessing.Lock()

    m_az = Stepper(s, lock1)
    m_el = Stepper(s, lock2)

    m_az.zero()
    m_el.zero()
    print("Motors initialized at 0°.")


# web server set up stuff

def recv_request(conn):
    return conn.recv(8192).decode("utf-8", errors="ignore")

def parse_request_line(req_text):   # parse header request
    first = req_text.split("\r\n", 1)[0]
    parts = first.split()
    return (parts[0], parts[1]) if len(parts) >= 2 else ( "GET", "/" )

def parse_post_body(req_text):      # parse body request, returns the dictionary of posted form fields
    i = req_text.find("\r\n\r\n")
    if i < 0: return {}
    body = req_text[i+4:]
    out = {}
    for pair in body.split("&"):
        if "=" in pair:
            k, v = pair.split("=", 1)
            out[k] = v
    return out

def send_html(conn, html):  # send header as HTML
    conn.sendall((
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: text/html\r\n"
        "Connection: close\r\n\r\n"
    ).encode() + html.encode())

def send_json(conn, obj):   # # send header as json
    conn.sendall((
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: application/json\r\n"
        "Connection: close\r\n\r\n"
    ).encode() + obj.encode())


# html stuff

def page_html():
    return f"""<!doctype html>
<html>
<head><meta charset="utf-8"><title>ENME441 Turret Control</title></head>
<body>
  <h1>IoT Laser Turret</h1>

  <h2>Aim at Target</h2>

  <label>Target Type:</label>
  <select id="target_type">
    <option value="turrets">Turret</option>
    <option value="globes">Globe</option>
  </select>

  <label>Target ID:</label>
  <select id="target_id"></select>

  <button onclick="aimTarget()">Aim</button>

  <h2>Trim Controls (Manual Adjustment)</h2>
  <div>
    Azimuth:
    <button onclick="trim('az', -1)">-1°</button>
    <button onclick="trim('az', +1)">+1°</button>
  </div>

  <div>
    Elevation:
    <button onclick="trim('el', -1)">-1°</button>
    <button onclick="trim('el', +1)">+1°</button>
  </div>

  <button onclick="saveCalibration()">Save as New Calibration</button>

<script>
async function loadTargetIDs() {{
  let type = document.getElementById("target_type").value;
  let response = await fetch('/coords');
  let data = await response.json();

  let sel = document.getElementById("target_id");
  sel.innerHTML = "";

  let items = (type === "turrets") ? Object.keys(data.turrets)
                                   : data.globes.map((x,i)=>i);

  items.forEach(id => {{
    let opt = document.createElement("option");
    opt.value = id;
    opt.text = id;
    sel.add(opt);
  }});
}}

document.getElementById("target_type").onchange = loadTargetIDs;
window.onload = loadTargetIDs;

async function aimTarget() {{
  let type = document.getElementById("target_type").value;
  let id   = document.getElementById("target_id").value;

  await fetch("/aim", {{
    method: "POST",
    headers: {{ "Content-Type": "application/x-www-form-urlencoded" }},
    body: "type="+type+"&id="+id
  }});
}}

async function trim(axis, amount) {{
  await fetch("/trim", {{
    method:"POST",
    headers:{{"Content-Type":"application/x-www-form-urlencoded"}},
    body:"axis="+axis+"&amount="+amount
  }});
}}

async function saveCalibration() {{
  let type = document.getElementById("target_type").value;
  let id   = document.getElementById("target_id").value;

  await fetch("/save_cal", {{
    method:"POST",
    headers:{{"Content-Type":"application/x-www-form-urlencoded"}},
    body:"type="+type+"&id="+id
  }});
}}
</script>

</body>
</html>"""


# web interface response

def handle_post_set(req_text):      # read response from web interface, makes sure correct axis is changed to correct angle
    data = parse_post_body(req_text)
    axis = data.get("axis", "")
    angle = float(data.get("angle", "0"))

    if axis == "az":  m_az.goAngle(angle)
    if axis == "el":  m_el.goAngle(angle)

def handle_post_zero():         # zeros motors
    m_az.zero()
    m_el.zero()


# web server set up

def run_server():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)  # creating socket, AF_INET is IPv4 socket, SOCK_STREAM is TCP
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) # allows quick rebind to address/port
    sock.bind((HOST, PORT))
    sock.listen(5)

    print(f"Serving at http://raspberrypi.local:{PORT}")

    while True:
        conn, addr = sock.accept()  # return socket and client address when someone connects
        req = recv_request(conn)
        method, path = parse_request_line(req)  # find if its a GET or POST request

        if method == "GET":        # get position data
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

    # ---------------------------------------
    # NEW: Aim at target (turret or globe)
    # ---------------------------------------
    elif path == "/aim":
        data = parse_post_body(req)
        target_type = data["type"]      # "turrets" or "globes"
        target_id   = data["id"]        # turret number OR globe index

        aim_data = load_aim_file()["angles"]
        angles = aim_data[target_type][str(target_id)] if target_type == "turrets" else \
                 aim_data[target_type][int(target_id)]

        m_az.goAngle(angles["az"])
        m_el.goAngle(angles["el"])

        send_json(conn, '{"status":"aimed"}')

    # ---------------------------------------
    # NEW: 1° Trim buttons
    # ---------------------------------------
    elif path == "/trim":
        data = parse_post_body(req)
        axis = data["axis"]             # "az" or "el"
        amount = float(data["amount"])  # +1 or -1

        if axis == "az":
            new_angle = m_az.current_angle + amount
            m_az.goAngle(new_angle)
            m_az.current_angle = new_angle

        elif axis == "el":
            new_angle = m_el.current_angle + amount
            m_el.goAngle(new_angle)
            m_el.current_angle = new_angle

        send_json(conn, '{"status":"trimmed"}')

    # ---------------------------------------
    # NEW: Save Calibration
    # ---------------------------------------
    elif path == "/save_cal":
        data = parse_post_body(req)
        t = data["type"]   # "turrets" or "globes"
        i = data["id"]     # id number or index

        aim = load_aim_file()
        stored = aim["angles"][t][i] if t == "turrets" else aim["angles"][t][int(i)]

        # Save final trimmed angles as calibration offsets
        aim["calibration"][f"{t[:-1]}_{i}_az"] = stored["az"]
        aim["calibration"][f"{t[:-1]}_{i}_el"] = stored["el"]

        save_aim_file(aim)

        send_json(conn, '{"status":"saved"}')

conn.close()



# main

if __name__ == "__main__":
    try:
        setup_motors()

        positions = load_positions()
        process_positions() 

        run_server()

    except KeyboardInterrupt:
        print("Shutting down...")

    finally:
        if s:
            s.shiftByte(0)
        GPIO.cleanup()
        print("GPIO cleaned up.")