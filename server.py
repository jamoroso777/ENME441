import socket
from urllib.parse import unquote_plus
from stepper_class_shiftregister_multiprocessing import Stepper
from shifter import Shifter
import multiprocessing
import RPi.GPIO as GPIO


# ---------------------------------------------------------
# Helper: Parse POST data from request
# ---------------------------------------------------------
def parsePOSTdata(request):
    try:
        header, body = request.split("\r\n\r\n", 1)
        params = {}
        for pair in body.split("&"):
            if "=" in pair:
                k, v = pair.split("=", 1)
                params[k] = unquote_plus(v)
        return params
    except:
        return {}


# ---------------------------------------------------------
# HTML page for the control UI
# ---------------------------------------------------------
def html_page(az, el):
    return f"""
<html>
<head>
<title>Laser Turret Control</title>
<style>
button {{
  margin: 8px; padding: 10px 20px;
}}
</style>
</head>
<body>
<h2>Laser Turret Control</h2>

<h3>Azimuth</h3>
<form method="POST">
  <button name="axis" value="az">Az</button>
  <input type="hidden" name="delta" value="-5">
  <button type="submit">◀ -5°</button>
</form>
<form method="POST">
  <input type="hidden" name="axis" value="az">
  <input type="hidden" name="delta" value="5">
  <button type="submit">+5° ▶</button>
</form>

<h3>Elevation</h3>
<form method="POST">
  <input type="hidden" name="axis" value="el">
  <input type="hidden" name="delta" value="-5">
  <button type="submit">▼ -5°</button>
</form>
<form method="POST">
  <input type="hidden" name="axis" value="el">
  <input type="hidden" name="delta" value="5">
  <button type="submit">▲ +5°</button>
</form>

<h3>Current Angles</h3>
<p>Azimuth: {az:.2f}°<br>Elevation: {el:.2f}°</p>

</body>
</html>
"""


# ---------------------------------------------------------
# Setup motors
# ---------------------------------------------------------
# Using same shift register pins you told me earlier
SHIFTER_DATA_PIN = 16
SHIFTER_LATCH_PIN = 20
SHIFTER_CLOCK_PIN = 21

s = Shifter(data=SHIFTER_DATA_PIN, latch=SHIFTER_LATCH_PIN, clock=SHIFTER_CLOCK_PIN)

lock_az = multiprocessing.Lock()
lock_el = multiprocessing.Lock()

# Instantiation order defines motor index
az_stepper = Stepper(s, lock_az)   # motor 0
el_stepper = Stepper(s, lock_el)   # motor 1

az_stepper.zero()
el_stepper.zero()


# ---------------------------------------------------------
# Server loop
# ---------------------------------------------------------
def run_server():
    host, port = "", 8080
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind((host, port))
    srv.listen(1)

    print(f"Motor Control Server running on port {port}...")
    print("Open: http://<your-pi-ip>:8080")

    while True:
        conn, addr = srv.accept()
        request = conn.recv(4096).decode("utf-8")
        print(f"\nRequest from {addr}")
        print(request)

        if "POST" in request:
            data = parsePOSTdata(request)
            print("Parsed POST:", data)

            try:
                axis = data.get("axis")
                delta = float(data.get("delta", 0))

                if axis == "az":
                    az_stepper.rotate(delta)
                elif axis == "el":
                    el_stepper.rotate(delta)

            except Exception as e:
                print("Error:", e)

        # Read angles
        with az_stepper.angle.get_lock():
            az = az_stepper.angle.value
        with el_stepper.angle.get_lock():
            el = el_stepper.angle.value

        # Build page
        page = html_page(az, el)
        response = (
            "HTTP/1.1 200 OK\r\n"
            "Content-Type: text/html\r\n"
            f"Content-Length: {len(page)}\r\n"
            "Connection: close\r\n\r\n"
            + page
        )

        conn.sendall(response.encode("utf-8"))
        conn.close()


# ---------------------------------------------------------
# Main
# ---------------------------------------------------------
if __name__ == "__main__":
    try:
        run_server()
    except KeyboardInterrupt:
        print("Stopping server...")
    finally:
        try:
            s.shiftByte(0)
        except:
            pass
        GPIO.cleanup()
