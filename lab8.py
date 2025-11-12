# stepper_class_shiftregister_multiprocessing.py
#
# Stepper class (fixed for simultaneous multi-motor operation via shift register)
#
# This version allows multiple stepper motors (each using 4 bits of the same shift register)
# to move simultaneously, with proper multiprocessing and shared memory handling.

import time
import multiprocessing
from shifter import Shifter   # custom Shifter class

class Stepper:
    """
    Supports operation of an arbitrary number of stepper motors using
    one or more shift registers.

    Each motor uses 4 bits of the shared shift register outputs.
    The motors can now operate simultaneously, since all processes
    share a single 'shifter_outputs' variable through multiprocessing.Value.
    """

    # Class attributes:
    num_steppers = 0
    shifter_outputs = multiprocessing.Value('i', 0)  # shared integer across processes
    seq = [0b0001,0b0011,0b0010,0b0110,0b0100,0b1100,0b1000,0b1001]  # 8-step half-stepping sequence
    delay = 1200          # delay between motor steps [us]
    steps_per_degree = 4096 / 1440  # 4096 steps per rev

    def __init__(self, shifter, lock):
        self.s = shifter
        self.angle = 0
        self.step_state = 0
        self.shifter_bit_start = 4 * Stepper.num_steppers  # starting bit position
        self.lock = lock
        Stepper.num_steppers += 1

    # Signum function:
    def __sgn(self, x):
        if x == 0:
            return 0
        else:
            return int(abs(x) / x)

    # Move a single +/-1 step in the motor sequence:
    def __step(self, dir):
        # Update sequence state
        self.step_state = (self.step_state + dir) % 8
        mask = 0b1111 << self.shifter_bit_start

        with self.lock:
            # Read the shared shift register value
            val = Stepper.shifter_outputs.value

            # Clear this motor’s 4 bits
            val &= ~mask

            # Write new sequence pattern to its 4 bits
            val |= (Stepper.seq[self.step_state] << self.shifter_bit_start)

            # Save and output the updated byte
            Stepper.shifter_outputs.value = val
            self.s.shiftByte(val)

        # Update motor angle tracking
        self.angle = (self.angle + dir / Stepper.steps_per_degree) % 360

    # Rotate a relative angle (blocking)
    def __rotate(self, delta):
        numSteps = int(Stepper.steps_per_degree * abs(delta))
        dir = self.__sgn(delta)
        for _ in range(numSteps):
            self.__step(dir)
            time.sleep(Stepper.delay / 1e6)

    # Public rotate (non-blocking)
    def rotate(self, delta):
        # Spawn a process so multiple motors can move simultaneously
        p = multiprocessing.Process(target=self.__rotate, args=(delta,))
        p.start()

    # Move to an absolute angle taking the shortest path:
    def goAngle(self, target_angle):
        delta = (target_angle - self.angle + 540) % 360 - 180
        self.rotate(delta)
       

    # Set the motor zero point
    def zero(self):
        self.angle = 0


# Example usage:
if __name__ == '__main__':
    s = Shifter(data=16, latch=20, clock=21)   # Setup shift register
    lock = multiprocessing.Lock()              # Shared lock for hardware access

    # Instantiate in REVERSE ORDER (Qa–Qd first, Qe–Qh second)
    m2 = Stepper(s, lock)  # Motor 2 uses Qa–Qd (upper bits)
    m1 = Stepper(s, lock)  # Motor 1 uses Qe–Qh (lower bits)

    # Zero both
    m1.zero()
    m2.zero()

    # Move both simultaneously
    print("Rotating both motors...")
    
    print("setting m1 90, m2 -90")    
    m1.goAngle(90)
    m2.goAngle(-90)
    time.sleep(5)
    print("setting m1 -45, m2 45")
    m1.goAngle(-45)
    m2.goAngle(45)
    time.sleep(5)
    print("setting m1 -135")
    m1.goAngle(-135)
    time.sleep(5)
    print("setting m1 135")
    m1.goAngle(135)
    time.sleep(5)
    print("set m1 0")
    m1.goAngle(0)

    try:
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nEnd of program.")
