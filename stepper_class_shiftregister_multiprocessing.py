# stepper_class_shiftregister_multiprocessing.py
#
# Final Lab 8 version – simultaneous motor control, minimal debug output

import time
import multiprocessing
from shifter import Shifter

class Stepper:
    # Shared class attributes
    num_steppers = 0
    shifter_outputs = multiprocessing.Value('i', 0)  # shared across processes
    seq = [0b0001, 0b0011, 0b0010, 0b0110,
           0b0100, 0b1100, 0b1000, 0b1001]
    delay = 1200            # µs between steps
    steps_per_degree = 4096.0 / 360.0

    def __init__(self, shifter, lock):
        self.s = shifter
        self.angle = multiprocessing.Value('d', 0.0)  # shared across processes
        self.step_state = 0
        self.shifter_bit_start = 4 * Stepper.num_steppers
        self.motor_id = Stepper.num_steppers + 1
        self.lock = lock
        Stepper.num_steppers += 1

    # Helper
    def __sgn(self, x):
        return 0 if x == 0 else int(abs(x) / x)

    def __step(self, dir):
        """Take one step in given direction."""
        self.step_state = (self.step_state + dir) % len(Stepper.seq)

        mask = 0b1111 << self.shifter_bit_start

        # Read-modify-write the shared outputs safely
        with Stepper.shifter_outputs.get_lock():
            val = Stepper.shifter_outputs.value
            val &= ~mask
            val |= Stepper.seq[self.step_state] << self.shifter_bit_start
            Stepper.shifter_outputs.value = val

            total_bits = max(8, Stepper.num_steppers * 4)
            self.s.shiftWord(Stepper.shifter_outputs.value, total_bits)

        # Update angle
        self.angle.value += dir / Stepper.steps_per_degree
        self.angle.value %= 360.0

    def __rotate(self, delta):
        """Rotate by delta degrees (run in a separate process)."""
        num_steps = int(abs(delta) * Stepper.steps_per_degree)
        direction = self.__sgn(delta)
        for _ in range(num_steps):
            self.__step(direction)
            time.sleep(Stepper.delay / 1e6)

    # Public methods
    def goAngle(self, target):
        """Move to target angle using shortest path."""
        current = self.angle.value
        delta = (target - current + 180) % 360 - 180
        print(f"[Motor {self.motor_id}] Starting goAngle({target}) "
              f"from {current:.1f}°, delta={delta:.1f}°", flush=True)

        p = multiprocessing.Process(target=self.__rotate, args=(delta,))
        p.start()

        # Optional watcher process: wait until rotation should finish
        def watcher(proc, motor_id, target):
            proc.join()
            print(f"[Motor {motor_id}] Finished goAngle({target})", flush=True)

        watcher_proc = multiprocessing.Process(
            target=watcher, args=(p, self.motor_id, target))
        watcher_proc.start()

    def zero(self):
        self.angle.value = 0.0
        print(f"[Motor {self.motor_id}] Zeroed (angle=0°)", flush=True)


# ---------------- Example Lab Test ----------------
if __name__ == '__main__':
    s = Shifter(data=16, clock=21, latch=20)

    # Separate locks for simultaneous motion
    lock1 = multiprocessing.Lock()
    lock2 = multiprocessing.Lock()

    m1 = Stepper(s, lock1)
    m2 = Stepper(s, lock2)

    m1.zero()
    m2.zero()

    time.sleep(0.5)
    print("\n=== Lab 8 simultaneous goAngle() demo ===\n", flush=True)

    # Motors operate simultaneously (independent locks)
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
        print("\nDemo stopped.")