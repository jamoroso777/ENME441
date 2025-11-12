import time
from shifter import Shifter

class Stepper:
    """
    Multi-stepper class using shift registers.
    Each motor uses 4 bits of the shared register.
    """

    seq = [0b0001,0b0011,0b0010,0b0110,0b0100,0b1100,0b1000,0b1001]  # 8-step half-step
    delay = 1200  # microseconds
    steps_per_degree = 1024 / 360  # 1024 steps per rev

    def __init__(self, shifter, shifter_bit_start, lock):
        self.s = shifter
        self.lock = lock
        self.shifter_bit_start = shifter_bit_start
        self.angle = 0.0
        self.step_state = 0

    def __sgn(self, x):
        return 0 if x == 0 else int(abs(x)/x)

    def __step(self, dir):
        # Update step state
        self.step_state = (self.step_state + dir) % 8
        seq_val = Stepper.seq[self.step_state]

        # Write to shift register
        mask = 0b1111 << self.shifter_bit_start
        with self.lock:
            val = self.s.readByte()  # read current register
            val &= ~mask
            val |= seq_val << self.shifter_bit_start
            self.s.shiftByte(val)

        # Update angle
        self.angle = (self.angle + dir / Stepper.steps_per_degree) % 360

    def goAngle(self, target_angle):
        """
        Move motor to target angle along shortest path.
        Blocking.
        """
        delta = (target_angle - self.angle + 540) % 360 - 180
        steps_needed = int(abs(delta) * Stepper.steps_per_degree)
        dir = self.__sgn(delta)

        for _ in range(steps_needed):
            self.__step(dir)
            time.sleep(Stepper.delay / 1e6)

    @staticmethod
    def goAnglesSimultaneous(motors, target_angles):
        """
        Move multiple motors simultaneously (blocking).
        Steps are proportionally distributed.
        """
        # Calculate deltas
        deltas = []
        for m, tgt in zip(motors, target_angles):
            delta = (tgt - m.angle + 540) % 360 - 180
            deltas.append(delta)

        # Steps required per motor
        steps = [abs(d)*Stepper.steps_per_degree for d in deltas]
        max_steps = int(max(steps))

        if max_steps == 0:
            return

        dirs = [Stepper.__sgn(None, d) for d in deltas]

        # Step loop
        for i in range(max_steps):
            for j, m in enumerate(motors):
                # Determine if this motor should step this iteration
                if int(i * steps[j]/max_steps) > int((i-1) * steps[j]/max_steps) if i>0 else 0:
                    m.__step(dirs[j])
            time.sleep(Stepper.delay / 1e6)

    @staticmethod
    def __sgn(self, x):
        return 0 if x == 0 else int(abs(x)/x)

    def zero(self):
        self.angle = 0.0
        self.step_state = 0

# =====================
# Main program
# =====================
if __name__ == "__main__":
    s = Shifter(data=16, latch=20, clock=21)
    lock = s.lock  # assume shifter has a lock, or create one: lock = threading.Lock()

    # Instantiate motors
    m2 = Stepper(s, shifter_bit_start=0, lock=lock)   # Motor2 = Qa-Qd
    m1 = Stepper(s, shifter_bit_start=4, lock=lock)   # Motor1 = Qe-Qh

    # Zero both
    m1.zero()
    m2.zero()
    print(f"Zeroed: Motor1 = {m1.angle:.2f}, Motor2 = {m2.angle:.2f}")

    # First simultaneous move
    Stepper.goAnglesSimultaneous([m1, m2], [90, -90])
    print(f"After goAngle(90/-90): Motor1 = {m1.angle:.2f}, Motor2 = {m2.angle:.2f}")

    # Second simultaneous move
    Stepper.goAnglesSimultaneous([m1, m2], [-45, 45])
    print(f"After goAngle(-45/45): Motor1 = {m1.angle:.2f}, Motor2 = {m2.angle:.2f}")

    # Sequential Motor1 moves
    m1.goAngle(-135)
    print(f"After m1.goAngle(-135): Motor1 = {m1.angle:.2f}, Motor2 = {m2.angle:.2f}")

    m1.goAngle(135)
    print(f"After m1.goAngle(135): Motor1 = {m1.angle:.2f}, Motor2 = {m2.angle:.2f}")

    m1.goAngle(0)
    print(f"After m1.goAngle(0): Motor1 = {m1.angle:.2f}, Motor2 = {m2.angle:.2f}")
