# stepper_class_shiftregister_multiprocessing.py
#
# Stepper class (edited for simultaneous motor operation)
#
# This version allows multiple stepper motors driven by the same shift register
# to move simultaneously. Each motor updates only its own 4-bit region in the
# shared shift register output using proper bitmasking.

import time
import multiprocessing
from shifter import Shifter   # our custom Shifter class

class Stepper:
    """
    Supports operation of an arbitrary number of stepper motors using
    one or more shift registers.

    A class attribute (shifter_outputs) keeps track of all
    shift register output values for all motors.  In addition to
    simplifying sequential control of multiple motors, this schema also
    makes simultaneous operation of multiple motors possible.

    Motor instantiation sequence is inverted from the shift register outputs.
    For example, in the case of 2 motors, the 2nd motor must be connected
    with the first set of shift register outputs (Qa-Qd), and the 1st motor
    with the second set of outputs (Qe-Qh). This is because the MSB of
    the register is associated with Qa, and the LSB with Qh.
    """

    # Class attributes:
    num_steppers = 0      # track number of Steppers instantiated
    shifter_outputs = 0   # track shift register outputs for all motors
    seq = [0b0001,0b0011,0b0010,0b0110,0b0100,0b1100,0b1000,0b1001] # CCW sequence
    delay = 1200          # delay between motor steps [us]
    steps_per_degree = 4096 / 360    # 4096 steps/rev * 1/360 rev/deg

    def __init__(self, shifter, lock):
        self.s = shifter           # shift register
        self.angle = 0             # current output shaft angle
        self.step_state = 0        # track position in sequence
        self.shifter_bit_start = 4 * Stepper.num_steppers  # starting bit position
        self.lock = lock           # multiprocessing lock

        Stepper.num_steppers += 1  # increment the instance count

    # Signum function:
    def __sgn(self, x):
        if x == 0:
            return 0
        else:
            return int(abs(x)/x)

    # Move a single +/-1 step in the motor sequence:
    def __step(self, dir):
        # Update step state
        self.step_state = (self.step_state + dir) % 8

        # Create a 4-bit mask for this motor's output region
        mask = 0b1111 << self.shifter_bit_start

        # Clear this motor's bits, then write the new pattern
        Stepper.shifter_outputs &= ~mask
        Stepper.shifter_outputs |= (Stepper.seq[self.step_state] << self.shifter_bit_start)

        # Safely send the new output to the shift register
        with self.lock:
            self.s.shiftByte(Stepper.shifter_outputs)

        # Update angle tracking
        self.angle = (self.angle + dir / Stepper.steps_per_degree) % 360

    # Move relative angle from current position:
    def __rotate(self, delta):
        numSteps = int(Stepper.steps_per_degree * abs(delta))
        dir = self.__sgn(delta)
        for _ in range(numSteps):
            self.__step(dir)
            time.sleep(Stepper.delay / 1e6)

    # Public method for rotation using multiprocessing
    def rotate(self, delta):
        time.sleep(0.05)
        p = multiprocessing.Process(target=self.__rotate, args=(delta,))
        p.start()

    # Move to an absolute angle taking the shortest possible path:
    def goAngle(self, target_angle):
        # Compute shortest rotation direction
        delta = (target_angle - self.angle + 540) % 360 - 180
        self.rotate(delta)

    # Set the motor zero point
    def zero(self):
        self.angle = 0


# Example use:

if __name__ == '__main__':
    s = Shifter(data=16, latch=20, clock=21)   # set up Shifter

    # Use multiprocessing.Lock() to prevent write collisions
    lock = multiprocessing.Lock()

    # Instantiate 2 Steppers:
    m2 = Stepper(s, lock)
    m1 = Stepper(s, lock)

    # Zero the motors:
    m1.zero()
    m2.zero()

    # Move both simultaneously:
    m1.rotate(180)
    m2.rotate(-90)

    # While motors are running, main can continue doing other work
    try:
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        print('\nEnd of program.')
