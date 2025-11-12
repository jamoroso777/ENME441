# stepper_class_shiftregister_multiprocessing.py
#
# Stepper class (synchronous version that allows simultaneous multi-motor operation)

import time
import multiprocessing
from shifter import Shifter

class Stepper:
    num_steppers = 0
    shifter_outputs = multiprocessing.Value('i', 0)
    seq = [0b0001,0b0011,0b0010,0b0110,0b0100,0b1100,0b1000,0b1001]
    delay = 1200
    steps_per_degree = 4096 / 360

    def __init__(self, shifter, lock):
        self.s = shifter
        self.angle = multiprocessing.Value('d', 0.0)
        self.step_state = 0
        self.shifter_bit_start = 4 * Stepper.num_steppers
        self.lock = lock
        Stepper.num_steppers += 1

    def __sgn(self, x):
        return 0 if x == 0 else int(abs(x) / x)

    def __step(self, dir):
        self.step_state = (self.step_state + dir) % 8
        mask = 0b1111 << self.shifter_bit_start

        with self.lock:
            val = Stepper.shifter_outputs.value
            val &= ~mask
            val |= (Stepper.seq[self.step_state] << self.shifter_bit_start)
            Stepper.shifter_outputs.value = val
            self.s.shiftByte(val)

        with self.angle.get_lock():
            self.angle.value = (self.angle.value + dir / Stepper.steps_per_degree) % 360

    def __rotate(self, delta):
        numSteps = int(Stepper.steps_per_degree * abs(delta))
        dir = self.__sgn(delta)
        for _ in range(numSteps):
            self.__step(dir)
            time.sleep(Stepper.delay / 1e6)

    # ✅ modified: return the process, so we can join() later
    def rotate(self, delta):
        p = multiprocessing.Process(target=self.__rotate, args=(delta,))
        p.start()
        return p

    def goAngle(self, target_angle):
        with self.angle.get_lock():
            current_angle = self.angle.value
        delta = (target_angle - current_angle + 180) % 360 - 180

        # ✅ Start motion in separate process and wait for completion
        p = self.rotate(delta)
        p.join()  # wait for motor to finish before continuing

        with self.angle.get_lock():
            self.angle.value = (current_angle + delta) % 360

    def zero(self):
        with self.angle.get_lock():
            self.angle.value = 0.0


if __name__ == '__main__':
    s = Shifter(data=16, latch=20, clock=21)
    lock = multiprocessing.Lock()

    m2 = Stepper(s, lock)
    m1 = Stepper(s, lock)

    m1.zero()
    m2.zero()

    print("Rotating both motors...")

    print("setting m1 90, m2 -90")
    p1 = multiprocessing.Process(target=m1.goAngle, args=(90,))
    p2 = multiprocessing.Process(target=m2.goAngle, args=(-90,))
    p1.start()
    p2.start()
    p1.join()
    p2.join()

    print("setting m1 -45, m2 45")
    p1 = multiprocessing.Process(target=m1.goAngle, args=(-45,))
    p2 = multiprocessing.Process(target=m2.goAngle, args=(45,))
    p1.start()
    p2.start()
    p1.join()
    p2.join()

    print("setting m1 -135")
    m1.goAngle(-135)

    print("setting m1 135")
    m1.goAngle(135)

    print("set m1 0")
    m1.goAngle(0)

    print("All moves complete.")
