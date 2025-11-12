# stepper_class_shiftregister_multiprocessing_fixed.py
#
# Stepper class (fixed for simultaneous multi-motor operation via shift register)
# - delta is calculated inside the child process (so it's based on the motor's current position)
# - angle is stored in multiprocessing.Value so parent and children share it

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
    steps_per_degree = 1024.0 / 360.0  # 4096 steps per rev -> keep as float

    def __init__(self, shifter, lock, use_shared_angle=True):
        self.s = shifter
        # Use a shared value for angle so parent can read it and children update the same value.
        if use_shared_angle:
            self.angle = multiprocessing.Value('d', 0.0)  # 'd' = double (float)
        else:
            # fallback to local float (not shared)
            self.angle = 0.0

        self.step_state = 0
        # Each motor uses 4 bits. start bit is assigned in the order of instantiation.
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

        # Update motor angle tracking — handle both shared and non-shared angle types
        delta_degrees = dir / Stepper.steps_per_degree
        if isinstance(self.angle, multiprocessing.Value):
            # Multiprocessing.Value: must access .value
            with self.angle.get_lock():
                self.angle.value = (self.angle.value + delta_degrees) % 360.0
        else:
            self.angle = (self.angle + delta_degrees) % 360.0

    # Rotate to a target angle (this runs in child process)
    def __rotate_to(self, target_angle):
        # Compute delta inside the child using the (possibly shared) current angle
        if isinstance(self.angle, multiprocessing.Value):
            with self.angle.get_lock():
                current = self.angle.value
        else:
            current = self.angle

        # shortest signed delta in range (-180, 180]
        delta = (target_angle - current + 540.0) % 360.0 - 180.0

        numSteps = int(abs(delta) * Stepper.steps_per_degree)
        dir = self.__sgn(delta)

        for _ in range(numSteps):
            self.__step(dir)
            time.sleep(Stepper.delay / 1e6)

    # Public rotate to absolute target angle (non-blocking)
    def rotate(self, target_angle):
        # Spawn a process so multiple motors can move simultaneously.
        # The child will compute the delta using its (shared) angle value.
        p = multiprocessing.Process(target=self.__rotate_to, args=(target_angle,))
        p.daemon = True
        p.start()
        return p  # returning the Process object can be useful for joining if desired

    # Move to an absolute angle taking the shortest path:
    def goAngle(self, target_angle):
        # Now simply ask the motor to rotate to the target; delta is computed inside the child.
        return self.rotate(target_angle)

    # Set the motor zero point
    def zero(self):
        if isinstance(self.angle, multiprocessing.Value):
            with self.angle.get_lock():
                self.angle.value = 0.0
        else:
            self.angle = 0.0


# Example usage:
if __name__ == '__main__':
    s = Shifter(data=16, latch=20, clock=21)   # Setup shift register
    lock = multiprocessing.Lock()              # Shared lock for hardware access

    # Instantiate in REVERSE ORDER (Qa–Qd first, Qe–Qh second)
    # Use shared angle so main can read motor positions after movement
    m2 = Stepper(s, lock, use_shared_angle=True)  # Motor 2 uses Qa–Qd (upper bits)
    m1 = Stepper(s, lock, use_shared_angle=True)  # Motor 1 uses Qe–Qh (lower bits)

    # Zero both
    m1.zero()
    m2.zero()

    # Move both simultaneously
    print("Rotating both motors...")

    print("setting m1 90, m2 -90")
    m1.goAngle(90)
    m2.goAngle(-90)
    time.sleep(5)
    print(m1.angle.value)   # shared Value - read .value
    print(m2.angle.value)
    print("setting m1 -45, m2 45")
    m1.goAngle(-45)
    m2.goAngle(45)
    time.sleep(5)
    print(m1.angle.value)
    print(m2.angle.value)
    print("setting m1 -135")
    m1.goAngle(-135)
    time.sleep(5)
    print(m1.angle.value)
    print(m2.angle.value)
    print("setting m1 135")
    m1.goAngle(135)
    time.sleep(5)
    print(m1.angle.value)
    print(m2.angle.value)
    print("set m1 0")
    m1.goAngle(0)

    try:
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nEnd of program.")
