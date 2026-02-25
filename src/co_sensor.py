# co_sensor.py
# Integrated CO Sensor Module for Resilient Fan Project
# Handles MQ7 CO sensor readings and OLED display updates

from machine import Pin, ADC
import time
from mq7 import MQ7

class COSensor:
    """CO Sensor Interface - manages MQ7 readings and display updates"""
    
    def __init__(self, ao_pin=26, do_pin=1, display=None):
        """
        Initialize CO sensor
        
        Args:
            ao_pin: Analog output pin (GPIO 26 - ADC0)
            do_pin: Digital output pin (GPIO 1)
            display: Optional display object for OLED updates
        """
        self.ao_pin = ao_pin
        self.do_pin = do_pin
        self.display = display
        
        # Setup MQ7 sensor (analog reading)
        self.mq7_ao = ADC(Pin(ao_pin))
        
        # Setup digital alert pin
        self.mq7_do = Pin(do_pin, Pin.IN)
        
        # Last readings for display rotation
        self.last_raw = 0
        self.last_alert = 0
        self.co_ppm = 0.0
        
    def read_raw(self):
        """Read raw ADC value from MQ7 analog output (0-65535 on Pico)"""
        self.last_raw = self.mq7_ao.read_u16()
        return self.last_raw
    
    def read_alert(self):
        """Read digital alert status from MQ7"""
        self.last_alert = self.mq7_do.value()
        return self.last_alert
    
    def read_all(self):
        """Read both analog and digital values"""
        raw = self.read_raw()
        alert = self.read_alert()
        return {'raw': raw, 'alert': alert}
    
    def get_co_concentration(self):
        """
        Get estimated CO concentration (simplified calculation)
        In a real application, you'd use the MQ7 calibration curves
        """
        # Rough conversion from raw ADC to ppm (this is simplified)
        # MQ7 outputs 0.4V for 100ppm CO in 5V system
        # On Pico: 65535 = 3.3V (or 5V depending on Pico config)
        raw = self.last_raw
        # Convert to voltage (assuming 3.3V range)
        voltage = (raw / 65535.0) * 3.3
        # Rough linear approximation (should use calibration curve for accuracy)
        ppm = (voltage - 0.4) / 0.003  # Rough scaling
        self.co_ppm = max(0, ppm)  # Don't allow negative values
        return self.co_ppm
    
    def display_update_line_1(self):
        """Display first line of CO data - Raw value"""
        if self.display:
            self.display.fill(0)
            self.display.text('CO Sensor', 0, 0, 1)
            self.display.text('Raw: ' + str(self.last_raw), 0, 20, 1)
            self.display.show()
            return True
        return False
    
    def display_update_line_2(self):
        """Display second line of CO data - Alert status"""
        if self.display:
            self.display.fill(0)
            self.display.text('CO Sensor', 0, 0, 1)
            alert_text = 'ALERT!' if self.last_alert else 'Safe'
            self.display.text('Alert: ' + alert_text, 0, 20, 1)
            self.display.show()
            return True
        return False
    
    def display_update_combined(self):
        """Display both raw and alert on screen
        For use when you have enough OLED space"""
        if self.display:
            self.display.fill(0)
            self.display.text('CO Sensor', 0, 0, 1)
            self.display.text('Raw: ' + str(self.last_raw), 0, 16, 1)
            alert_text = 'ALERT!' if self.last_alert else 'Safe'
            self.display.text('Status: ' + alert_text, 0, 32, 1)
            self.display.show()
            return True
        return False
    
    def display_update_with_rotation(self, cycle_count, rotation_interval=2):
        """Rotate display between raw value and alert status
        Updates based on cycle count to swap every N cycles
        
        Args:
            cycle_count: Current iteration count
            rotation_interval: Number of cycles before switching display
        """
        if self.display:
            if (cycle_count // rotation_interval) % 2 == 0:
                self.display_update_line_1()
            else:
                self.display_update_line_2()
    
    def print_all(self):
        """Print all sensor values to console"""
        print(f'CO Raw: {self.last_raw} | Alert: {self.last_alert}')


# Example usage in main loop
def co_sensor_loop(co_sensor, display=None, loop_count=0):
    """Integrate into your main loop
    Usage in rtc_logger or main:
        co = COSensor(ao_pin=26, do_pin=1, display=oled)
        # In your main loop:
        co_sensor_loop(co, display=oled, loop_count=i)
    """
    # Read sensor
    co_sensor.read_all()
    
    # Print to console
    co_sensor.print_all()
    
    # Update display (with rotation if OLED space is limited)
    co_sensor.display_update_with_rotation(loop_count, rotation_interval=2)