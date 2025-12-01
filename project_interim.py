import socket
import time
import multiprocessing
import json
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

USE_LOCAL_JSON = False          # local json for testing
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

        elif method == "POST":     # get zeroed status
            if path == "/set":
                handle_post_set(req)
                send_json(conn, '{"status":"ok"}')
            elif path == "/zero":
                handle_post_zero()
                send_json(conn, '{"status":"zeroed"}')

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
