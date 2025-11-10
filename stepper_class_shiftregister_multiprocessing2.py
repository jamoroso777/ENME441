# stepper_class_shiftregister_multiprocessing.py
#
# Updated Stepper class for Lab 8
# - Uses shiftWord(...) to write all shift-register bits
# - Uses multiprocessing.Value for shared angle
# - Prints debugging info at each step and at rotate start
# - Masks each motor's 4 bits to avoid overwriting other motors

import time
import multiprocessing
from shifter import Shifter   # custom Shifter class (must implement shiftWord)

class Stepper:
    """
    Stepper class supporting multiple steppers sharing chained shift registers.
    Each motor uses 4 bits. Class attribute shifter_outputs holds the full
    output word for all motors; each motor only updates its own 4-bit section.
    """

    # Class attributes
    num_steppers = 0
    shifter_outputs = 0
    seq = [0b0001, 0b0011, 0b0010, 0b0110,
           0b0100, 0b1100, 0b1000, 0b1001]  # 8-step CCW sequence
    delay = 1200            # microseconds between steps
    steps_per_degree = 4096.0 / 360.0

    def __init__(self, shifter, lock):
        self.s = shifter
        # angle is shared across processes
        self.angle = multiprocessing.Value('d', 0.0)
        self.step_state = 0
        # assign block of 4 bits to this motor (0-based)
        self.shifter_bit_start = 4 * Stepper.num_steppers
        # store a friendly motor id for debugging (1-based)
        self.motor_id = (self.shifter_bit_start // 4) + 1
        self.lock = lock

        Stepper.num_steppers += 1

    # simple sign function
    def __sgn(self, x):
        if x == 0:
            return 0
        return int(abs(x) / x)

    def __step(self, dir):
        """
        Perform one step (dir is +1 or -1).
        Update only this motor's 4 bits in the shared shifter_outputs,
        then write the entire output word to the chained shift registers.
        """
        # advance step state
        self.step_state = (self.step_state + dir) % len(Stepper.seq)

        # mask for this motor's 4 bits
        mask = 0b1111 << self.shifter_bit_start

        # clear only this motor's bits
        Stepper.shifter_outputs &= ~mask

        # set this motor's bits according to current step state
        Stepper.shifter_outputs |= (Stepper.seq[self.step_state] << self.shifter_bit_start)

        # write the full word to the shift registers:
        # number of bits = 4 bits per motor * number of motors instantiated
        total_bits = max(8, Stepper.num_steppers * 4)  # at least 8 for single register
        # use shiftWord to send arbitrary-length word to chained shift registers
        self.s.shiftWord(Stepper.shifter_outputs, total_bits)

        # update shared angle (in degrees)
        self.angle.value += dir / Stepper.steps_per_degree
        self.angle.value %= 360.0

    def __rotate(self, delta):
        """
        Rotate by delta degrees (signed). Runs in a separate process.
        Debug prints included: start of rotation and after each step.
        """
        # compute absolute target angle for useful debug messages
        start_angle = self.angle.value
        target_angle = (start_angle + delta) % 360.0

        # announce rotation
        print(f"[Motor {self.motor_id}] START rotate: delta={delta:.2f}°, start={start_angle:.2f}°, "
              f"target={target_angle:.2f}°", flush=True)

        # Acquire lock (if using shared lock behavior). If you want true parallel
        # motion, give each motor its own lock in main.
        self.lock.acquire()
        try:
            numSteps = int(abs(delta) * Stepper.steps_per_degree)
            direction = self.__sgn(delta)
            for step_num in range(1, numSteps + 1):
                self.__step(direction)
                # debug: print angle after each step
                print(f"[Motor {self.motor_id}] step {step_num}/{numSteps} -> angle={self.angle.value:.2f}°",
                      flush=True)
                time.sleep(Stepper.delay / 1e6)
        finally:
            self.lock.release()
            # final angle report
            print(f"[Motor {self.motor_id}] DONE rotate: final angle={self.angle.value:.2f}° (intended {target_angle:.2f}°)",
                  flush=True)

    # Public API ----------------------------------------------------------

    def rotate(self, delta):
        """Start a relative rotation by delta degrees in a new process."""
        time.sleep(0.1)
        p = multiprocessing.Process(target=self.__rotate, args=(delta,))
        p.start()
        return p

    def goAngle(self, target):
        """Move to absolute target angle using the shortest path. Runs in separate process."""
        # calculate shortest signed delta in range (-180, 180]
        current = self.angle.value
        delta = target - current
        # normalize to [-180, 180)
        delta = (delta + 180.0) % 360.0 - 180.0

        print(f"[Motor {self.motor_id}] goAngle called: target={target:.2f}°, current={current:.2f}°, delta(shortest)={delta:.2f}°",
              flush=True)

        p = multiprocessing.Process(target=self.__rotate, args=(delta,))
        p.start()
        return p

    def zero(self):
        """Set current angle to zero (shared)."""
        self.angle.value = 0.0
        print(f"[Motor {self.motor_id}] zeroed (angle set to 0.0°)", flush=True)


# ---------------- Example usage / test harness ----------------
if __name__ == '__main__':
    import time

    # Setup: adjust pins to match your wiring
    s = Shifter(data=16, clock=21, latch=20)

    # Use separate locks for true concurrent motion (give each motor its own lock)
    lock1 = multiprocessing.Lock()
    lock2 = multiprocessing.Lock()

    # Instantiate motors
    m1 = Stepper(s, lock1)
    m2 = Stepper(s, lock2)

    # Zero motors
    m1.zero()
    m2.zero()

    time.sleep(0.5)
    print("=== Starting lab test sequence with goAngle() ===", flush=True)

    # Lab sequence (as required)
    m1.goAngle(90)
    m1.goAngle(-45)

    m2.goAngle(-90)
    m2.goAngle(45)

    m1.goAngle(-135)
    m1.goAngle(135)
    m1.goAngle(0)

    # Keep main alive so background processes can run
    try:
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nDemo interrupted by user. Exiting.", flush=True)
