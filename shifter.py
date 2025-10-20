import RPi.GPIO as GPIO
import time

class Shifter:
  def __init__(self, serialPin, clockPin, latchPin):
    self.serialPin = serialPin
    self.clockPin = clockPin
    self.latchPin = latchPin


    GPIO.setmode(GPIO.BCM)
    GPIO.setup(serialPin, GPIO.OUT)
    GPIO.setup(latchPin, GPIO.OUT, initial=0)  
    GPIO.setup(clockPin, GPIO.OUT, initial=0)  

  def ping(self, pin):
    GPIO.output(pin, 1)
    time.sleep(0)
    GPIO.output(pin, 0)

  def shiftByte(self, b):
    for i in range(8):
      GPIO.output(self.serialPin, b & (1<<i))
      self.ping(self.clockPin)
    self.ping(self.latchPin)

if __name__=="__main__":
  serialPin, latchPin, clockPin = 23, 24, 25
  pattern = 0b01100110        # 8-bit pattern to display on LED bar

  try:
    shifter = Shifter(serialPin, clockPin, latchPin)
    shifter.shiftByte(pattern)
    while 1: 
      pass
  except:
    GPIO.cleanup()