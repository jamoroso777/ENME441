# stepper_class_shiftregister_multiprocessing.py
#
# Lab 8 – Stepper Motor Control
# Simplified and correct version (no joins, proper multiprocessing.Value)

import time
import multiprocessing
from shifter import Shifter


class Stepper:
    # Class-level parameters
    num_steppers = 0
    shifter_outputs = 0
    seq = [0b0001, 0b0011, 0b0010, 0b0110,
           0b0100, 0b1100, 0b1000, 0b1001]
    delay = 1200                # microseconds
    steps_per_degree = 4096.0 / 360.0  # 4096 steps per rev

    def __init__(self, shifter, lock):
        self.s = shifter
        self.angle = multiprocessing.Value('d', 0.0)   # shared across processes ✅
        self.step_state = 0
        self.shifter_bit_start = 4 * Stepper.num_steppers
        self.lock = lock
        self.motor_id = Stepper.num_steppers + 1
        Stepper.num_steppers += 1

    # Helper: sign of x
    def __sgn(self, x):
        return 0 if x == 0 else int(abs(x) / x)

    # Step one increment
    def __step(self, direction):
        self.step_state = (self.step_state + direction) % len(Stepper.seq)

        mask = 0b1111 << self.shifter_bit_start
        Stepper.shifter_outputs &= ~mask
        Stepper.shifter_outputs |= Stepper.seq[self.step_state] << self.shifter_bit_start

        total_bits = max(8, Stepper.num_steppers * 4)
        self.s.shiftWord(Stepper.shifter_outputs, total_bits)

        # Update angle
        self.angle.value += direction / Stepper.steps_per_degree
        self.angle.value %= 360.0

    # Private rotation function (runs in new process)
    def __rotate(self, delta):
        with self.lock:
            steps = int(abs(delta) * Stepper.steps_per_degree)
            direction = self.__sgn(delta)
            for _ in range(steps):
                self.__step(direction)
                time.sleep(Stepper.delay / 1e6)

    # Public method: relative motion
    def rotate(self, delta):
        p = multiprocessing.Process(target=self.__rotate, args=(delta,))
        p.start()

    # Public method: go to absolute target
    def goAngle(self, target):
        current = self.angle.value
        delta = (target - current + 180) % 360 - 180  # shortest path
        print(f"[Motor {self.motor_id}] goAngle({target}) "
              f"from {current:.1f}° (delta={delta:.1f}°)", flush=True)
        p = multiprocessing.Process(target=self.__rotate, args=(delta,))
        p.start()

    # Zero motor angle
    def zero(self):
        self.angle.value = 0.0
        print(f"[Motor {self.motor_id}] Zeroed.", flush=True)


# ---------------- Example Lab 8 Test ----------------
if __name__ == '__main__':
    s = Shifter(data=16, clock=21, latch=20)

    # Two separate locks for simultaneous operation
    lock1 = multiprocessing.Lock()
    lock2 = multiprocessing.Lock()

    m1 = Stepper(s, lock1)
    m2 = Stepper(s, lock2)

    m1.zero()
    m2.zero()

    time.sleep(0.5)
    print("\n=== Lab 8 simultaneous goAngle() demo ===\n", flush=True)

    # Commands from the lab sheet
    m1.goAngle(90)
    m1.goAngle(-45)

    m2.goAngle(-90)
    m2.goAngle(45)

    m1.goAngle(-135)
    m1.goAngle(135)
    m1.goAngle(0)

    try:
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nDemo complete.")
