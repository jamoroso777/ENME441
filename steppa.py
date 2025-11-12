# stepper_class_shiftregister_multiprocessing.py
#
# Stepper class (fixed for simultaneous multi-motor operation via shift register)
# Now includes proper shared angle tracking using multiprocessing.Value
# and correct shortest-path goAngle() logic.

import time
import multiprocessing
import ctypes
from shifter import Shifter   # custom Shifter class

class Stepper:
    """
    Supports operation of an arbitrary number of stepper motors using
    one or more shift registers.

    Each motor uses 4 bits of the shared shift register outputs.
    The motors can operate simultaneously, with each motor's angle
    tracked independently and accurately.
    """

    # Class attributes:
    num_steppers = 0
    shifter_outputs = multiprocessing.Value('i', 0)  # shared integer for shift register bits
    seq = [0b0001,0b0011,0b0010,0b0110,0b0100,0b1100,0b1000,0b1001]  # 8-step sequence
    delay = 1200  # delay between motor steps [µs]
    steps_per_degree = 1024 / 360  # 4096 steps per revolution

    def __init__(self, shifter, lock):
        self.s = shifter
        self.lock = lock
        self.step_state = 0
        self.angle = multiprocessing.Value(ctypes.c_double, 0.0)  # shared double for persistent angle
        self.shifter_bit_start = 4 * Stepper.num_steppers  # bit position for this motor
        Stepper.num_steppers += 1

    # Internal sign function
    def __sgn(self, x):
        if x == 0:
            return 0
        else:
            return int(abs(x) / x)

    # Perform one step in given direction
    def __step(self, dir):
        self.step_state = (self.step_state + dir) % 8
        mask = 0b1111 << self.shifter_bit_start

        with self.lock:
            val = Stepper.shifter_outputs.value
            val &= ~mask
            val |= (Stepper.seq[self.step_state] << self.shifter_bit_start)
            Stepper.shifter_outputs.value = val
            self.s.shiftByte(val)

        # Update internal angle tracker
        with self.angle.get_lock():
            self.angle.value = (self.angle.value + dir / Stepper.steps_per_degree) % 360

    # Internal rotation (blocking)
    def __rotate(self, delta):
        numSteps = int(Stepper.steps_per_degree * abs(delta))
        dir = self.__sgn(delta)
        for _ in range(numSteps):
            self.__step(dir)
            time.sleep(Stepper.delay / 1e6)

    # Public rotate (non-blocking, relative)
    def rotate(self, delta):
        p = multiprocessing.Process(target=self.__rotate, args=(delta,))
        p.start()

    # Move to a specific angle (non-blocking)
    def goAngle(self, target_angle):
        with self.angle.get_lock():
            current_angle = self.angle.value

        # Compute delta as shortest path [-180, 180]
        delta = (target_angle - current_angle + 540) % 360 - 180

        # Spawn process for simultaneous motion
        p = multiprocessing.Process(target=self.__rotate, args=(delta,))
        p.start()

        # Update tracked angle in main process
        with self.angle.get_lock():
            self.angle.value = (current_angle + delta) % 360

    # Reset zero position
    def zero(self):
        with self.angle.get_lock():
            self.angle.value = 0.0


# Example test
if __name__ == '__main__':
    s = Shifter(data=16, latch=20, clock=21)
    lock = multiprocessing.Lock()

    # Instantiate in REVERSE ORDER (Qa–Qd first, Qe–Qh second)
    m2 = Stepper(s, lock)  # Motor 2 uses Qa–Qd (upper bits)
    m1 = Stepper(s, lock)  # Motor 1 uses Qe–Qh (lower bits)

    m1.zero()
    m2.zero()

    print("Rotating both motors simultaneously through sequence...")
    m1.goAngle(90)
    m2.goAngle(-90)
    time.sleep(5)
    m1.goAngle(-45)
    m2.goAngle(45)
    time.sleep(5)
    m1.goAngle(-135)
    time.sleep(5)
    m1.goAngle(135)
    time.sleep(5)
    m1.goAngle(0)

    try:
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nEnd of program.")
