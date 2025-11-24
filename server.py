# server.py
import time
import threading
from flask import Flask, jsonify, request, send_file
import multiprocessing
import RPi.GPIO as GPIO

# Import your existing Stepper and Shifter code
from stepper_class_shiftregister_multiprocessing import Stepper
from shifter import Shifter  # should be your module that controls the shift register

# --- Config ---
AZIMUTH_STEPPER_INDEX = 0   # we will instantiate az then el so index 0 = azimuth
ELEVATION_STEPPER_INDEX = 1

# Use the same pins you used before for the shifter
SHIFTER_DATA_PIN = 16
SHIFTER_LATCH_PIN = 20
SHIFTER_CLOCK_PIN = 21

# (Optional) if you want to control a laser later, configure a pin here.
# For now we will not toggle the laser automatically to keep things simple/safe.
LASER_GPIO_PIN = None

# --- Setup ---
app = Flask(__name__)

# Initialize hardware
s = Shifter(data=SHIFTER_DATA_PIN, latch=SHIFTER_LATCH_PIN, clock=SHIFTER_CLOCK_PIN)

# Use one multiprocessing.Lock for each motor as in your class
lock_az = multiprocessing.Lock()
lock_el = multiprocessing.Lock()

# Instantiate two Steppers in the correct order (first Az then El)
az_stepper = Stepper(s, lock_az)
el_stepper = Stepper(s, lock_el)

# Zero on startup (logical zero for calibration)
az_stepper.zero()
el_stepper.zero()


# --- Helper functions ---
def get_angles():
    with az_stepper.angle.get_lock():
        az = az_stepper.angle.value
    with el_stepper.angle.get_lock():
        el = el_stepper.angle.value
    return float(az), float(el)

def relative_move(axis, delta_deg):
    if axis == 'az':
        az_stepper.rotate(float(delta_deg))
    elif axis == 'el':
        el_stepper.rotate(float(delta_deg))
    else:
        raise ValueError("bad axis")

def absolute_move(axis, angle_deg):
    if axis == 'az':
        az_stepper.goAngle(float(angle_deg))
    elif axis == 'el':
        el_stepper.goAngle(float(angle_deg))
    else:
        raise ValueError("bad axis")


# --- REST API ---
@app.route('/')
def index():
    return send_file('control_page.html')

@app.route('/api/angles', methods=['GET'])
def api_angles():
    az, el = get_angles()
    return jsonify({"ok": True, "az": az, "el": el})

@app.route('/api/move', methods=['POST'])
def api_move():
    """
    JSON: {"axis":"az"|"el", "delta": <degrees>}
    Example: {"axis":"az", "delta": 5}
    """
    data = request.get_json(force=True)
    axis = data.get('axis')
    delta = float(data.get('delta', 0.0))
    try:
        relative_move(axis, delta)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400

@app.route('/api/go', methods=['POST'])
def api_go():
    """
    JSON: {"axis":"az"|"el", "angle": <degrees>}
    """
    data = request.get_json(force=True)
    axis = data.get('axis')
    angle = float(data.get('angle', 0.0))
    try:
        absolute_move(axis, angle)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400

@app.route('/api/set_zero', methods=['POST'])
def api_set_zero():
    """
    JSON: {"axis":"az"|"el"}
    Sets the current position as zero for that axis (in-memory).
    """
    data = request.get_json(force=True)
    axis = data.get('axis')
    if axis == 'az':
        az_stepper.zero()
    elif axis == 'el':
        el_stepper.zero()
    else:
        return jsonify({"ok": False, "error": "bad axis"}), 400
    return jsonify({"ok": True})

# Serve the field image you uploaded for convenience (optional)
@app.route('/static/field_diagram')
def field_diagram():
    # local path from your upload (provided earlier)
    return send_file('/mnt/data/504aa1b2-e1f5-4d32-a3e6-d773904686aa.png')

# --- Run server ---
if __name__ == '__main__':
    try:
        # Run on all interfaces so other devices on WiFi can reach it
        app.run(host='0.0.0.0', port=5000, debug=False)
    except KeyboardInterrupt:
        pass
    finally:
        # cleanup: stop outputs and cleanup GPIO
        try:
            s.shiftByte(0)
        except Exception:
            pass
        GPIO.cleanup()
