# stepper_class_shiftregister_multiprocessing.py
#
# Stepper class with simultaneous multi-motor operation,
# shared angle tracking, and shortest-path absolute rotation.

import time
import multiprocessing
import ctypes
from shifter import Shifter   # custom Shifter class

class Stepper:
    """
    Supports operation of multiple stepper motors using one or more shift registers.
    Each motor uses 4 bits of the shared shift register outputs. Motors can move
    simultaneously, with proper shared angle tracking and shortest-path rotation.
    """

    # Class attributes
    num_steppers = 0
    shifter_outputs = multiprocessing.Value('i', 0)  # shared shift register outputs
    seq = [0b0001, 0b0011, 0b0010, 0b0110, 0b0100, 0b1100, 0b1000, 0b1001]  # 8-step sequence
    delay = 1200  # microseconds between steps
    steps_per_degree = 1024 / 360  # adjust to your motor

    def __init__(self, shifter, lock, name="Stepper"):
        self.s = shifter
        self.lock = lock
        self.name = name
        self.step_state = 0
        self.angle = multiprocessing.Value(ctypes.c_double, 0.0)  # shared angle
        self.shifter_bit_start = 4 * Stepper.num_steppers
        Stepper.num_steppers += 1

    # Sign function
    def __sgn(self, x):
        if x == 0:
            return 0
        else:
            return int(abs(x)/x)

    # Single step
    def __step(self, dir):
        self.step_state = (self.step_state + dir) % 8
        mask = 0b1111 << self.shifter_bit_start
        with self.lock:
            val = Stepper.shifter_outputs.value
            val &= ~mask
            val |= (Stepper.seq[self.step_state] << self.shifter_bit_start)
            Stepper.shifter_outputs.value = val
            self.s.shiftByte(val)
        # Update angle after step
        with self.angle.get_lock():
            self.angle.value = (self.angle.value + dir / Stepper.steps_per_degree) % 360

    # Relative rotation (blocking)
    def __rotate(self, delta):
        numSteps = int(abs(delta) * Stepper.steps_per_degree)
        dir = self.__sgn(delta)
        for _ in range(numSteps):
            self.__step(dir)
            time.sleep(Stepper.delay / 1e6)

    # Public relative rotation (non-blocking)
    def rotate(self, delta):
        p = multiprocessing.Process(target=self.__rotate, args=(delta,))
        p.start()
        return p  # allows join if needed

    # Absolute rotation to target angle (non-blocking)
    def goAngle(self, target_angle):
        """
        Move motor to target_angle via shortest path.
        Returns the process so the main program can join if needed.
        """
        def move_to_target(target, angle_value):
            with angle_value.get_lock():
                current = angle_value.value

            # Compute three possible deltas
            alpha = target - current
            beta = target - current + 360
            gamma = target - current - 360

            delta = min([alpha, beta, gamma], key=abs)

            # Rotate step-by-step
            direction = 1 if delta > 0 else -1
            steps = int(abs(delta) * Stepper.steps_per_degree)

            for _ in range(steps):
                self.__step(direction)
                time.sleep(Stepper.delay / 1e6)

            # Update shared angle after move
            with angle_value.get_lock():
                angle_value.value = (current + delta) % 360

        # Launch process for simultaneous motion
        p = multiprocessing.Process(target=move_to_target, args=(target_angle, self.angle))
        p.start()
        return p  # caller can join()

    # Reset zero position
    def zero(self):
        with self.angle.get_lock():
            self.angle.value = 0.0


# Example usage
if __name__ == '__main__':
    s = Shifter(data=16, latch=20, clock=21)
    lock = multiprocessing.Lock()

    # Instantiate motors in reverse order (Qa–Qd first)
    m1 = Stepper(s, lock, name="Motor1")  # Qe–Qh lower bits
    m2 = Stepper(s, lock, name="Motor2")  # Qa–Qd upper bits

    # Zero both motors
    m1.zero()
    m2.zero()

    # Move motors simultaneously, shortest path
    p1 = m1.goAngle(90)
    p2 = m2.goAngle(-90)
    p1.join()
    p2.join()
    time.sleep(3)
    p1 = m1.goAngle(-45)
    p2 = m2.goAngle(45)
    p1.join()
    p2.join()
    time.sleep(3)

    p1 = m1.goAngle(-135)
    p1.join()
    time.sleep(3)
    p1 = m1.goAngle(135)
    p1.join()
    time.sleep(3)
    p1 = m1.goAngle(0)
    p1.join()

    try:
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nEnd of program.")
