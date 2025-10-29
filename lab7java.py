#!/usr/bin/env python3
import RPi.GPIO as GPIO
from http.server import BaseHTTPRequestHandler, HTTPServer
import urllib.parse
import json

GPIO.setmode(GPIO.BCM)

# Define LED pins
led_pins = [17, 27, 22]
for pin in led_pins:
    GPIO.setup(pin, GPIO.OUT)
    GPIO.output(pin, GPIO.LOW)

# Create PWM objects (1kHz)
pwms = [GPIO.PWM(pin, 1000) for pin in led_pins]
for pwm in pwms:
    pwm.start(0)

# Track brightness for each LED
led_brightness = [0, 0, 0]


class LEDHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        """Serve the main HTML+JavaScript page"""
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(self.html_page().encode("utf-8"))

    def do_POST(self):
        """Handle AJAX POST updates"""
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length).decode("utf-8")
        data = urllib.parse.parse_qs(post_data)

        # Extract LED and brightness
        led_index = int(data.get("led", [0])[0])
        brightness = int(data.get("brightness", [0])[0])

        # Update state and PWM
        led_brightness[led_index] = brightness
        pwms[led_index].ChangeDutyCycle(brightness)

        # Respond with JSON (no reload)
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        response = {"led_brightness": led_brightness}
        self.wfile.write(json.dumps(response).encode("utf-8"))

    def html_page(self):
        """Return the full HTML + JavaScript UI"""
        return f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>LED Brightness Control</title>
<style>
  body {{
    font-family: Arial, sans-serif;
    margin: 40px;
  }}
  .led-control {{
    margin-bottom: 20px;
  }}
  input[type=range] {{
    width: 300px;
  }}
  h2 {{
    color: #333;
  }}
</style>
<script>
function updateLED(led, value) {{
  // Display new percentage next to slider
  document.getElementById("val" + led).innerText = value + "%";

  // Send POST request to server
  fetch("/", {{
    method: "POST",
    headers: {{
      "Content-Type": "application/x-www-form-urlencoded"
    }},
    body: "led=" + led + "&brightness=" + value
  }})
  .then(response => response.json())
  .then(data => {{
    // Update labels to reflect new brightness values
    for (let i = 0; i < 3; i++) {{
      document.getElementById("val" + i).innerText = data.led_brightness[i] + "%";
      document.getElementById("slider" + i).value = data.led_brightness[i];
    }}
  }})
  .catch(err => console.error("Error:", err));
}}
</script>
</head>

<body>
  <h2>Live LED Brightness Control</h2>
  <p>Adjust each slider to change the brightness of an LED instantly.</p>

  <div class="led-control">
    <label>LED 1: </label>
    <input type="range" id="slider0" min="0" max="100" value="{led_brightness[0]}"
           oninput="updateLED(0, this.value)">
    <span id="val0">{led_brightness[0]}%</span>
  </div>

  <div class="led-control">
    <label>LED 2: </label>
    <input type="range" id="slider1" min="0" max="100" value="{led_brightness[1]}"
           oninput="updateLED(1, this.value)">
    <span id="val1">{led_brightness[1]}%</span>
  </div>

  <div class="led-control">
    <label>LED 3: </label>
    <input type="range" id="slider2" min="0" max="100" value="{led_brightness[2]}"
           oninput="updateLED(2, this.value)">
    <span id="val2">{led_brightness[2]}%</span>
  </div>
</body>
</html>
"""


# Run the server
try:
    print("Starting LED control server on http://0.0.0.0:8080 ...")
    with HTTPServer(('', 8080), LEDHandler) as server:
        server.serve_forever()
except KeyboardInterrupt:
    pass
finally:
    for pwm in pwms:
        pwm.stop()
    GPIO.cleanup()
    print("Server stopped, GPIO cleaned up.")
