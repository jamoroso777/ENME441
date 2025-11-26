# turret_interim.py
#
# Interim checkpoint:
# - Control two stepper axes (azimuth, elevation) from a web page.
# - Uses socket-based HTTP like Lab 7.

import socket
import time
import multiprocessing
import RPi.GPIO as GPIO

from shifter import Shifter
from stepper_class_shiftregister_multiprocessing import Stepper

# ----------------- CONFIG -----------------
# Shift register pins (BCM)
DATA_PIN  = 16
LATCH_PIN = 20
CLOCK_PIN = 21

# Angle limits for UI sliders (deg)
AZ_MIN = -180
AZ_MAX =  180
EL_MIN = -90
EL_MAX =  90

HOST = ""       # listen on all interfaces
PORT = 8080
# ------------------------------------------


# Globals for motors
s = None
m_az = None   # azimuth motor
m_el = None   # elevation motor


def setup_motors():
    """Set up GPIO, shift register, and stepper motors."""
    global s, m_az, m_el

    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)

    # One shared shifter for both motors (like Lab 8)
    s = Shifter(data=DATA_PIN, latch=LATCH_PIN, clock=CLOCK_PIN)

    # Each motor gets its own lock
    lock1 = multiprocessing.Lock()
    lock2 = multiprocessing.Lock()

    # Motor 1 = azimuth, Motor 2 = elevation
    m_az = Stepper(s, lock1)
    m_el = Stepper(s, lock2)

    # Set current positions to 0°
    m_az.zero()
    m_el.zero()
    print("Motors initialized (azimuth and elevation at 0°).")


# ---------- Tiny HTTP helpers (Lab-7 style) ----------

def recv_request(conn):
    return conn.recv(8192).decode("utf-8", errors="ignore")

def parse_request_line(req_text):
    first = req_text.split("\r\n", 1)[0]
    parts = first.split()
    if len(parts) >= 2:
        return parts[0], parts[1]  # method, path
    return "GET", "/"

def parse_post_body(req_text):
    i = req_text.find("\r\n\r\n")
    if i < 0:
        return {}
    body = req_text[i+4:]
    out = {}
    for pair in body.split("&"):
        if "=" in pair:
            k, v = pair.split("=", 1)
            out[k] = v
    return out

def send_html(conn, html):
    header = (
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: text/html\r\n"
        "Connection: close\r\n\r\n"
    )
    conn.sendall(header.encode("utf-8") + html.encode("utf-8"))

def send_json(conn, obj_str):
    header = (
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: application/json\r\n"
        "Connection: close\r\n\r\n"
    )
    conn.sendall(header.encode("utf-8") + obj_str.encode("utf-8"))

# -------------- Web page (HTML + JS) --------------

def page_html():
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>ENME441 Turret Control</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 2rem; }}
    h2   {{ margin-top: 1.5rem; }}
    .row {{ display:flex; align-items:center; gap:12px; margin: 0.75rem 0; }}
    .label {{ width: 5rem; }}
    .val   {{ width: 4rem; text-align:right; }}
    input[type=range] {{ width: 280px; }}
  </style>
</head>
<body>
  <h1>IoT Laser Turret – Interim Control</h1>

  <h2>Manual control</h2>

  <div class="row">
    <div class="label">Azimuth</div>
    <input id="az" type="range" min="{AZ_MIN}" max="{AZ_MAX}" value="0">
    <div class="val"><span id="az_val">0</span>&deg;</div>
  </div>

  <div class="row">
    <div class="label">Elevation</div>
    <input id="el" type="range" min="{EL_MIN}" max="{EL_MAX}" value="0">
    <div class="val"><span id="el_val">0</span>&deg;</div>
  </div>

  <button onclick="zeroAll()">Zero motors</button>

  <script>
    async function sendAngle(axis, angle) {{
      const body = "axis=" + axis + "&angle=" + angle;
      try {{
        await fetch("/set", {{
          method: "POST",
          headers: {{ "Content-Type": "application/x-www-form-urlencoded" }},
          body: body
        }});
      }} catch (e) {{
        console.log("Request error:", e);
      }}
    }}

    function attachSlider(id, spanId, axisName) {{
      const slider = document.getElementById(id);
      const label  = document.getElementById(spanId);
      slider.addEventListener("input", (e) => {{
        const val = e.target.value;
        label.textContent = val;
        sendAngle(axisName, val);
      }});
    }}

    attachSlider("az", "az_val", "az");
    attachSlider("el", "el_val", "el");

    async function zeroAll() {{
      try {{
        await fetch("/zero", {{ method: "POST" }});
        document.getElementById("az").value = 0;
        document.getElementById("el").value = 0;
        document.getElementById("az_val").textContent = 0;
        document.getElementById("el_val").textContent = 0;
      }} catch (e) {{
        console.log("Zero error:", e);
      }}
    }}
  </script>
</body>
</html>"""


# -------------- Request handling --------------

def handle_post_set(req_text):
    """Handle POST /set: axis=az|el  angle=<deg>"""
    data = parse_post_body(req_text)
    axis  = data.get("axis", "")
    angle_str = data.get("angle", "0")

    try:
        angle = float(angle_str)
    except ValueError:
        angle = 0.0

    if axis == "az" and m_az is not None:
        m_az.goAngle(angle)
    elif axis == "el" and m_el is not None:
        m_el.goAngle(angle)

def handle_post_zero():
    """Zero both motors."""
    if m_az is not None:
        m_az.zero()
    if m_el is not None:
        m_el.zero()


# -------------- Main server loop --------------

def run_server():
    s_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s_sock.bind((HOST, PORT))
    s_sock.listen(5)

    print(f"Serving on http://{HOST or 'raspberrypi.local'}:{PORT}")
    print("Move sliders in your browser to command the turret.")
    try:
        while True:
            conn, addr = s_sock.accept()
            try:
                req = recv_request(conn)
                method, path = parse_request_line(req)

                if method == "GET":
                    # only serve main page at "/"
                    send_html(conn, page_html())

                elif method == "POST":
                    if path == "/set":
                        handle_post_set(req)
                        send_json(conn, '{{"status":"ok"}}')
                    elif path == "/zero":
                        handle_post_zero()
                        send_json(conn, '{{"status":"zeroed"}}')
                    else:
                        send_json(conn, '{{"status":"unknown"}}')
                else:
                    send_html(conn, "<h1>Unsupported method</h1>")
            finally:
                conn.close()
    finally:
        s_sock.close()


# -------------- Entry point --------------

if __name__ == "__main__":
    try:
        setup_motors()
        run_server()
    except KeyboardInterrupt:
        print("\nStopping server...")
    finally:
        # Release everything cleanly
        if s is not None:
            s.shiftByte(0)  # turn off coils
        time.sleep(0.1)
        GPIO.cleanup()
        print("GPIO cleaned up.")