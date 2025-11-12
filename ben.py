# stepper_class_shiftregister_multiprocessing_child_delta_shared_angle.py
#
# - delta is computed inside the child process
# - angle is a multiprocessing.Value (shared) so successive child processes
#   see the updated motor position
# - steps update the shared angle as they execute

import time
import multiprocessing
from shifter import Shifter   # your custom Shifter class


class Stepper:
    # shared class attributes
    num_steppers = 0
    shifter_outputs = multiprocessing.Value('i', 0)  # shared int for shift register byte
    seq = [0b0001,0b0011,0b0010,0b0110,0b0100,0b1100,0b1000,0b1001]  # 8-step half-step
    delay = 1200  # microseconds between steps
    steps_per_degree = 1024.0 / 360.0  # 4096 steps/rev -> keep float precision

    def __init__(self, shifter, hw_lock):
        self.s = shifter
        self.lock = hw_lock  # lock that guards the shared shift register hardware
        # Shared angle value so parent and children all see the same current angle
        self.angle = multiprocessing.Value('d', 0.0)  # 'd' = double
        self.step_state = 0
        self.shifter_bit_start = 4 * Stepper.num_steppers
        Stepper.num_steppers += 1

    # sign function
    def __sgn(self, x):
        return 0 if x == 0 else int(abs(x) / x)

    # single low-level step: updates shift register and the shared angle
    def __step(self, dir):
        # advance the step state (half-step sequence)
        self.step_state = (self.step_state + dir) % len(Stepper.seq)
        mask = 0b1111 << self.shifter_bit_start

        # update the shared shift register byte and actually output it
        with self.lock:
            val = Stepper.shifter_outputs.value
            val &= ~mask
            val |= (Stepper.seq[self.step_state] << self.shifter_bit_start)
            Stepper.shifter_outputs.value = val
            # perform the actual hardware shift
            self.s.shiftByte(val)

        # update the shared angle value (in degrees)
        delta_deg = dir / Stepper.steps_per_degree
        # Use get_lock on the Value for atomic update
        with self.angle.get_lock():
            self.angle.value = (self.angle.value + delta_deg) % 360.0

    # This runs inside the child process: compute shortest delta from shared angle,
    # then step that many steps while updating the shared angle
    def __rotate_child(self, target_angle):
        # read current shared angle atomically
        with self.angle.get_lock():
            current = self.angle.value

        # compute shortest signed delta in (-180, 180]
        delta = (target_angle - current + 540.0) % 360.0 - 180.0

        num_steps = int(abs(delta) * Stepper.steps_per_degree)
        direction = self.__sgn(delta)

        for _ in range(num_steps):
            self.__step(direction)
            # sleep according to delay in microseconds
            time.sleep(Stepper.delay / 1e6)

        # after finishing, ensure angle is exactly target (fix tiny rounding)
        with self.angle.get_lock():
            self.angle.value = target_angle % 360.0

    # Public: non-blocking move to absolute target angle. delta computed inside child.
    def goAngle(self, target_angle):
        p = multiprocessing.Process(target=self.__rotate_child, args=(float(target_angle),))
        p.start()
        return p

    # set zero (shared)
    def zero(self):
        with self.angle.get_lock():
            self.angle.value = 0.0


# Example usage that demonstrates the sequence you described:
if __name__ == '__main__':
    s = Shifter(data=16, latch=20, clock=21)   # adapt pins to your hardware
    hw_lock = multiprocessing.Lock()

    # instantiate motors (note order in your original code)
    m2 = Stepper(s, hw_lock)
    m1 = Stepper(s, hw_lock)

    # zero both
    m1.zero()
    m2.zero()

    def signed_angle(a):
        """Helper to print angles in [-180,180) for clarity."""
        a = (a + 180.0) % 360.0 - 180.0
        return a

    print("Starting sequence (parent will read shared .value angles):")

    # 1) m1 -> +90, m2 -> -90
    print("setting m1 90, m2 -90")
    m1.goAngle(90)
    m2.goAngle(-90)
    time.sleep(5)
    print("m1 angle (deg):", m1.angle.value, "signed:", signed_angle(m1.angle.value))
    print("m2 angle (deg):", m2.angle.value, "signed:", signed_angle(m2.angle.value))

    # 2) m1 -> -45, m2 -> 45
    print("setting m1 -45, m2 45")
    m1.goAngle(-45)
    m2.goAngle(45)
    time.sleep(5)
    print("m1 angle (deg):", m1.angle.value, "signed:", signed_angle(m1.angle.value))
    print("m2 angle (deg):", m2.angle.value, "signed:", signed_angle(m2.angle.value))

    # 3) m1 -> -135
    print("setting m1 -135")
    m1.goAngle(-135)
    time.sleep(5)
    print("m1 angle (deg):", m1.angle.value, "signed:", signed_angle(m1.angle.value))
    print("m2 angle (deg):", m2.angle.value, "signed:", signed_angle(m2.angle.value))

    # 4) m1 -> 135
    print("setting m1 135")
    m1.goAngle(135)
    time.sleep(5)
    print("m1 angle (deg):", m1.angle.value, "signed:", signed_angle(m1.angle.value))
    print("m2 angle (deg):", m2.angle.value, "signed:", signed_angle(m2.angle.value))

    # 5) m1 -> 0
    print("set m1 0")
    m1.goAngle(0)
    time.sleep(5)
    print("m1 angle (deg):", m1.angle.value, "signed:", signed_angle(m1.angle.value))
    print("m2 angle (deg):", m2.angle.value, "signed:", signed_angle(m2.angle.value))

    try:
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nEnd of program.")
