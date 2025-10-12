import time
import random
import threading
import RPi.GPIO as GPIO
from shifter import Shifter

class Bug:
    def __init__(self, timestep=0.1, x=3, isWrapOn=False):
        self.timestep = timestep
        self.x = x
        self.isWrapOn = isWrapOn
        self.__shifter = Shifter(serialPin=23, clockPin=25, latchPin=24)
        self.__running = False
        self.__thread = None

    def __update(self):
        """Private thread loop to update LED position."""
        while self.__running:
            pattern = 1 << self.x
            self.__shifter.shiftByte(pattern)
            time.sleep(self.timestep)

            # Random move: left or right
            step = random.choice([-1, 1])
            self.x += step

            if self.isWrapOn:
                self.x %= 8  # wrap around 0–7
            else:
                self.x = max(0, min(7, self.x))

    def start(self):
        """Start the random walk animation."""
        if not self.__running:
            self.__running = True
            self.__thread = threading.Thread(target=self.__update)
            self.__thread.start()

    def stop(self):
        """Stop the animation and clear LEDs."""
        self.__running = False
        if self.__thread:
            self.__thread.join()
        self.__shifter.shiftByte(0)  # turn off all LEDs
 
