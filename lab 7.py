#!/usr/bin/env python3
import cgi
import cgitb
import RPi.GPIO as GPIO
import os

cgitb.enable()  # Enable detailed error messages in browser

# ---------- GPIO SETUP ----------
GPIO.setmode(GPIO.BCM)

# Define which GPIO pins the LEDs are connected to
led_pins = [17, 27, 22]  # LED 1, LED 2, LED 3

# Set up PWM on each LED pin
pwms = []
for pin in led_pins:
    GPIO.setup(pin, GPIO.OUT)
    pwm = GPIO.PWM(pin, 1000)  # 1 kHz frequency
    pwm.start(0)
    pwms.append(pwm)

# ---------- LOAD PREVIOUS BRIGHTNESS VALUES ----------
brightness_file = "/tmp/led_brightness.txt"

if os.path.exists(brightness_file):
    with open(brightness_file, "r") as f:
        try:
            led_brightness = [int(x) for x in f.read().split()]
        except ValueError:
            led_brightness = [0, 0, 0]
else:
    led_brightness = [0, 0, 0]
    print("program started")

# ---------- HANDLE FORM SUBMISSION ----------
form = cgi.FieldStorage()
if "led" in form and "brightness" in form:
    led_index = int(form["led"].value) - 1
    brightness = int(form["brightness"].value)

    # Clamp brightness between 0–100 just in case
    brightness = max(0, min(100, brightness))

    # Update stored brightness and apply it to the correct LED
    led_brightness[led_index] = brightness
    pwms[led_index].ChangeDutyCycle(brightness)

    # Save updated values to file
    with open(brightness_file, "w") as f:
        f.write(" ".join(map(str, led_brightness)))

# ---------- GENERATE HTML RESPONSE ----------
print("Content-type: text/html\n")
print(f"""
<html>
<head>
<title>LED Brightness Control</title>
<style>
  body {{
    font-family: Arial, sans-serif;
  }}
  .control-box {{
    border: 1px solid #ccc;
    width: 220px;
    padding: 10px;
    border-radius: 8px;
  }}
  input[type=range] {{
    width: 100%;
  }}
</style>
</head>
<body>
<div class="control-box">
  <form method="POST" action="/cgi-bin/led_control.py">
    <label for="brightness"><b>Brightness level:</b></label><br>
    <input type="range" id="brightness" name="brightness" min="0" max="100" value="0"><br><br>

    <b>Select LED:</b><br>
    <input type="radio" name="led" value="1" checked> LED 1 ({led_brightness[0]}%)<br>
    <input type="radio" name="led" value="2"> LED 2 ({led_brightness[1]}%)<br>
    <input type="radio" name="led" value="3"> LED 3 ({led_brightness[2]}%)<br><br>

    <input type="submit" value="Change Brightness">
  </form>
</div>
</body>
</html>
""")
