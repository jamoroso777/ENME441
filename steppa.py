# stepper_class_shiftregister_multiprocessing.py
#
# Stepper class with persistent worker processes and command queues.
# Safe simultaneous operation, correct shortest-path rotation, and debug prints.

import time
import multiprocessing
import ctypes
from shifter import Shifter   # custom Shifter class

class Stepper:
    """
    Stepper motor controlled via a shift register.
    Each motor runs its own worker process listening to commands in a queue.
    """

    # Class attributes
    num_steppers = 0
    shifter_outputs = multiprocessing.Value('i', 0)  # shared shift register outputs
    seq = [0b0001, 0b0011, 0b0010, 0b0110, 0b0100, 0b1100, 0b1000, 0b1001]  # 8-step sequence
    delay = 1200  # microseconds between steps
    steps_per_degree = 1024 / 360  # adjust to your motor

    def __init__(self, shifter, lock, name="Stepper"):
        self.s = shifter
        self.lock = lock
        self.name = name
        # Shared state
        self.step_state = multiprocessing.Value(ctypes.c_int, 0)
        self.angle = multiprocessing.Value(ctypes.c_double, 0.0)
        self.shifter_bit_start = 4 * Stepper.num_steppers
        Stepper.num_steppers += 1

        # Command queue
        self.command_queue = multiprocessing.Queue()
        # Start worker process
        self.process = multiprocessing.Process(target=self._worker)
        self.process.daemon = True
        self.process.start()

    # Internal sign function
    def __sgn(self, x):
        return 0 if x == 0 else int(abs(x)/x)

    # Worker process
    def _worker(self):
        while True:
            cmd, value = self.command_queue.get()
            if cmd == "rotate":
                self._do_rotate(value)
            elif cmd == "goAngle":
                self._do_goAngle(value)
            elif cmd == "exit":
                break

    # Step function (internal)
    def _step(self, dir):
        with self.step_state.get_lock():
            self.step_state.value = (self.step_state.value + dir) % 8
            current_step = self.step_state.value

        mask = 0b1111 << self.shifter_bit_start
        with self.lock:
            val = Stepper.shifter_outputs.value
            val &= ~mask
            val |= (Stepper.seq[current_step] << self.shifter_bit_start)
            Stepper.shifter_outputs.value = val
            self.s.shiftByte(val)

        # Update shared angle
        with self.angle.get_lock():
            self.angle.value = (self.angle.value + dir / Stepper.steps_per_degree) % 360
            print(f"[{self.name}] angle: {self.angle.value:.2f}°")  # debug print

    # Blocking relative rotation
    def _do_rotate(self, delta):
        numSteps = int(abs(delta) * Stepper.steps_per_degree)
        dir = self.__sgn(delta)
        for _ in range(numSteps):
            self._step(dir)
            time.sleep(Stepper.delay / 1e6)

    # Blocking absolute rotation to shortest path
    def _do_goAngle(self, target_angle):
        with self.angle.get_lock():
            current = self.angle.value

        # Compute shortest path
        alpha = target_angle - current
        beta  = alpha + 360
        gamma = alpha - 360
        delta = min([alpha, beta, gamma], key=abs)

        # Execute rotation
        self._do_rotate(delta)

    # Public relative rotation (non-blocking)
    def rotate(self, delta):
        self.command_queue.put(("rotate", delta))

    # Public absolute rotation (non-blocking)
    def goAngle(self, target_angle):
        self.command_queue.put(("goAngle", target_angle))

    # Reset zero position
    def zero(self):
        with self.angle.get_lock():
            self.angle.value = 0.0
        with self.step_state.get_lock():
            self.step_state.value = 0

    # Stop worker process
    def stop(self):
        self.command_queue.put(("exit", 0))
        self.process.join()


# Example usage
if __name__ == '__main__':
    s = Shifter(data=16, latch=20, clock=21)
    lock = multiprocessing.Lock()

    # Instantiate motors (Qa–Qd first)
    m1 = Stepper(s, lock, name="Motor1")  # Qe–Qh lower bits
    m2 = Stepper(s, lock, name="Motor2")  # Qa–Qd upper bits

    # Zero both motors
    m1.zero()
    m2.zero()

    # Move motors simultaneously
    m1.goAngle(90)
    m2.goAngle(-90)
    time.sleep(3)
    m1.goAngle(-45)
    m2.goAngle(45)
    time.sleep(3)
    m1.goAngle(-135)
    time.sleep(3)
    m1.goAngle(135)
    time.sleep(3)
    m1.goAngle(0)

    try:
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nStopping motors...")
        m1.stop()
        m2.stop()
        print("End of program.")
