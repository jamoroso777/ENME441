import RPi.GPIO as GPIO
import time
from bug_class import Bug  # import the Bug class from previous step

# --- Pin assignments for switches ---
s1, s2, s3 = 17, 27, 22   # example GPIO pin numbers for your 3 switches

# --- Setup GPIO ---
GPIO.setmode(GPIO.BCM)
GPIO.setup(s1, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
GPIO.setup(s2, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
GPIO.setup(s3, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)

# --- Instantiate Bug object (defaults: timestep=0.1, x=3, isWrapOn=False) ---
bug = Bug()

# --- Track previous state of s2 for edge detection ---
s2_prev = GPIO.input(s2)
bug_running = False

print("🐞 Bug system initialized.")
print("Controls:")
print("  S1 → Start/Stop Bug")
print("  S2 → Toggle Wrap Mode")
print("  S3 → 3x Speed Boost\n")

try:
    while True:
        # --- Read switch states ---
        s1_state = GPIO.input(s1)
        s2_state = GPIO.input(s2)
        s3_state = GPIO.input(s3)

        # --- (a) S1 controls ON/OFF ---
        if s1_state and not bug_running:
            print("[S1] Bug started.")
            bug.start()
            bug_running = True

        elif not s1_state and bug_running:
            print("[S1] Bug stopped.")
            bug.stop()
            bug_running = False

        # --- (b) S2 toggles wrap mode when it changes state ---
        if s2_state != s2_prev:
            bug.isWrapOn = not bug.isWrapOn
            print(f"[S2] Wrap mode toggled → {bug.isWrapOn}")
        s2_prev = s2_state

        # --- (c) S3 controls 3x speed boost ---
        if s3_state:
            if abs(bug.timestep - 0.033) > 1e-3:
                bug.timestep = 0.1 / 3
                print("[S3] Speed boost activated (3× faster).")
        else:
            if abs(bug.timestep - 0.1) > 1e-3:
                bug.timestep = 0.1
                print("[S3] Speed boost deactivated (normal speed).")

        # --- Debugging output of current Bug state ---
        if bug_running:
            print(f"LED position: {bug.x} | Wrap: {bug.isWrapOn} | Timestep: {bug.timestep:.3f}s")

        time.sleep(0.2)

except KeyboardInterrupt:
    print("\nKeyboardInterrupt detected. Cleaning up GPIO...")
    bug.stop()
    GPIO.cleanup()
    print("GPIO cleanup complete. Program terminated.")
