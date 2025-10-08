import RPi.GPIO as GPIO
import time
import math

GPIO.setmode(GPIO.BCM)
pins = [2,3,4,17,27,22,10,9,11,5]

button_pin = 6
GPIO.setup(button_pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)


initial_f = 500
pwms = []
for pin in pins:
	GPIO.setup(pin, GPIO.OUT)
	pwm = GPIO.PWM(pin, initial_f)
	pwm.start(0)
	pwms.append(pwm)

f= 0.2
phase_step = math.pi/11
direction = 1

def change_direction(button_pin):
	global direction
	direction *= -1
	print("Direction changed")

GPIO.add_event_detect(button_pin, GPIO.RISING, callback=change_direction, bouncetime=300)


try:
	t_0 = time.time()

	while True:
		t = time.time() - t_0

		for i, p in enumerate(pwms):
			phi = direction*i*phase_step
			B = math.sin(2*math.pi*f*t - phi)**2

			Duty_Cycle = B*100
			p.ChangeDutyCycle(Duty_Cycle)

except KeyboardInterrup:
	pass
finally:
	for p in pwms:
		p.stop()
	GPIO.cleanup()

