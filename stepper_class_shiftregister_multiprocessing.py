# stepper_class_shiftregister_multiprocessing.py
#
# Stepper class for Lab 8 – simultaneous multi-motor control
#
# Uses multiprocessing and shared memory to coordinate
# multiple steppers connected through one or more shift registers.

import time
import multiprocessing
from shifter import Shifter   # custom Shifter class

class Stepper:
    """
    Supports operation of an arbitrary number of stepper motors using
    one or more shift registers.

    A class attribute (shifter_outputs) keeps track of all
    shift register output values for all motors. This schema allows
    simultaneous operation of multiple motors since each modifies only
    its assigned bits in the shared output word.
    """

    # Class attributes
    num_steppers = 0
    shifter_outputs = 0
    seq = [0b0001, 0b0011, 0b0010, 0b0110,
           0b0100, 0b1100, 0b1000, 0b1001]  # 8-step CCW sequence
    delay = 1200            # step delay [µs]
    steps_per_degree = 4096 / 360.0  # 4096 steps/rev * 1/360 rev/deg

    def __init__(self, shifter, lock):
        self.s = shifter
        self.angle = multiprocessing.Value('d', 0.0)   # shared double
        self.step_state = 0
        self.shifter_bit_start = 4 * Stepper.num_steppers
        self.lock = lock

        Stepper.num_steppers += 1

    # ----------------- Private helper methods -----------------

    def __sgn(self, x):
        if x == 0:
            return 0
        return int(abs(x) / x)

    def __step(self, dir):
        """Perform one step in given direction (+1 or -1)."""
        self.step_state += dir
        self.step_state %= 8

        # Create mask for this motor's 4 control bits
        mask = 0b1111 << self.shifter_bit_start

        # Clear current bits for this motor only
        Stepper.shifter_outputs &= ~mask

        # Insert new step pattern bits
        Stepper.shifter_outputs |= Stepper.seq[self.step_state] << self.shifter_bit_start

        # Send to shift register
        self.s.shiftByte(Stepper.shifter_outputs)

        # Update shared angle
        self.angle.value += dir / Stepper.steps_per_degree
        self.angle.value %= 360.0  # keep in [0, 360)

    def __rotate(self, delta):
        """Rotate motor by delta degrees relative to current position."""
        # Acquire lock if provided (optional — can be shared or independent)
        self.lock.acquire()
        try:
            numSteps = int(Stepper.steps_per_degree * abs(delta))
            direction = self.__sgn(delta)
            for _ in range(numSteps):
                self.__step(direction)
                time.sleep(Stepper.delay / 1e6)
        finally:
            self.lock.release()

    # ----------------- Public methods -----------------

    def rotate(self, delta):
        """Rotate motor relative to current position in a separate process."""
        time.sleep(0.1)
        p = multiprocessing.Process(target=self.__rotate, args=(delta,))
        p.start()

    def goAngle(self, target):
        """
        Move motor to an absolute target angle using the shortest path.
        """
        # Compute smallest signed angle difference (-180 to +180)
        delta = target - self.angle.value
        delta = (delta + 180) % 360 - 180

        # Launch rotation process
        p = multiprocessing.Process(target=self.__rotate, args=(delta,))
        p.start()

    def zero(self):
        """Set current motor angle as zero."""
        self.angle.value = 0.0


# ----------------- Example usage -----------------
if __name__ == '__main__':
    from shifter import Shifter
    import multiprocessing
    import time

    # Initialize shift register (adjust pins to match your wiring)
    s = Shifter(data=16, latch=20, clock=21)

    # Create separate locks so both motors can step simultaneously
    lock1 = multiprocessing.Lock()
    lock2 = multiprocessing.Lock()

    # Instantiate two independent stepper motors
    m1 = Stepper(s, lock1)
    m2 = Stepper(s, lock2)

    # Zero both motors
    m1.zero()
    m2.zero()

    print("Starting simultaneous goAngle() test...")
    time.sleep(1)

    # === Lab 8 Command Sequence ===
    # Both motors should move concurrently where applicable
    m1.goAngle(90)
    m1.goAngle(-45)

    m2.goAngle(-90)
    m2.goAngle(45)

    m1.goAngle(-135)
    m1.goAngle(135)
    m1.goAngle(0)

    # Keep program alive while motors move
    try:
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nDemo complete — stopping motors.")
