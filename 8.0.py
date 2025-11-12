import time
import multiprocessing
from shifter import Shifter

class Stepper:
    """
    Multi-stepper class using shift registers.
    Each motor uses 4 bits of the shared register.
    Tracks angle in shared memory for cross-process access.
    """

    # Class attributes
    num_steppers = 0
    shifter_outputs = multiprocessing.Value('i', 0)  # shared shift register
    seq = [0b0001,0b0011,0b0010,0b0110,0b0100,0b1100,0b1000,0b1001]  # 8-step half-step
    delay = 1200  # microseconds
    steps_per_degree = 1024 / 360  # 1024 steps per 360°

    def __init__(self, shifter, lock):
        self.s = shifter
        self.lock = lock
        self.angle = multiprocessing.Value('d', 0.0)  # shared angle for this motor
        self.step_state = 0
        self.shifter_bit_start = 4 * Stepper.num_steppers
        Stepper.num_steppers += 1

    # Sign function
    def __sgn(self, x):
        return 0 if x == 0 else int(abs(x) / x)

    # Step one sequence step
    def __step(self, dir):
        self.step_state = (self.step_state + dir) % 8
        mask = 0b1111 << self.shifter_bit_start

        with self.lock:
            val = Stepper.shifter_outputs.value
            val &= ~mask
            val |= (Stepper.seq[self.step_state] << self.shifter_bit_start)
            Stepper.shifter_outputs.value = val
            self.s.shiftByte(val)

        # Update shared angle
        with self.angle.get_lock():
            self.angle.value = (self.angle.value + dir / Stepper.steps_per_degree) % 360

    # Blocking rotation by relative angle
    def __rotate(self, delta):
        num_steps = int(Stepper.steps_per_degree * abs(delta))
        dir = self.__sgn(delta)
        for _ in range(num_steps):
            self.__step(dir)
            time.sleep(Stepper.delay / 1e6)

    # Public rotation (blocking)
    def rotate(self, delta):
        self.__rotate(delta)

    # Move to absolute angle (blocking)
    def goAngle(self, target_angle):
        with self.angle.get_lock():
            current = self.angle.value
        # Minimal delta: [-180,180]
        delta = (target_angle - current + 540) % 360 - 180
        self.__rotate(delta)

    # Zero the motor
    def zero(self):
        with self.angle.get_lock():
            self.angle.value = 0.0

# Helper function to move multiple motors simultaneously
def goAnglesSimultaneous(motors, target_angles):
    """
    motors: list of Stepper objects
    target_angles: list of absolute angles
    """
    procs = []
    for m, a in zip(motors, target_angles):
        p = multiprocessing.Process(target=m.goAngle, args=(a,))
        p.start()
        procs.append(p)
    for p in procs:
        p.join()

# =====================
# Main program
# =====================
if __name__ == '__main__':
    s = Shifter(data=16, latch=20, clock=21)
    lock = multiprocessing.Lock()

    # Instantiate motors (Motor1 = Qe-Qh, Motor2 = Qa-Qd)
    m1 = Stepper(s, lock)  # Motor1
    m2 = Stepper(s, lock)  # Motor2

    # Step 1: Zero both
    m1.zero()
    m2.zero()
    print(f"Zeroed: Motor1 = {m1.angle.value:.2f}, Motor2 = {m2.angle.value:.2f}")

    # Step 2: First simultaneous move
    goAnglesSimultaneous([m1, m2], [90, -90])
    print(f"After goAngle(90/-90): Motor1 = {m1.angle.value:.2f}, Motor2 = {m2.angle.value:.2f}")

    # Step 3: Second simultaneous move
    goAnglesSimultaneous([m1, m2], [-45, 45])
    print(f"After goAngle(-45/45): Motor1 = {m1.angle.value:.2f}, Motor2 = {m2.angle.value:.2f}")

    # Step 4: Remaining moves for Motor1 (blocking)
    m1.goAngle(-135)
    print(f"After m1.goAngle(-135): Motor1 = {m1.angle.value:.2f}, Motor2 = {m2.angle.value:.2f}")

    m1.goAngle(135)
    print(f"After m1.goAngle(135): Motor1 = {m1.angle.value:.2f}, Motor2 = {m2.angle.value:.2f}")

    m1.goAngle(0)
    print(f"After m1.goAngle(0): Motor1 = {m1.angle.value:.2f}, Motor2 = {m2.angle.value:.2f}")
