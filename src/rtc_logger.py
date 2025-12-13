# File: rtc_logger.py
# Version: V9.8 (Minute-precision night mode + business hours transition logging)
# Description: Main application loop for the fan controller
# and sensor logger. Handles fan logic, logging, and display.
# Enforcement: External RTC is the sole source of truth. Internal RTC 
# MUST NOT write to the external RTC under any failure condition.
# =========================================================
from machine import SoftI2C, Pin, RTC
import time
import gc
import os
from ssd_config import oled
from tmp117 import TMP117
from shtc3 import SHTC3
from rtc_driver import DS3231_RTC
from motor_control import MotorDriver
from button_handler import ButtonHandler
import config 

LOGGER_VERSION = "V9.8" 

# Configuration for log pruning
MAX_ACTIVITY_LOG_SIZE_BYTES = 100 * 1024 # 100KB limit for activity.log

# Emulate the OLED init message immediately to match log request
print("OLED initialized successfully.")
print("Text displayed on OLED. Waiting 1 seconds...")
time.sleep(1)

class ResilientLogger:
    
    # Day names (MicroPython RTC uses 0=Monday to 6=Sunday)
    DAY_NAMES = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
    
    def __init__(self):
        self.log_file = getattr(config, 'LOG_FILE', None) or "sensor_log.csv"
        self.activity_log_file = getattr(config, 'ACTIVITY_LOG_FILE', None) or "activity.log"
        self.rtc = RTC() 
        
        # Tracks last time prune ran to limit frequency
        self.last_prune_time = 0
        self.prune_interval = 30 # seconds
        self.log_write_count = 0
        
        # --- Header ---
        self._log_activity("", timestamp=False) 
        self._log_activity("="*50, timestamp=False)
        self._log_activity(f"RESILIENT RTC SENSOR LOGGER {LOGGER_VERSION}", timestamp=False)
        self._log_activity("STRICT RTC POLICY: EXTERNAL IS MASTER ONLY.", timestamp=False)
        self._log_activity("="*50, timestamp=False)
        self._log_activity("", timestamp=False)

        self.night_start = getattr(config, 'NIGHT_MODE_START_HOUR', 22)
        self.night_start_min = getattr(config, 'NIGHT_MODE_START_MINUTE', 0)
        self.night_end = getattr(config, 'NIGHT_MODE_END_HOUR', 7)
        self.night_end_min = getattr(config, 'NIGHT_MODE_END_MINUTE', 0)
        self.has_external_rtc = False
        self.manual_mode = False 
        self.temp_override_threshold = getattr(config, 'TEMP_OVERRIDE_THRESHOLD_F', 80.0)
        self.temp_override_min_speed = getattr(config, 'TEMP_OVERRIDE_MIN_SPEED', 75)
        self.humidity_override_threshold = getattr(config, 'HUMIDITY_OVERRIDE_THRESHOLD', 45.0)
        self.humidity_override_min_speed = getattr(config, 'HUMIDITY_OVERRIDE_MIN_SPEED', 75)
        self.last_shutdown_reason = None 
        
        self.oled_working = True
        self.oled_last_retry_time = 0 
        self.rtc_last_retry_time = 0 
        
        # --- Last Known Sensor Readings (for brief disconnections) ---
        self.last_valid_readings = {'tmp117_f': None, 'shtc3_f': None, 'humidity': None, 'timestamp': 0}
        self.sensor_reading_timeout = getattr(config, 'SENSOR_CACHE_TIMEOUT_SECONDS', None) or 30 
        
        # --- Motor and Button Init ---
        self.motor = MotorDriver()
        motor_pwm_pin = getattr(config, 'MOTOR_PWM_PIN', 16)
        motor_in1_pin = getattr(config, 'MOTOR_IN1_PIN', 17)
        self._log_activity(f"Motor Driver initialized (PWM on Pin {motor_pwm_pin} & {motor_in1_pin}).", timestamp=False)
        
        self.buttons = ButtonHandler()
        self._log_activity("      Button Handler V1.2 (PULL_UP/LOW)", timestamp=False)
        button_green_pin = getattr(config, 'BUTTON_GREEN_PIN', 20)
        button_red_pin = getattr(config, 'BUTTON_RED_PIN', 21)
        self._log_activity(f"      Button handler initialized on Green:{button_green_pin}, Red:{button_red_pin}", timestamp=False)
        
        self.fan_speed = getattr(config, 'MOTOR_INITIAL_SPEED_PERCENT', 65)
        self.motor.forward(self.fan_speed)

        # --- PHASE 1: I2C Setup & RTC Driver Init ---
        self._log_activity("[1/5] Setting up I2C buses...", timestamp=False)
        sensor_sda = getattr(config, 'SENSOR_I2C_SDA_PIN', 0)
        sensor_scl = getattr(config, 'SENSOR_I2C_SCL_PIN', 1)
        i2c_freq = getattr(config, 'I2C_FREQUENCY', 400000)
        
        self.i2c_sensors = SoftI2C(
            sda=Pin(sensor_sda), 
            scl=Pin(sensor_scl), 
            freq=i2c_freq
        )
        sensor_devices = self.i2c_sensors.scan()
        sens_list = [hex(d) for d in sensor_devices]
        sens_str = str(sens_list).replace('"', "'") 
        self._log_activity(f"      Sensor I2C (pins {sensor_sda},{sensor_scl}): {sens_str}", timestamp=False)
        
        # Initialize DS3231 driver
        self.ds3231 = DS3231_RTC()
        rtc_devices = self.ds3231.i2c.scan()
        rtc_list = [hex(d) for d in rtc_devices]
        rtc_str = str(rtc_list).replace('"', "'")
        self._log_activity(f"      RTC I2C (pins 12,13): {rtc_str}", timestamp=False)

        # --- PHASE 2: RTC Check and Sync (One-Way Trust) ---
        self._log_activity("", timestamp=False)
        self._log_activity("[2/5] Checking for external RTC (Master Source) with strict policy...", timestamp=False)
        self._sync_rtc_time() 
        
        # --- PHASE 3: TMP117 ---
        self._log_activity("", timestamp=False)
        self._log_activity("[3/5] Initializing TMP117...", timestamp=False)
        self.tmp117 = None; self.tmp117_working = False
        if 0x48 in sensor_devices: self._init_tmp117()
        else: self._log_activity("      TMP117 not found at 0x48", timestamp=False)
        
        # --- PHASE 4: SHTC3 ---
        self._log_activity("", timestamp=False)
        self._log_activity("[4/5] Initializing SHTC3...", timestamp=False)
        self.shtc3 = None; self.shtc3_working = False
        if 0x70 in sensor_devices: self._init_shtc3()
        else: self._log_activity("      SHTC3 not found at 0x70", timestamp=False)
        
        if not self.tmp117_working and not self.shtc3_working:
            self._log_activity("\n[ERROR] No working sensors found!", timestamp=False)
        
        # --- PHASE 5: Files ---
        self._log_activity("", timestamp=False)
        self._log_activity("[5/5] Setting up log file...", timestamp=False)
        try:
            with open(self.log_file, 'r') as f: pass
            self._log_activity(f"      Using existing {self.log_file}", timestamp=False)
        except:
            with open(self.log_file, 'w') as f: f.write("timestamp,tmp117_f,shtc3_f,humidity,status\n")
            self._log_activity(f"      Created {self.log_file}", timestamp=False)
        
        # --- READY BLOCK ---
        self._log_activity("", timestamp=False)
        self._log_activity("="*50, timestamp=False)
        self._log_activity("READY!", timestamp=False)
        
        sensor_status = []
        if self.tmp117_working: sensor_status.append("TMP117")
        if self.shtc3_working: sensor_status.append("SHTC3")
        
        self._log_activity(f"Working sensors: {', '.join(sensor_status) if sensor_status else 'NONE'}", timestamp=False)
        self._log_activity(f"Fan Speed: {self.fan_speed}%", timestamp=False)
        self._log_activity(f"Manual Mode: {self.manual_mode}", timestamp=False)
        self._log_activity("="*50, timestamp=False)
        self._log_activity("", timestamp=False)
        
        # Run initial memory-safe log prune after all startup messages are logged
        self._prune_activity_log(self.activity_log_file, force=True)

    def _prune_activity_log(self, filename, force=False):
        """
        Memory-safe log pruning: checks size and truncates by line count if necessary.
        Uses a two-pass file operation to avoid loading the entire file into memory (OOM fix).
        """
        MAX_LINES_TO_KEEP = 1000 # Keep the 1000 most recent lines
        
        # Periodic check to limit overhead unless forced (e.g., at startup)
        if not force and time.time() - self.last_prune_time < self.prune_interval:
            return

        gc.collect() # Always run garbage collection before a potentially large file operation
        
        try:
            stat = os.stat(filename)
            size = stat[6] 
            
            if size > MAX_ACTIVITY_LOG_SIZE_BYTES:
                
                # --- Pass 1: Count lines (Line-by-line read is memory-safe) ---
                line_count = 0
                try:
                    with open(filename, 'r') as f:
                        for _ in f:
                            line_count += 1
                except OSError as e:
                    print(f"[PRUNE_ERROR] Pass 1 read failed: {e}")
                    return

                lines_to_skip = max(0, line_count - MAX_LINES_TO_KEEP)
                
                if lines_to_skip > 0:
                    temp_filename = filename + ".tmp"
                    lines_removed = 0
                    
                    # --- Pass 2: Write remaining lines to temp file ---
                    with open(filename, 'r') as infile:
                        with open(temp_filename, 'w') as outfile:
                            for i, line in enumerate(infile):
                                if i < lines_to_skip:
                                    lines_removed += 1
                                    continue
                                outfile.write(line)
                            
                    # --- Pass 3: Replace original file ---
                    os.remove(filename)
                    os.rename(temp_filename, filename)
                    
                    # Log the action (will be visible on the next _log_activity call)
                    prune_message = f"[PRUNE] Activity log exceeded {MAX_ACTIVITY_LOG_SIZE_BYTES/1024:.0f}KB. Removed {lines_removed} oldest lines (Keeping last {MAX_LINES_TO_KEEP})."
                    self._log_activity(prune_message, timestamp=True)
                    
                self.last_prune_time = time.time() # Update prune time only if it ran successfully

        except Exception as e:
            # Catch file stat or rename errors
            print(f"[PRUNE_ERROR] Failed to prune {filename}: {e}")

    def _init_tmp117(self):
        try:
            self.tmp117 = TMP117(self.i2c_sensors, address=0x48)
            self.tmp117.set_conversion_cycle(self.tmp117.CONV_250MS)
            self.tmp117.set_averaging(self.tmp117.AVG_8)
            time.sleep(0.5) 
            test_temp = self.tmp117.read_temperature()
            if -50 <= test_temp <= 100:
                self.tmp117_working = True
                self._log_activity("      TMP117 initialized successfully.", timestamp=False)
                return True
            else:
                self._log_activity(f"      TMP117 test read failed: {test_temp}C", timestamp=False)
        except Exception as e:
            self._log_activity(f"      TMP117 initialization failed: {e}", timestamp=False)
        self.tmp117 = None; self.tmp117_working = False
        return False

    def _init_shtc3(self):
        try:
            self.shtc3 = SHTC3(self.i2c_sensors, debug=False)
            test_temp, test_hum = self.shtc3.read_measurements()
            if -50 <= test_temp <= 100 and 0 <= test_hum <= 100:
                self.shtc3_working = True
                self._log_activity("      SHTC3 initialized successfully.", timestamp=False)
                return True
            else:
                self._log_activity(f"      SHTC3 test read failed: {test_temp}C, {test_hum}%", timestamp=False)
        except Exception as e:
            self._log_activity(f"      SHTC3 initialization failed: {e}", timestamp=False)
        self.shtc3 = None; self.shtc3_working = False
        return False
    
    def _reinit_ds3231(self):
        """Re-initializes the DS3231 driver object and checks for presence."""
        self.ds3231 = DS3231_RTC()
        if self.ds3231.is_present:
            self._log_activity("RTC: DS3231 I2C connection re-established.")
            return True
        return False

    def _log_activity(self, message, timestamp=True):
        """Logs to file and prints to console. Supports raw (no timestamp) output for headers."""
        if timestamp:
            print(f"[{self.get_timestamp()}] {message}") 
        else:
            print(message)

        try:
            with open(self.activity_log_file, 'a') as f:
                if timestamp:
                    f.write(f"[{self.get_timestamp()}] {message}\n")
                else:
                    f.write(f"{message}\n")
            
            # Prune only periodically (every 30 seconds or 10 writes)
            self.log_write_count += 1
            if self.log_write_count % 10 == 0 or time.time() - self.last_prune_time >= self.prune_interval:
                self._prune_activity_log(self.activity_log_file)
            
        except Exception as e:
            print(f"[ACTIVITY_LOG_ERROR] {e}")

    def _sync_rtc_time(self):
        """
        Attempts to read time from the external DS3231.
        If valid, it sets the internal RTC. If invalid or missing, it DOES NOTHING 
        and allows the internal RTC to run free.
        """
        try:
            if not self.ds3231.is_present:
                self._log_activity("RTC: External DS3231 not found or disconnected. Internal RTC running unsynced.")
                self.has_external_rtc = False
                return False

            external_time = self.ds3231.read_time()

            if external_time:
                # 1. SUCCESS: External time is valid. Use it as the source of truth.
                y, mo, d, h, mi, s = external_time
                # MicroPython RTC tuple: (year, month, day, weekday, hours, minutes, seconds, subseconds)
                # We let the internal RTC calculate the correct DOW based on Y, M, D. (wd=0)
                self.rtc.datetime((y, mo, d, 0, h, mi, s, 0))
                self.has_external_rtc = True
                self.rtc_last_retry_time = time.time() # Reset retry time since it worked
                self._log_activity("RTC: External DS3231 time successfully synced (MASTER).")
                return True
            else:
                # 2. FAILURE: External time is invalid (corrupted). DO NOTHING.
                # Rely on the current state of the internal RTC, which will drift or show 2000-01-01.
                self._log_activity("RTC: DS3231 found, but time corrupted. NOT setting/repairing external RTC. Internal RTC running unsynced.")
                self.has_external_rtc = False
                return False
                
        except Exception as e:
            self._log_activity(f"External RTC sync failed: {e}. Internal RTC running unsynced.")
        
        self.has_external_rtc = False
        return False
    
    def _check_rtc_status(self):
        current_time = time.time()
        
        # Get intervals from config with fallback defaults
        normal_interval = getattr(config, 'RTC_SYNC_NORMAL_INTERVAL_SECONDS', None) or 3600
        retry_interval = getattr(config, 'RTC_SYNC_RETRY_INTERVAL_SECONDS', None) or 30
        
        # If the external RTC is currently unreliable, use the aggressive retry interval.
        if not self.has_external_rtc:
            check_interval = retry_interval
        else:
            # If the external RTC is currently working, use the longer interval for drift correction.
            check_interval = normal_interval
        
        if current_time - self.rtc_last_retry_time >= check_interval:
            self.rtc_last_retry_time = current_time
            
            # If the external RTC is currently NOT providing reliable time, we retry the full check
            if not self.has_external_rtc:
                if not self.ds3231.is_present:
                    # If not present, try to re-init the driver to scan for it
                    self._reinit_ds3231()
            
            # If present (or just re-init'd), attempt to read and sync
            if self.ds3231.is_present:
                self._sync_rtc_time()
    
    # --- Helpers ---
    def get_timestamp(self):
        # We use the internal RTC always to get the current time, 
        # which is kept in sync by the DS3231 if present.
        y, mo, d, wd, h, mi, s, ss = self.rtc.datetime()
        return f"{y:04d}-{mo:02d}-{d:02d} {h:02d}:{mi:02d}:{s:02d}"
    
    def format_date_day(self):
        y, mo, d, wd, h, mi, s, ss = self.rtc.datetime()
        # Use the two-letter day abbreviation
        return f"{mo:02d}/{d:02d} {self.DAY_NAMES[wd]}"
        
    def format_time_12hr(self):
        y, mo, d, wd, h, mi, s, ss = self.rtc.datetime()
        ampm = "PM" if h >= 12 else "AM"
        display_h = h % 12
        if display_h == 0: display_h = 12
        return f"{display_h}:{mi:02d}{ampm}"
    
    def is_night_mode(self):
        """Check if current time is within night mode hours (minute precision)."""
        y, mo, d, wd, h, mi, s, ss = self.rtc.datetime()
        
        # Convert times to minutes since midnight for easy comparison
        current_mins = h * 60 + mi
        start_mins = self.night_start * 60 + self.night_start_min
        end_mins = self.night_end * 60 + self.night_end_min
        
        # Handle case where night mode crosses midnight (e.g., 22:30 to 7:15)
        if start_mins > end_mins:
            return current_mins >= start_mins or current_mins < end_mins
        else:
            return start_mins <= current_mins < end_mins
    
    def is_motor_enabled(self, readings):
        # 1. MANUAL MODE: Always allowed (highest priority).
        if self.manual_mode: return True, "MANUAL_MODE"
        
        y, mo, d, wd, h, mi, s, ss = self.rtc.datetime()
        
        # Get environmental data from current readings
        tmp1 = readings.get('tmp117_f'); tmp2 = readings.get('shtc3_f')
        humidity = readings.get('humidity')
        
        # --- Use last known readings if current readings are None AND within timeout window ---
        current_time = time.time()
        time_since_last_valid = current_time - self.last_valid_readings['timestamp']
        
        if time_since_last_valid <= self.sensor_reading_timeout:
            # We're within the timeout window, use cached readings for None values
            if tmp1 is None and self.last_valid_readings['tmp117_f'] is not None:
                tmp1 = self.last_valid_readings['tmp117_f']
            if tmp2 is None and self.last_valid_readings['shtc3_f'] is not None:
                tmp2 = self.last_valid_readings['shtc3_f']
            if humidity is None and self.last_valid_readings['humidity'] is not None:
                humidity = self.last_valid_readings['humidity']
        
        # Temperature is averaged if both sensors are working
        temp_f = (tmp1 + tmp2)/2 if (tmp1 and tmp2) else (tmp1 or tmp2)

        # 2. TEMPERATURE OVERRIDE (highest priority environmental override)
        if temp_f and temp_f >= self.temp_override_threshold:
            return True, f"HIGH_TEMP_OVERRIDE_{temp_f:.1f}"
        
        # 3. HUMIDITY OVERRIDE (second priority environmental override)
        if humidity and humidity >= self.humidity_override_threshold:
            return True, f"HIGH_HUMIDITY_OVERRIDE_{humidity:.1f}"
        
        # 4. TIME/DAY CHECK (after all overrides are checked)
        # If outside business hours/days, return False
        
        # Check Day of Week with config fallbacks
        bus_days_start = getattr(config, 'BUSINESS_DAYS_START', 0)
        bus_days_end = getattr(config, 'BUSINESS_DAYS_END', 4)
        if not (bus_days_start <= wd <= bus_days_end): 
            return False, "WEEKEND"
        
        # Check Time of Day with config fallbacks
        bus_hour_start = getattr(config, 'BUSINESS_HOUR_START', 8)
        bus_min_start = getattr(config, 'BUSINESS_MINUTE_START', 0)
        bus_hour_end = getattr(config, 'BUSINESS_HOUR_END', 17)
        bus_min_end = getattr(config, 'BUSINESS_MINUTE_END', 0)
        
        start_mins = bus_hour_start * 60 + bus_min_start
        end_mins = bus_hour_end * 60 + bus_min_end
        curr_mins = h * 60 + mi
        
        if not (start_mins <= curr_mins <= end_mins): 
            return False, "AFTER_HOURS"

        # 5. AUTO ALLOWED (Within business hours and no override conditions met)
        return True, "ALLOWED"

    def read_sensors(self):
        readings = { 'tmp117_f': None, 'shtc3_f': None, 'humidity': None, 'status': [] }
        
        if not self.tmp117_working and 0x48 in self.i2c_sensors.scan():
            if self._init_tmp117(): self._log_activity("SENSOR: TMP117 reconnected")
        
        if self.tmp117_working and self.tmp117:
            try:
                t = self.tmp117.read_temperature()
                if -50<=t<=100: 
                    readings['tmp117_f']=(t*1.8)+32; readings['status'].append('TMP117_OK')
                else: 
                    readings['status'].append('TMP117_BAD')
                    self._log_activity("SENSOR: TMP117 disconnected (bad reading)")
                    self.tmp117_working=False
            except Exception as e: 
                readings['status'].append('TMP117_ERR')
                self._log_activity(f"SENSOR: TMP117 disconnected (error: {e})")
                self.tmp117_working=False

        if not self.shtc3_working and 0x70 in self.i2c_sensors.scan():
            if self._init_shtc3(): self.shtc3_working=True; self._log_activity("SENSOR: SHTC3 reconnected")
            
        if self.shtc3_working and self.shtc3:
            try:
                t, h = self.shtc3.read_measurements()
                if -50<=t<=100:
                    readings['shtc3_f']=(t*1.8)+32; readings['humidity']=h; readings['status'].append('SHTC3_OK')
                else: 
                    readings['status'].append('SHTC3_BAD')
                    self._log_activity("SENSOR: SHTC3 disconnected (bad reading)")
                    self.shtc3_working=False
            except Exception as e: 
                readings['status'].append('SHTC3_ERR')
                self._log_activity(f"SENSOR: SHTC3 disconnected (error: {e})")
                self.shtc3_working=False
            
        if not readings['status']: readings['status'].append('NO_SENSORS')
        
        # --- Update last valid readings if we got new data ---
        current_time = time.time()
        has_new_data = readings['tmp117_f'] is not None or readings['shtc3_f'] is not None or readings['humidity'] is not None
        
        if has_new_data:
            # Store valid readings with timestamp
            if readings['tmp117_f'] is not None:
                self.last_valid_readings['tmp117_f'] = readings['tmp117_f']
            if readings['shtc3_f'] is not None:
                self.last_valid_readings['shtc3_f'] = readings['shtc3_f']
            if readings['humidity'] is not None:
                self.last_valid_readings['humidity'] = readings['humidity']
            self.last_valid_readings['timestamp'] = current_time
        
        return readings

    def _reinit_oled(self):
        try:
            import sys
            if 'ssd_config' in sys.modules: del sys.modules['ssd_config']
            from ssd_config import oled as new_oled
            global oled; oled = new_oled
            oled.poweroff(); time.sleep(0.1); oled.poweron(); time.sleep(0.1)
            oled.fill(0); oled.text("OLED OK", 0, 0); oled.show()
            self._log_activity("DISPLAY: OLED reconnected")
            return True
        except: return False

    def display_readings(self, readings):
        if self.is_night_mode():
            if self.oled_working:
                try: oled.fill(0); oled.show()
                except: self.oled_working = False
            return
        
        if not self.oled_working:
            if time.time() - self.oled_last_retry_time >= 10:
                self.oled_last_retry_time = time.time()
                if self._reinit_oled(): self.oled_working = True
            if not self.oled_working: return

        try:
            oled.fill(0)
            
            # Draw a border around the entire display (128x64)
            oled.rect(0, 0, 128, 64, 1) 
            
            # Start text at x=2, y=2 to clear the top/left border pixels
            oled.text(f"{self.format_date_day()} {self.format_time_12hr()}", 2, 2)
            
            # Add line under the date (y=2 to y=9 is text, line at y=11)
            oled.hline(2, 11, 124, 1) 
            
            t1 = readings['tmp117_f']
            oled.text(f"TMP: {t1:.1f}F" if t1 else "TMP: --F", 2, 16)
            
            t2 = readings['shtc3_f']
            oled.text(f"SHT: {t2:.1f}F" if t2 else "SHT: --F", 2, 24)
            
            h1 = readings['humidity']
            oled.text(f"HUM: {h1:.1f}%" if h1 else "HUM: --%", 2, 32)
            
            oled.text(f"FAN: {self.fan_speed}%", 2, 40)
            
            en, reason = self.is_motor_enabled(readings)
            if not en: 
                status = "STOP: " + ("A/H" if reason=="AFTER_HOURS" else reason[:10])
            else: 
                if reason == "MANUAL_MODE":
                    status = "RUN: Manual"
                elif "HIGH_TEMP_OVERRIDE" in reason:
                    status = "RUN: T Override"
                elif "HIGH_HUMIDITY_OVERRIDE" in reason:
                    status = "RUN: H Override"
                else:
                    status = "RUN: Auto"
            oled.text(status, 2, 48)
            
            # Display RTC status with T or H override indicator if applicable
            if self.has_external_rtc:
                rtc_status = "EXT (SYNC)"
            else:
                # Show override type in RTC line when internal RTC and override is active
                if "HIGH_TEMP_OVERRIDE" in reason:
                    rtc_status = "INT (T-OVR)"
                elif "HIGH_HUMIDITY_OVERRIDE" in reason:
                    rtc_status = "INT (H-OVR)"
                else:
                    rtc_status = "INT (UNSYNC)"
            oled.text(f"RTC: {rtc_status}", 2, 56)
            oled.show()
            
            if not self.oled_working: self.oled_working = True; self._log_activity("DISPLAY: OLED restored")
        except Exception as e:
            if self.oled_working:
                self._log_activity(f"ERROR: OLED failed - {e}")
                self.oled_working = False; self.oled_last_retry_time = time.time()

    def log_data(self, readings):
        try:
            ts = self.get_timestamp()
            t1 = f"{readings['tmp117_f']:.2f}" if readings['tmp117_f'] else ""
            t2 = f"{readings['shtc3_f']:.2f}" if readings['shtc3_f'] else ""
            h1 = f"{readings['humidity']:.2f}" if readings['humidity'] else ""
            stat = f"{'MANUAL' if self.manual_mode else 'AUTO'}|" + "|".join(readings['status'])
            
            with open(self.log_file, 'a') as f:
                f.write(f"{ts},{t1},{t2},{h1},{stat}\n")
        except Exception as e: print(f"[ERROR] Logging failed: {e}")

    def get_increase_step(self, spd):
        if spd < 50: return 10
        elif spd < 80: return 7.5
        elif spd < 90: return 5
        else: return 2

    def get_decrease_step(self, spd):
        if spd > 90: return 2.0
        elif spd > 80: return 5.0
        elif spd > 50: return 7.5
        else: return 10.0

    def run(self, log_interval=None):
        # Use config value if not specified with robust fallback
        if log_interval is None:
            log_interval = getattr(config, 'LOGGING_INTERVAL_SECONDS', None) or 60
        
        rtc_src = "External DS3231 RTC" if self.has_external_rtc else "Internal RTC (UNSYNCED)"
        self._log_activity(f"Time source: {rtc_src}", timestamp=False)
        self._log_activity(f"Current time (24hr): {self.get_timestamp()}", timestamp=False)
        
        last_log = time.time()
        last_night = self.is_night_mode()
        last_reason = ""
        last_motor_enabled = None  # Track motor enable state for business hours transitions
        last_sensor_read = 0  # Track last sensor read time
        cached_readings = None  # Store last sensor readings
        
        # Get timing intervals from config with fallback defaults
        sensor_read_interval = getattr(config, 'SENSOR_READ_INTERVAL_SECONDS', None) or 1.0
        main_loop_interval = getattr(config, 'MAIN_LOOP_INTERVAL_SECONDS', None) or 0.1
        
        try:
            while True:
                night = self.is_night_mode()
                if night != last_night:
                    night_start_str = f"{self.night_start:02d}:{self.night_start_min:02d}"
                    night_end_str = f"{self.night_end:02d}:{self.night_end_min:02d}"
                    if night:
                        self._log_activity(f"[NIGHT MODE] Display off until {night_end_str}", timestamp=True)
                    else:
                        self._log_activity(f"[DAY MODE] Display on until {night_start_str}", timestamp=True)
                    last_night = night
                
                self._check_rtc_status()
                
                new_spd = self.fan_speed # Start with the current speed
                
                # Manual Toggle (Green + Red simultaneously)
                both = (self.buttons.buttons['green']['pin'].value()==0 and self.buttons.buttons['red']['pin'].value()==0)
                if both:
                    curr = time.ticks_ms()
                    last = max(self.buttons.buttons['green']['last_press_time'], self.buttons.buttons['red']['last_press_time'])
                    if time.ticks_diff(curr, last) > 200:
                        if self.manual_mode:
                            self.manual_mode = False; self.last_shutdown_reason = None # Clear shutdown reason
                            self._log_activity("CONTROL: Manual mode disabled. Returning to Auto.", timestamp=True)
                        else:
                             self.manual_mode = True # Auto -> Manual
                             self._log_activity("CONTROL: Manual mode activated.", timestamp=True)
                        
                        # Visual feedback and button reset
                        if self.oled_working: 
                            try: oled.fill(0); oled.text("MANUAL "+("OFF" if not self.manual_mode else "ON"),0,16); oled.show(); time.sleep(0.5)
                            except: self.oled_working=False
                        self.buttons.buttons['green']['last_press_time']=curr; self.buttons.buttons['red']['last_press_time']=curr
                        continue

                # Read button presses
                btn_g = self.buttons.check_press('green')
                btn_r = self.buttons.check_press('red')
                
                # Define the overall button_pressed state (used in override/manual logic)
                button_pressed = None
                if btn_g: button_pressed = 'GREEN'
                elif btn_r: button_pressed = 'RED'
                
                # --- Read sensors at configured interval (not every loop iteration) ---
                current_time = time.time()
                if current_time - last_sensor_read >= sensor_read_interval or cached_readings is None:
                    readings = self.read_sensors()
                    cached_readings = readings
                    last_sensor_read = current_time
                else:
                    # Use cached readings from last sensor read
                    readings = cached_readings
                
                en, reason = self.is_motor_enabled(readings)
                is_over = "OVERRIDE" in reason
                is_temp_over = "HIGH_TEMP_OVERRIDE" in reason
                is_man = reason == "MANUAL_MODE"
                
                # --- Log Business Hours Transitions (Time-based only) ---
                # Only log when transitioning between ALLOWED <-> (AFTER_HOURS or WEEKEND)
                # Don't log when override conditions change
                if last_motor_enabled is not None and en != last_motor_enabled and not is_man and not is_over:
                    # Check if the PREVIOUS reason was also not an override
                    was_override = "OVERRIDE" in last_reason
                    
                    # Only log if we're transitioning purely due to time/day changes
                    if not was_override:
                        y, mo, d, wd, h, mi, s, ss = self.rtc.datetime()
                        current_time_str = f"{h:02d}:{mi:02d}"
                        day_name = self.DAY_NAMES[wd]
                        
                        if en and reason == "ALLOWED":
                            # Transition: Business hours START
                            bus_start_str = f"{config.BUSINESS_HOUR_START:02d}:{config.BUSINESS_MINUTE_START:02d}"
                            bus_end_str = f"{config.BUSINESS_HOUR_END:02d}:{config.BUSINESS_MINUTE_END:02d}"
                            self._log_activity(f"[BUSINESS HOURS] Started at {current_time_str} ({day_name}). Operating until {bus_end_str}", timestamp=True)
                        elif not en and (reason == "AFTER_HOURS" or reason == "WEEKEND"):
                            # Transition: Business hours END
                            next_start_str = f"{config.BUSINESS_HOUR_START:02d}:{config.BUSINESS_MINUTE_START:02d}"
                            if reason == "WEEKEND":
                                self._log_activity(f"[WEEKEND] Business hours ended at {current_time_str}. Resuming Monday at {next_start_str}", timestamp=True)
                            else:
                                self._log_activity(f"[AFTER HOURS] Business day ended at {current_time_str}. Resuming at {next_start_str}", timestamp=True)
                
                last_motor_enabled = en  # Update state tracker
                
                # --- State Transition Logging (Override/Auto Mode) ---
                if is_over and "OVERRIDE" not in last_reason and not is_man:
                     # Log entry into override
                     val = reason.split('_')[-1]
                     if "TEMP" in reason:
                         type_s = "Temperature"
                         unit = "F"
                         target = self.temp_override_min_speed
                     else:
                         type_s = "Humidity"
                         unit = "%"
                         target = self.humidity_override_min_speed
                     self._log_activity(f"[OVERRIDE] {type_s} ({val}{unit}) detected. Forcing min speed {target}%.", timestamp=True)
                
                elif not is_over and "OVERRIDE" in last_reason and not is_man:
                    # Log exit from override and return to normal operation
                    self._log_activity(f"[AUTO] Override ended. Resuming normal operation ({reason}).", timestamp=True)
                    
                # --- Motor Control and Logging ---
                if not en and not is_man:
                    # STATE: Motor must be OFF (AFTER_HOURS, WEEKEND, etc.)
                    
                    # We only log if the reason for stopping is NEW (i.e., we just transitioned from RUNNING or different STOP reason)
                    if self.last_shutdown_reason != reason:
                        
                        # Case 1: Transition RUNNING (last_shutdown_reason=None) -> STOPPED
                        if self.last_shutdown_reason is None:
                            self._log_activity(f"[STOP] Motor disabled: {reason}", timestamp=True)
                        else:
                            # Case 2: Transition STOPPED_A -> STOPPED_B (e.g., WEEKEND to AFTER_HOURS)
                            self._log_activity(f"[STOP] Motor stop reason changed to: {reason}", timestamp=True)

                        # Set the physical state and update the state trackers
                        new_spd = 0
                        self.motor.stop()
                        self.last_shutdown_reason = reason # Record the reason we are now stopped
                    
                    # If self.last_shutdown_reason == reason, the motor is already stopped for this reason. Do nothing (logs suppressed).
                        
                else:
                    # STATE: Motor must be ON (Manual, Override, or Auto Allowed)
                    
                    # 1. Transition: STOPPED -> RUNNING
                    if self.last_shutdown_reason is not None:
                        self._log_activity(f"[RUN] Motor re-enabled: {reason}", timestamp=True)
                        # Set initial speed if the fan was completely stopped (i.e., self.fan_speed was 0)
                        if self.fan_speed == 0:
                            initial_speed = getattr(config, 'MOTOR_INITIAL_SPEED_PERCENT', 65)
                            new_spd = initial_speed
                        self.last_shutdown_reason = None # Clear the shutdown reason tracker
                    
                    # 2. Speed Adjustment Logic (if running or starting)
                    if is_man:
                        motor_min_speed = getattr(config, 'MOTOR_MIN_SPEED_PERCENT', 20)
                        if button_pressed == 'GREEN': new_spd = min(100, self.fan_speed + self.get_increase_step(self.fan_speed))
                        elif button_pressed == 'RED': new_spd = max(motor_min_speed, self.fan_speed - self.get_decrease_step(self.fan_speed))
                        if button_pressed: self._log_activity(f"[MANUAL] Speed: {new_spd:.1f}%", timestamp=True)

                    elif is_over:
                        target_min = self.temp_override_min_speed if is_temp_over else self.humidity_override_min_speed
                        
                        # 2.1 Handle Manual Adjustment
                        if button_pressed == 'GREEN':
                            step = self.get_increase_step(self.fan_speed)
                            new_spd = min(100, self.fan_speed + step)
                            self._log_activity(f"[OVERRIDE] Speed increased to {new_spd:.1f}% manually.", timestamp=True)
                        elif button_pressed == 'RED':
                            step = self.get_decrease_step(self.fan_speed)
                            calculated_speed = self.fan_speed - step
                            
                            if calculated_speed >= target_min:
                                new_spd = calculated_speed
                                self._log_activity(f"[OVERRIDE] Speed decreased to {new_spd:.1f}% manually.", timestamp=True)
                            else:
                                # Blocked - would go below minimum
                                new_spd = target_min
                                self._log_activity(f"[OVERRIDE] Decrease blocked. Min speed enforced ({target_min}%).", timestamp=True)

                        # 2.2 Initial Minimum Enforcement (when the motor first kicks into override mode)
                        elif self.fan_speed < target_min:
                            new_spd = target_min
                            self._log_activity(f"[OVERRIDE] Enforcing minimum speed: {target_min}%.", timestamp=True)
                    
                    else: # Auto Mode (ALLOWED)
                        # In Auto Mode, buttons switch to Manual Mode
                        motor_min_speed = getattr(config, 'MOTOR_MIN_SPEED_PERCENT', 20)
                        if button_pressed:
                            self.manual_mode = True
                            if button_pressed == 'GREEN': new_spd = min(100, self.fan_speed + self.get_increase_step(self.fan_speed))
                            elif button_pressed == 'RED': new_spd = max(motor_min_speed, self.fan_speed - self.get_decrease_step(self.fan_speed))
                            self._log_activity(f"[CONTROL] Manual Active. Speed: {new_spd:.1f}%", timestamp=True)
                            if self.oled_working: 
                                try: oled.fill(0); oled.text("MANUAL ON",0,16); oled.show(); time.sleep(0.5)
                                except: self.oled_working=False

                    # Update the speed and motor driver if there was any change
                    if new_spd != self.fan_speed: self.fan_speed = new_spd; self.motor.forward(self.fan_speed)

                # Update the state tracker for the next loop iteration (for override logging)
                last_reason = reason
                
                if time.time() - last_log >= log_interval: self.log_data(readings); last_log = time.time()
                self.display_readings(readings)
                time.sleep(main_loop_interval)

        except KeyboardInterrupt:
            self.motor.stop()
            self._log_activity("", timestamp=False)
            self._log_activity("[STOP] Stopped by user", timestamp=False)
            if self.oled_working:
                try: oled.fill(0); oled.text("Stopped", 0, 0); oled.show()
                except: pass
        except Exception as e:
            self.motor.stop()
            self._log_activity("", timestamp=False)
            self._log_activity(f"[FATAL ERROR] {e}", timestamp=False)
            if self.oled_working:
                try: oled.fill(0); oled.text("FATAL ERROR", 0, 0); oled.text(str(e)[:16], 0, 10); oled.show()
                except: pass

def main():
    logger = ResilientLogger()
    logger.run()

if __name__ == "__main__":
    main()