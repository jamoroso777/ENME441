import RPi.GPIO as GPIO
import time
from bug_class import Bug  

switch_pins = [17, 27, 22]

GPIO.setmode(GPIO.BCM)
for pin in switch_pins:
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)

bug = Bug()

s2_prev = GPIO.input(27)
bug_running = False

print("Bug started")
print("Controls:")
print("Yellow Wire --> Start/stop Bug")
print(" Black Wire --> Toggle wrap mode")
print(" White Wire --> 3x speed boost\n")

try:
    while True:
        s1_state = GPIO.input(17)
        s2_state = GPIO.input(27)
        s3_state = GPIO.input(22)

       #start/stop control
        if s1_state and not bug_running:
            print("Bug started.")
            bug.start()
            bug_running = True

        elif not s1_state and bug_running:
            print("Bug stopped.")
            bug.stop()
            bug_running = False

        #wrap mode control
        if s2_state != s2_prev:
            bug.isWrapOn = not bug.isWrapOn
            print(f"Wrap mode toggled: {bug.isWrapOn}")
        s2_prev = s2_state

        #speed boost control
        if s3_state:
            if abs(bug.timestep - 0.033) > 1e-3:
                bug.timestep = 0.1 / 3
                print("3x Speed boost activated")
        else:
            if abs(bug.timestep - 0.1) > 1e-3:
                bug.timestep = 0.1
                print("Speed boost deactivated")

        time.sleep(0.2)

except KeyboardInterrupt:
    print("\nKeyboardInterrupt. Cleaning GPIO...")
    bug.stop()
    GPIO.cleanup()
    print("complete")