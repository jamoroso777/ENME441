#!/usr/bin/env python3
import RPi.GPIO as GPIO
from http.server import BaseHTTPRequestHandler, HTTPServer
import urllib.parse

GPIO.setmode(GPIO.BCM)

# Define LED pins
led_pins = [17, 27, 22]
for pin in led_pins:
    GPIO.setup(pin, GPIO.OUT)
    GPIO.output(pin, GPIO.LOW)

# Create PWM objects for each LED (1kHz frequency)
pwms = [GPIO.PWM(pin, 1000) for pin in led_pins]
for pwm in pwms:
    pwm.start(0)

# Track brightness levels
led_brightness = [0, 0, 0]

class LEDHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(self.html_page().encode("utf-8"))

    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length).decode("utf-8")
        data = urllib.parse.parse_qs(post_data)

        # Get LED and brightness
        led = int(data.get("led", [1])[0]) - 1
        brightness = int(data.get("brightness", [0])[0])
        led_brightness[led] = brightness

        pwms[led].ChangeDutyCycle(brightness)

        # Refresh page
        self.send_response(303)
        self.send_header('Location', '/')
        self.end_headers()

    def html_page(self):
        html = f"""<html><head><title>LED Brightness Control</title></head>
        <body style="font-family:Arial;">
        <h2>LED Brightness Control</h2>
        <form method="POST" action="/">
        <label>Brightness level:</label><br>
        <input type="range" name="brightness" min="0" max="100" value="0"><br><br>

        <b>Select LED:</b><br>
        <input type="radio" name="led" value="1" checked> LED 1 ({led_brightness[0]}%)<br>
        <input type="radio" name="led" value="2"> LED 2 ({led_brightness[1]}%)<br>
        <input type="radio" name="led" value="3"> LED 3 ({led_brightness[2]}%)<br><br>

        <input type="submit" value="Change Brightness">
        </form>
        </body></html>"""
        return html

# Run the server
try:
    print("Starting web server on http://0.0.0.0:8080 ...")
    with HTTPServer(('', 8080), LEDHandler) as server:
        server.serve_forever()
except KeyboardInterrupt:
    pass
finally:
    for pwm in pwms:
        pwm.stop()
    GPIO.cleanup()
    print("Server stopped, GPIO cleaned up.")
