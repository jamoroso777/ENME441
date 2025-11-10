# Shift register class

from RPi import GPIO
from time import sleep

GPIO.setmode(GPIO.BCM)

class Shifter():

    def __init__(self, data, clock, latch):
        self.dataPin = data
        self.latchPin = latch
        self.clockPin = clock
        GPIO.setup(self.dataPin, GPIO.OUT)
        GPIO.setup(self.latchPin, GPIO.OUT)
        GPIO.setup(self.clockPin, GPIO.OUT)

    def ping(self, p):  # ping the clock or latch pin
        GPIO.output(p,1)
        sleep(0)
        GPIO.output(p,0)

    # Shift all bits in an arbitrary-length word, allowing
    # multiple 8-bit shift registers to be chained (with overflow
    # of SR_n tied to input of SR_n+1):
    def shiftWord(self, dataword, num_bits):
        for i in range((num_bits+1) % 8):  # Load bits short of a byte with 0
            # self.dataPin.value(0)  # MicroPython for ESP32
            GPIO.output(self.dataPin, 0) 
            self.ping(self.clockPin)
        for i in range(num_bits):          # Send the word
            # self.dataPin.value(dataword & (1<<i))  # MicroPython for ESP32
            GPIO.output(self.dataPin, dataword & (1<<i))
            self.ping(self.clockPin)
        self.ping(self.latchPin)

    # Shift all bits in a single byte:
    def shiftByte(self, databyte):
        self.shiftWord(databyte, 8)


# Example:
#
# from time import sleep
# s = Shifter(data=16,clock=20,latch=21)   # convenient Pi pins
# for i in range(256):
#     s.shiftByte(i)
#     sleep(0.1)
