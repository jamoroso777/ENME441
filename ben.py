# stepper_class_shiftregister_multiprocessing_childdelta.py
#
# Stepper class (fixed delta calculation inside child process)
# - Each motor computes delta relative to its own current angle inside its child process.
# - Simultaneous multi-motor operation via shared shift register.

import time
import multiprocessing
from shifter import Shifter   # custom Shifter class


class Stepper:
    """
    Supports operation of an arbitrary number of stepper motors using
    one or more shift registers.

    Each motor uses 4 bits of the shared shift register outputs.
    The motors can operate simultaneously, since all processes
    share a single 'shifter_outputs' variable via multiprocessing.Value.
    """

    # Class attributes:
    num_steppers = 0
    shifter_outputs = multiprocessing.Value('i', 0)  # shared integer across processes
    seq = [0b0001,0b0011,0b0010,0b0110,0b0100,0b1100,0b1000,0b1001]  # 8-step half-step sequence
    delay = 1200          # delay between motor steps [µs]
    steps_per_degree = 1024.0 / 360.0  # 4096 steps per rev

    def __init__(self, shifter, lock):
        self.s = shifter
        self.angle = 0.0
        self.step_state = 0
        self.shifter_bit_start = 4 * Stepper.num_steppers
        self.lock = lock
        Stepper.num_steppers += 1

    # Signum function
    def __sgn(self, x):
        return 0 if x == 0 else int(abs(x) / x)

    # Move a single +/-1 step
    def __step(self, dir):
        # Update sequence position
        self.step_state = (self.step_state + dir) % 8
        mask = 0b1111 << self.shifter_bit_start

        with self.lock:
            val = Stepper.shifter_outputs.value
            val &= ~mask
            val |= (Stepper.seq[self.step_state] << self.shifter_bit_start)
            Stepper.shifter_outputs.value = val
            self.s.shiftByte(val)

        # Update angle (local to process)
        self.angle = (self.angle + dir / Stepper.steps_per_degree) % 360.0

    # --- Runs in the child process ---
    def __rotate_to(self, target_angle):
        """Rotate to target angle (computed relative to this process's current angle)."""
        delta = (target_angle - self.angle + 540.0) % 360.0 - 180.0  # shortest path
        numSteps = int(abs(delta) * Stepper.steps_per_degree)
        dir = self.__sgn(delta)

        for _ in range(numSteps):
            self.__step(dir)
            time.sleep(Stepper.delay / 1e6)

    # --- Public interface ---
    def goAngle(self, target_angle):
        """Rotate motor to the target absolute angle (non-blocking)."""
        p = multiprocessing.Process(target=self.__rotate_to, args=(target_angle,))
        p.start()

    def zero(self):
        self.angle = 0.0


# Example usage:
if __name__ == '__main__':
    s = Shifter(data=16, latch=20, clock=21)
    lock = multiprocessing.Lock()

    # Instantiate motors (Qa–Qd first, Qe–Qh second)
    m2 = Stepper(s, lock)
    m1 = Stepper(s, lock)

    m1.zero()
    m2.zero()

    print("Rotating both motors...")

    print("setting m1 90, m2 -90")
    m1.goAngle(90)
    m2.goAngle(-90)
    time.sleep(5)
    print("m1.angle (parent copy):", m1.angle)
    print("m2.angle (parent copy):", m2.angle)

    print("setting m1 -45, m2 45")
    m1.goAngle(-45)
    m2.goAngle(45)
    time.sleep(5)
    print("m1.angle (parent copy):", m1.angle)
    print("m2.angle (parent copy):", m2.angle)

    print("setting m1 -135")
    m1.goAngle(-135)
    time.sleep(5)
    print("m1.angle (parent copy):", m1.angle)
    print("m2.angle (parent copy):", m2.angle)

    print("setting m1 135")
    m1.goAngle(135)
    time.sleep(5)
    print("m1.angle (parent copy):", m1.angle)
    print("m2.angle (parent copy):", m2.angle)

    print("set m1 0")
    m1.goAngle(0)

    try:
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nEnd of program.")
