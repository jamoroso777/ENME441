import time
import random
import threading
import RPi.GPIO as GPIO
from shifter import Shifter

serialPin, latchPin, clockPin = 23, 24, 25

led = Shifter(serialPin, clockPin, latchPin)

position = 3
pattern = 1<<position

try:
	while True:
		led.shiftByte(pattern)
		time.sleep(0.05)

		step = random.choice([-1,1])
		position += step

		position = max(0, min(7,position))

		patern = 1<<position

except KeyboardInterrupt:
	GPIO.cleanup()