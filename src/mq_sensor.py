# File: mq_sensor.py
# Description: Resilient MQ-series gas sensor driver (MQ-7 CO / MQ-135 air quality)
# Analog output only - reads AO pin via ADC, DO pin for threshold alert.
# Follows the hot-swap resilience pattern of the rtc_logger project.

from machine import ADC, Pin
import math
import time


class MQSensor:

    def __init__(self, ao_pin=26, do_pin=1):
        self.ao_pin_num = ao_pin
        self.do_pin_num = do_pin
        self.ao = ADC(Pin(ao_pin))
        self.do = Pin(do_pin, Pin.IN)
        self.R0 = None
        self.working = False

    def calibrate(self, samples=30, log_fn=None):
        """
        Read the sensor in clean air for `samples` seconds to establish R0 baseline.
        Optionally pass a log_fn (e.g. self._log_activity) for logging.
        """
        if log_fn:
            log_fn(f"MQ SENSOR: Calibrating over {samples} seconds in clean air...", timestamp=True)
        readings = []
        for i in range(samples):
            readings.append(self.ao.read_u16())
            time.sleep(1)
        self.R0 = sum(readings) / len(readings)
        self.working = True
        if log_fn:
            log_fn(f"MQ SENSOR: Calibration complete. R0={self.R0:.1f}", timestamp=True)
        return self.R0

    def read(self):
        """
        Returns (raw, ppm, alert) where:
          raw   = 0-65535 ADC value
          ppm   = estimated CO PPM (None if not calibrated)
          alert = DO pin value (0 = threshold exceeded, 1 = normal)
        """
        try:
            raw = self.ao.read_u16()
            do_val = self.do.value()
            ppm = None
            if self.R0 and self.R0 > 0:
                ratio = raw / self.R0
                # MQ-7 CO sensitivity curve from datasheet
                ppm = round(100 * math.pow(ratio / 1.001, -1.458), 1)
            self.working = True
            return raw, ppm, do_val
        except Exception as e:
            self.working = False
            return None, None, None

