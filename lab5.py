import RPi.GPIO as GPIO
import time
import math

GPIO.setmode(GPIO.BCM)
pins = [2,3,4,17,27,22,10,9,11,5]


initial_f = 500
pwms = []
for pin in pins:
	GPIO.setup(pin, GPIO.OUT)
	p = GPIO.pwm(pin, initial_f)
	p.start(0)
	pwms.append(p)

f= 0.2
phase_step = math.pi/11

try:
	t_0 = time.time()

	while True:
		t = time.time() - t_0

		for i, p in enumerate(pwms):
			phi = i*phase_step
			B = math.sin(2*math.pi*f*t - phi)**2

			Duty_Cycle = B*100
			p.ChangeDutyCycle(Duty_Cycle)

except KeyboardInterrup:
	pass
finally:
	for p in pwms:
		p.stop()
		GPIO.cleanup()

