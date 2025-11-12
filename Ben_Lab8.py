# stepper_class_shiftregister_multiprocessing_child_delta_shared_angle_parallel.py
#
# Version:
# - Each motor executes its commands sequentially (internal worker process)
# - Both motors run concurrently (parallel operation)
# - Uses multiprocessing.Value for shared angle and Lock for hardware safety

import multiprocessing
from shifter import Shifter  # your custom hardware class


class Stepper:
    num_steppers = 0
    shifter_outputs = multiprocessing.Value('i', 0)
    seq = [0b0001, 0b0011, 0b0010, 0b0110,
           0b0100, 0b1100, 0b1000, 0b1001]
    delay = 1200  # µs between steps
    steps_per_degree = 1024.0 / 360.0

    def __init__(self, shifter, hw_lock):
        self.s = shifter
        self.lock = hw_lock
        self.angle = multiprocessing.Value('d', 0.0)
        self.step_state = 0
        self.shifter_bit_start = 4 * Stepper.num_steppers
        Stepper.num_steppers += 1

        # Each stepper has its own command queue and worker process
        self.cmd_queue = multiprocessing.Queue()
        self.worker = multiprocessing.Process(target=self.__worker_loop)
        self.worker.start()

    def __sgn(self, x):
        return 0 if x == 0 else int(abs(x) / x)

    def __step(self, direction):
        """Perform one low-level step and update shared angle."""
        self.step_state = (self.step_state + direction) % len(Stepper.seq)
        mask = 0b1111 << self.shifter_bit_start

        # Update the shared shift register byte and shift out
        with self.lock:
            val = Stepper.shifter_outputs.value
            val &= ~mask
            val |= (Stepper.seq[self.step_state] << self.shifter_bit_start)
            Stepper.shifter_outputs.value = val
            self.s.shiftByte(val)

        # Update angle (degrees)
        delta_deg = direction / Stepper.steps_per_degree
        with self.angle.get_lock():
            self.angle.value = (self.angle.value + delta_deg) % 360.0

    def __rotate_to(self, target_angle):
        """Rotate to target_angle (blocking inside worker)."""
        with self.angle.get_lock():
            current = self.angle.value

        delta = (target_angle - current + 540.0) % 360.0 - 180.0
        direction = self.__sgn(delta)
        num_steps = int(abs(delta) * Stepper.steps_per_degree)

        for _ in range(num_steps):
            self.__step(direction)
            # optional small delay:
            # time.sleep(Stepper.delay / 1e6)

        with self.angle.get_lock():
            self.angle.value = target_angle % 360.0

    def __worker_loop(self):
        """Background process that executes queued angle commands."""
        while True:
            target = self.cmd_queue.get()
            if target is None:
                break  # Exit signal
            self.__rotate_to(target)

    def goAngle(self, target_angle):
        """Queue a new target angle for this motor."""
        self.cmd_queue.put(float(target_angle))

    def zero(self):
        """Zero the shared angle."""
        with self.angle.get_lock():
            self.angle.value = 0.0

    def close(self):
        """Gracefully stop the worker."""
        self.cmd_queue.put(None)
        self.worker.join()


# === Example usage ===
if __name__ == '__main__':
    s = Shifter(data=16, latch=20, clock=21)
    hw_lock = multiprocessing.Lock()

    m2 = Stepper(s, hw_lock)
    m1 = Stepper(s, hw_lock)

    m1.zero()
    m2.zero()

    # enqueue commands for each motor — they’ll run concurrently
    m1.goAngle(90)
    m1.goAngle(-45)
    m1.goAngle(-135)
    m1.goAngle(135)
    m1.goAngle(0)

    m2.goAngle(-90)
    m2.goAngle(45)

    print("Motors running concurrently — waiting for completion...")

    # Wait until queues are empty
    m1.cmd_queue.join_thread()
    m2.cmd_queue.join_thread()

    # stop workers
    m1.close()
    m2.close()

    print("\nFinal angles:")
    print("m1 angle (deg):", m1.angle.value)
    print("m2 angle (deg):", m2.angle.value)
