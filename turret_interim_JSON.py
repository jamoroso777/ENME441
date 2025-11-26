# turret_interim.py
#
# Interim turret control:
#  - Simple web page with two sliders (pan & tilt) -> PWM duty cycles
#  - Also fetches positions.json from the router and shows r, theta
#
# Uses: socket, RPi.GPIO PWM, urllib.request, json
#

import socket
import json
import urllib.request
import RPi.GPIO as GPIO

# -------------------- USER SETTINGS --------------------

# PWM pins for pan/tilt servos (BCM numbers)
PAN_PIN  = 18      # change if your hardware uses different pins
TILT_PIN = 13

PWM_FREQ = 50      # typical for hobby servos

# URL for positions.json on the router  <<< CHANGE THIS TO MATCH YOUR LAB
POS_URL = "http://192.168.1.254:8000/positions.json"

# Your team ID as a string (key in the JSON file)  <<< CHANGE TO YOUR TEAM
TEAM_ID = "3"

# -------------------- GPIO / PWM SETUP --------------------

GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)

GPIO.setup(PAN_PIN, GPIO.OUT)
GPIO.setup(TILT_PIN, GPIO.OUT)

pan_pwm  = GPIO.PWM(PAN_PIN, PWM_FREQ)
tilt_pwm = GPIO.PWM(TILT_PIN, PWM_FREQ)

# start at 0% duty (you can change if needed)
pan_pwm.start(0)
tilt_pwm.start(0)

# store current duty cycles so we can show them on the page
pan_level  = 0
tilt_level = 0

# store last r, theta we got from positions.json
last_r = None
last_theta = None

# -------------------- HELPER FUNCTIONS --------------------

def set_pan(level):
    """Set pan PWM duty cycle (0–100)."""
    global pan_level
    level = max(0, min(100, int(level)))
    pan_level = level
    pan_pwm.ChangeDutyCycle(level)

def set_tilt(level):
    """Set tilt PWM duty cycle (0–100)."""
    global tilt_level
    level = max(0, min(100, int(level)))
    tilt_level = level
    tilt_pwm.ChangeDutyCycle(level)

def recv_request(conn):
    """Read a small HTTP request and return it as text."""
    return conn.recv(4096).decode("utf-8", errors="ignore")

def parse_request_line(req_text):
    """Return (method, path) from first line of HTTP request."""
    first = req_text.split("\r\n", 1)[0]
    parts = first.split()
    if len(parts) >= 2:
        return parts[0], parts[1]
    return "GET", "/"

def parse_post_body(req_text):
    """Parse URL-encoded POST body into a dict."""
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
    conn.send(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\n\r\n")
    conn.sendall(html.encode("utf-8"))

def fetch_position():
    """
    Fetch positions.json, extract this team's r, theta.
    Updates last_r, last_theta and prints them.
    """
    global last_r, last_theta

    try:
        with urllib.request.urlopen(POS_URL, timeout=1.0) as resp:
            text = resp.read().decode("utf-8")
        data = json.loads(text)

        # Many labs use {"teams": {"7": {"r": ..., "theta": ...}, ...}}
        if "teams" in data:
            data = data["teams"]

        # access by team id
        entry = None
        if isinstance(data, dict):
            # team key might be "7" or 7 depending on server
            if TEAM_ID in data:
                entry = data[TEAM_ID]
            elif TEAM_ID.isdigit() and int(TEAM_ID) in data:
                entry = data[int(TEAM_ID)]

        if isinstance(entry, dict):
            # try a few common key names
            r_val = entry.get("r", entry.get("R", 0.0))
            t_val = entry.get("theta", entry.get("theta_deg", 0.0))

            last_r = float(r_val)
            last_theta = float(t_val)
            print(f"positions.json -> team {TEAM_ID}: r = {last_r}, theta = {last_theta}")
        else:
            print("Team ID not found in positions.json")

    except Exception as e:
        print("Error fetching positions.json:", e)

# -------------------- HTML PAGE --------------------

def main_page():
    """Return the HTML for the slider UI + current turret JSON position."""
    if last_r is None or last_theta is None:
        pos_text = "unknown (no JSON yet)"
    else:
        pos_text = f"r = {last_r:.2f}, θ = {last_theta:.1f}°"

    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Turret Interim Control</title>
  <style>
    body {{
      font-family: system-ui, sans-serif;
      max-width: 520px;
      margin: 2rem;
    }}
    h2, h3 {{ margin-bottom: 0.3rem; }}
    .row {{
      display: flex;
      align-items: center;
      gap: 10px;
      margin: 10px 0;
    }}
    .name {{ width: 3rem; }}
    .val  {{ width: 3rem; text-align: right; }}
    input[type=range] {{ width: 260px; }}
    .pos-box {{
      padding: 0.5rem 0.8rem;
      border: 1px solid #ccc;
      border-radius: 6px;
      background: #f9f9f9;
      margin-top: 1rem;
    }}
  </style>
</head>
<body>
  <h2>Turret PWM Control (Interim)</h2>

  <form action="/" method="POST">
    <div class="row">
      <div class="name">Pan</div>
      <input type="range" name="pan" min="0" max="100" value="{pan_level}">
      <div class="val">{pan_level}%</div>
    </div>

    <div class="row">
      <div class="name">Tilt</div>
      <input type="range" name="tilt" min="0" max="100" value="{tilt_level}">
      <div class="val">{tilt_level}%</div>
    </div>

    <p><input type="submit" value="Update PWM"></p>
  </form>

  <div class="pos-box">
    <h3>Server Turret Position (from positions.json)</h3>
    <p>Team ID: <b>{TEAM_ID}</b></p>
    <p>{pos_text}</p>
    <p><small>Reload the page or move a slider to refresh.</small></p>
  </div>
</body>
</html>
"""

# -------------------- SERVER LOOP --------------------

def run(host="", port=8080):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((host, port))
    s.listen(3)

    print(f"Serving http://{host or 'raspberrypi.local'}:{port}")

    try:
        while True:
            conn, addr = s.accept()
            try:
                req = recv_request(conn)
                method, path = parse_request_line(req)

                # Always try to refresh JSON data once per request
                fetch_position()

                if method == "POST":
                    data = parse_post_body(req)
                    # update PWM if fields present
                    if "pan" in data:
                        try:
                            set_pan(data["pan"])
                        except ValueError:
                            pass
                    if "tilt" in data:
                        try:
                            set_tilt(data["tilt"])
                        except ValueError:
                            pass

                # For both GET and POST, send the same page
                send_html(conn, main_page())

            finally:
                conn.close()
    finally:
        s.close()

# -------------------- MAIN --------------------

if __name__ == "__main__":
    try:
        run("", 8080)
    except KeyboardInterrupt:
        print("\nExiting.")
    finally:
        pan_pwm.stop()
        tilt_pwm.stop()
        GPIO.cleanup()