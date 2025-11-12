# stepper_class_shiftregister_multiprocessing.py
#
# Stepper class
#
# Because only one motor action is allowed at a time, multithreading could be
# used instead of multiprocessing. However, the GIL makes the motor process run 
# too slowly on the Pi Zero, so multiprocessing is needed.
import RPi.GPIO as GPIO
import time
import multiprocessing
import math
from shifter import Shifter   # our custom Shifter class

# signed shortest delta in (−180, 180]
def _shortest_delta(current_deg: float, target_deg: float) -> float:
    return math.remainder(float(target_deg) - float(current_deg), 360.0)


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
    the register is associated with Qa, and the LSB with Qh (look at the code
    to see why this makes sense).
 
    An instance attribute (shifter_bit_start) tracks the bit position
    in the shift register where the 4 control bits for each motor
    begin.
    """

    # Class attributes:
    num_steppers = 0      # track number of Steppers instantiated
    shifter_outputs = multiprocessing.Value('i',0)   # track shift register outputs for all motors
    seq = [0b0001,0b0011,0b0010,0b0110,0b0100,0b1100,0b1000,0b1001] # CCW sequence
    delay = 1200          # delay between motor steps [us]
    steps_per_degree = 4096/360    # 4096 steps/rev * 1/360 rev/deg

    def __init__(self, shifter, lock):
        self.s = shifter           # shift register
        self.angle = multiprocessing.Value('d',0.0) # current output shaft as shared double
        self.step_state = 0        # track position in sequence
        self.shifter_bit_start = 4*Stepper.num_steppers  # starting bit position
        self.lock = lock           # multiprocessing lock
        
        Stepper.num_steppers += 1   # increment the instance count

        self.queue = multiprocessing.Queue()        # creates queue system for multiple rotate commands
        self.worker = multiprocessing.Process(target=self.__worker_loop)
        self.worker.daemon = True
        self.worker.start()

    # Signum function:
    def __sgn(self, x):
        if x == 0: return(0)
        else: return(int(abs(x)/x))

    # Move a single +/-1 step in the motor sequence:
    def __step(self, dir):
        self.step_state += dir    # increment/decrement the step
        self.step_state %= 8      # ensure result stays in [0,7]
        
        with Stepper.shifter_outputs.get_lock():        # requires lock on outputs
            current_output = Stepper.shifter_outputs.value      # copies old outputs
            mask = 0b1111 << self.shifter_bit_start     # write 1s for this motor
            new_output = (current_output & ~mask) | (Stepper.seq[self.step_state] << self.shifter_bit_start)       # clear this motors bits
            Stepper.shifter_outputs.value = new_output      # copy the new output to shared variable
            self.s.shiftByte(Stepper.shifter_outputs.value)     # execute the output to shift register
            
        with self.angle.get_lock():     # require lock on angle for this motor
            self.angle.value += dir/Stepper.steps_per_degree
            self.angle.value %= 360     # limit to [0,359.9+] range

    # Move relative angle from current position:
    def __rotate(self, delta):
        with self.lock:     # require lock for this motor
            numSteps = int(Stepper.steps_per_degree * abs(delta))    # find the right # of steps
            dir = self.__sgn(delta)        # find the direction (+/-1)
            for s in range(numSteps):      # take the steps
                self.__step(dir)
                time.sleep(Stepper.delay/1e6)

    def __worker_loop(self):
        while True:
            cmd, val = self.queue.get()   # ("rel", delta) or ("abs", target)
            if cmd == "rel":
                self.__rotate(val)
            else:  # "abs"
                with self.angle.get_lock():
                    current = self.angle.value
                delta = _shortest_delta(current, val)
                self.__rotate(delta)

            
    # Move relative angle from current position:
    def rotate(self, delta):
        self.queue.put(("rel", float(delta)))          # queue relative move

    def goAngle(self, target_angle):
        self.queue.put(("abs", float(target_angle)))   # queue absolute target


    # Set the motor zero point
    def zero(self):     # set shared angle for this motor to 0
        with self.angle.get_lock():
            self.angle.value = 0.0
        self.step_state = 0


# Example use:

if __name__ == '__main__':

    s = Shifter(data=16,latch=20,clock=21)   # set up Shifter

    # Use multiprocessing.Lock() to prevent motors from trying to 
    # execute multiple operations at the same time:
    lock1 = multiprocessing.Lock()      # motor lock 1
    lock2 = multiprocessing.Lock()      # motor lock 2

    # Instantiate 2 Steppers:
    m1 = Stepper(s, lock1)
    m2 = Stepper(s, lock2)

    m1.zero()
    m2.zero()
    
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
        pass
    
    finally:
        s.shiftByte(0)      # clear outputs
        time.sleep(0.1)
        GPIO.cleanup()
        print('\nend')