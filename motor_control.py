# File: motor_control.py
# Description: Driver for the DC Motor/Fan using a 2-pin Sign-Magnitude control scheme.
#              This version swaps the control roles defined in config.py to match
#              the physical 2-pin wiring (GP16 and GP17).
#
# ASSUMPTION:
# - GP17 (IN1_PIN) is used for PWM (Speed).
# - GP16 (MOTOR_PWM_PIN) is used for Direction (HIGH/LOW).
# - GP18 (IN2_PIN) is ignored.

from machine import Pin, PWM
import config
import time

# Safely load configuration settings
try:
    PWM_FREQ = config.MOTOR_PWM_FREQUENCY
    # We load the pins as defined, but will use them in swapped roles below.
    DIR_PIN = config.MOTOR_PWM_PIN  # GP16 is now the Direction Pin
    PWM_PIN = config.MOTOR_IN1_PIN  # GP17 is now the PWM Pin
    IN2_PIN = config.MOTOR_IN2_PIN  # GP18 is still defined but unused
except AttributeError as e:
    # Use safe defaults if config is missing the variable
    if 'MOTOR_PWM_FREQUENCY' in str(e):
        PWM_FREQ = 1000
    if 'MOTOR_PWM_PIN' in str(e):
        DIR_PIN = 16
    if 'MOTOR_IN1_PIN' in str(e):
        PWM_PIN = 17
    if 'MOTOR_IN2_PIN' in str(e):
        IN2_PIN = 18 
    print(f"[WARN] Config variable missing in motor_control: {e}. Using internal default.")

class MotorDriver:
    
    def __init__(self):
        # 1. Direction Pin (GP16)
        self.dir_pin = Pin(DIR_PIN, Pin.OUT)
        
        # 2. PWM Pin (GP17)
        self.pwm = PWM(Pin(PWM_PIN))
        self.pwm.freq(PWM_FREQ)
        
        # 3. Unused Pin (GP18) - Initialize and keep LOW
        self.unused_pin = Pin(IN2_PIN, Pin.OUT)
        
        # Set initial state to stopped
        self.dir_pin.value(0) 
        self.unused_pin.value(0)
        self.pwm.duty_u16(0) 

    def _set_speed(self, speed_percent):
        """Sets the PWM duty cycle based on a percentage (0-100) on GP17."""
        speed_percent = max(0, min(100, speed_percent))
        duty = int(speed_percent * 65535 / 100)
        self.pwm.duty_u16(duty)

    def forward(self, speed_percent):
        """Sets the motor to run forward (GP16 LOW, GP17 PWM) at the specified speed."""
        
        # 1. Set Direction (Forward - assuming LOW on GP16 is forward)
        self.dir_pin.value(0) # Direction Pin LOW
        self.unused_pin.value(0) # Keep GP18 LOW

        # 2. Set Speed (PWM on GP17)
        self._set_speed(speed_percent)

    def stop(self):
        """Stops the motor by holding the PWM pin low."""
        self.dir_pin.value(0) 
        self.unused_pin.value(0)
        self._set_speed(0)

    def reverse(self, speed_percent):
        """Sets the motor to run reverse (GP16 HIGH, GP17 PWM) at the specified speed."""
        
        # 1. Set Direction (Reverse - assuming HIGH on GP16 is reverse)
        self.dir_pin.value(1) # Direction Pin HIGH
        self.unused_pin.value(0) # Keep GP18 LOW
        
        # 2. Set Speed (PWM on GP17)
        self._set_speed(speed_percent)