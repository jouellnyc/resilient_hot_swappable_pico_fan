# File: rtc_logger.py
# Version: V10.0 (MQ gas sensor integration)
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
from mq_sensor import MQSensor
import config

LOGGER_VERSION = "V10.0"

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
        self.co_override_threshold = getattr(config, 'CO_OVERRIDE_THRESHOLD_PPM', 150.0)
        self.co_override_min_speed = getattr(config, 'CO_OVERRIDE_MIN_SPEED', 100)
        self.co_alert_raw_delta = getattr(config, 'CO_ALERT_RAW_DELTA', 5000)
        self.last_shutdown_reason = None

        self.oled_working = True
        self.oled_last_retry_time = 0
        self.rtc_last_retry_time = 0

        # --- Last Known Sensor Readings (for brief disconnections) ---
        self.last_valid_readings = {
            'tmp117_f': None, 'shtc3_f': None, 'humidity': None,
            'mq_raw': None, 'mq_ppm': None, 'mq_alert': None,
            'timestamp': 0
        }
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
        self._log_activity("[1/6] Setting up I2C buses...", timestamp=False)
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
        self._log_activity("[2/6] Checking for external RTC (Master Source) with strict policy...", timestamp=False)
        self._sync_rtc_time()

        # --- PHASE 3: TMP117 ---
        self._log_activity("", timestamp=False)
        self._log_activity("[3/6] Initializing TMP117...", timestamp=False)
        self.tmp117 = None; self.tmp117_working = False
        if 0x48 in sensor_devices: self._init_tmp117()
        else: self._log_activity("      TMP117 not found at 0x48", timestamp=False)

        # --- PHASE 4: SHTC3 ---
        self._log_activity("", timestamp=False)
        self._log_activity("[4/6] Initializing SHTC3...", timestamp=False)
        self.shtc3 = None; self.shtc3_working = False
        if 0x70 in sensor_devices: self._init_shtc3()
        else: self._log_activity("      SHTC3 not found at 0x70", timestamp=False)

        if not self.tmp117_working and not self.shtc3_working:
            self._log_activity("\n[ERROR] No working I2C sensors found!", timestamp=False)

        # --- PHASE 5: MQ Gas Sensor ---
        self._log_activity("", timestamp=False)
        self._log_activity("[5/6] Initializing MQ gas sensor...", timestamp=False)
        mq_ao = getattr(config, 'MQ_AO_PIN', 26)
        mq_do = getattr(config, 'MQ_DO_PIN', 1)
        mq_samples = getattr(config, 'MQ_CALIBRATION_SAMPLES', 30)
        self.mq = MQSensor(ao_pin=mq_ao, do_pin=mq_do)
        self.mq.calibrate(samples=mq_samples, log_fn=self._log_activity)
        self.mq_baseline_raw = self.mq.R0  # Store baseline for raw delta fallback

        # --- PHASE 6: Files ---
        self._log_activity("", timestamp=False)
        self._log_activity("[6/6] Setting up log file...", timestamp=False)
        try:
            with open(self.log_file, 'r') as f: pass
            self._log_activity(f"      Using existing {self.log_file}", timestamp=False)
        except:
            with open(self.log_file, 'w') as f:
                f.write("timestamp,tmp117_f,shtc3_f,humidity,mq_raw,mq_ppm,mq_alert,status\n")
            self._log_activity(f"      Created {self.log_file}", timestamp=False)

        # --- READY BLOCK ---
        self._log_activity("", timestamp=False)
        self._log_activity("="*50, timestamp=False)
        self._log_activity("READY!", timestamp=False)

        sensor_status = []
        if self.tmp117_working: sensor_status.append("TMP117")
        if self.shtc3_working: sensor_status.append("SHTC3")
        if self.mq.working: sensor_status.append("MQ")

        self._log_activity(f"Working sensors: {', '.join(sensor_status) if sensor_status else 'NONE'}", timestamp=False)
        self._log_activity(f"Fan Speed: {self.fan_speed}%", timestamp=False)
        self._log_activity(f"Manual Mode: {self.manual_mode}", timestamp=False)
        self._log_activity("="*50, timestamp=False)
        self._log_activity("", timestamp=False)

        # Run initial memory-safe log prune after all startup messages are logged
        self._prune_activity_log(self.activity_log_file, force=True)

    def _prune_activity_log(self, filename, force=False):
        """
        Memory-safe log pruning with aggressive limits for small storage.
        Keeps only the most recent 200 lines to prevent disk overflow on 1MB systems.
        """
        MAX_LINES_TO_KEEP = 200
        MAX_LOG_SIZE = 50 * 1024  # 50KB limit

        if not force and time.time() - self.last_prune_time < self.prune_interval:
            return

        gc.collect()

        try:
            stat = os.stat(filename)
            size = stat[6]

            if size > MAX_LOG_SIZE:
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

                    with open(filename, 'r') as infile:
                        with open(temp_filename, 'w') as outfile:
                            for i, line in enumerate(infile):
                                if i < lines_to_skip:
                                    lines_removed += 1
                                    continue
                                outfile.write(line)

                    os.remove(filename)
                    os.rename(temp_filename, filename)
                    print(f"[PRUNE] Removed {lines_removed} old lines (Kept {MAX_LINES_TO_KEEP})")

                self.last_prune_time = time.time()

        except Exception as e:
            print(f"[PRUNE_ERROR] Failed to prune {filename}: {e}")

    def _log_activity(self, message, timestamp=True):
        """
        Logs only important events to file to conserve disk space.
        Prints everything to console for debugging.
        """
        if timestamp:
            print(f"[{self.get_timestamp()}] {message}")
        else:
            print(message)

        skip_file_write = False

        if not timestamp:
            skip_file_write = True

        skip_patterns = [
            "Working sensors:",
            "Fan Speed:",
            "Manual Mode:",
            "Time source:",
            "Current time",
            "READY!"
        ]

        for pattern in skip_patterns:
            if pattern in message:
                skip_file_write = True
                break

        if not skip_file_write:
            try:
                with open(self.activity_log_file, 'a') as f:
                    f.write(f"[{self.get_timestamp()}] {message}\n")

                self.log_write_count += 1
                if self.log_write_count % 5 == 0:
                    self._prune_activity_log(self.activity_log_file)

            except Exception as e:
                print(f"[ACTIVITY_LOG_ERROR] {e}")

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
        self.ds3231 = DS3231_RTC()
        if self.ds3231.is_present:
            self._log_activity("RTC: DS3231 I2C connection re-established.")
            return True
        return False

    def _sync_rtc_time(self):
        try:
            if not self.ds3231.is_present:
                self._log_activity("RTC: External DS3231 not found or disconnected. Internal RTC running unsynced.")
                self.has_external_rtc = False
                return False

            external_time = self.ds3231.read_time()

            if external_time:
                y, mo, d, h, mi, s = external_time
                self.rtc.datetime((y, mo, d, 0, h, mi, s, 0))
                self.has_external_rtc = True
                self.rtc_last_retry_time = time.time()
                self._log_activity("RTC: External DS3231 time successfully synced (MASTER).")
                return True
            else:
                self._log_activity("RTC: DS3231 found, but time corrupted. NOT setting/repairing external RTC. Internal RTC running unsynced.")
                self.has_external_rtc = False
                return False

        except Exception as e:
            self._log_activity(f"External RTC sync failed: {e}. Internal RTC running unsynced.")

        self.has_external_rtc = False
        return False

    def _check_rtc_status(self):
        current_time = time.time()
        normal_interval = getattr(config, 'RTC_SYNC_NORMAL_INTERVAL_SECONDS', None) or 3600
        retry_interval = getattr(config, 'RTC_SYNC_RETRY_INTERVAL_SECONDS', None) or 30

        if not self.has_external_rtc:
            check_interval = retry_interval
        else:
            check_interval = normal_interval

        if current_time - self.rtc_last_retry_time >= check_interval:
            self.rtc_last_retry_time = current_time
            if not self.has_external_rtc:
                if not self.ds3231.is_present:
                    self._reinit_ds3231()
            if self.ds3231.is_present:
                self._sync_rtc_time()

    def get_timestamp(self):
        y, mo, d, wd, h, mi, s, ss = self.rtc.datetime()
        return f"{y:04d}-{mo:02d}-{d:02d} {h:02d}:{mi:02d}:{s:02d}"

    def format_date_day(self):
        y, mo, d, wd, h, mi, s, ss = self.rtc.datetime()
        return f"{mo:02d}/{d:02d} {self.DAY_NAMES[wd]}"

    def format_time_12hr(self):
        y, mo, d, wd, h, mi, s, ss = self.rtc.datetime()
        ampm = "PM" if h >= 12 else "AM"
        display_h = h % 12
        if display_h == 0: display_h = 12
        return f"{display_h}:{mi:02d}{ampm}"

    def is_night_mode(self):
        y, mo, d, wd, h, mi, s, ss = self.rtc.datetime()
        current_mins = h * 60 + mi
        start_mins = self.night_start * 60 + self.night_start_min
        end_mins = self.night_end * 60 + self.night_end_min
        if start_mins > end_mins:
            return current_mins >= start_mins or current_mins < end_mins
        else:
            return start_mins <= current_mins < end_mins

    def is_motor_enabled(self, readings):
        if self.manual_mode: return True, "MANUAL_MODE"

        y, mo, d, wd, h, mi, s, ss = self.rtc.datetime()

        tmp1 = readings.get('tmp117_f'); tmp2 = readings.get('shtc3_f')
        humidity = readings.get('humidity')
        mq_ppm = readings.get('mq_ppm')
        mq_raw = readings.get('mq_raw')

        current_time = time.time()
        time_since_last_valid = current_time - self.last_valid_readings['timestamp']

        if time_since_last_valid <= self.sensor_reading_timeout:
            if tmp1 is None and self.last_valid_readings['tmp117_f'] is not None:
                tmp1 = self.last_valid_readings['tmp117_f']
            if tmp2 is None and self.last_valid_readings['shtc3_f'] is not None:
                tmp2 = self.last_valid_readings['shtc3_f']
            if humidity is None and self.last_valid_readings['humidity'] is not None:
                humidity = self.last_valid_readings['humidity']
            if mq_ppm is None and self.last_valid_readings['mq_ppm'] is not None:
                mq_ppm = self.last_valid_readings['mq_ppm']
            if mq_raw is None and self.last_valid_readings['mq_raw'] is not None:
                mq_raw = self.last_valid_readings['mq_raw']

        temp_f = (tmp1 + tmp2)/2 if (tmp1 and tmp2) else (tmp1 or tmp2)

        # 2. TEMPERATURE OVERRIDE
        if temp_f and temp_f >= self.temp_override_threshold:
            return True, f"HIGH_TEMP_OVERRIDE_{temp_f:.1f}"

        # 3. HUMIDITY OVERRIDE
        if humidity and humidity >= self.humidity_override_threshold:
            return True, f"HIGH_HUMIDITY_OVERRIDE_{humidity:.1f}"

        # 4. CO / GAS OVERRIDE
        # Use PPM if calibrated, otherwise fall back to raw delta
        co_triggered = False
        co_value_str = ""
        if mq_ppm is not None and mq_ppm >= self.co_override_threshold:
            co_triggered = True
            co_value_str = f"{mq_ppm:.1f}ppm"
        elif mq_raw is not None and self.mq_baseline_raw and \
                (mq_raw - self.mq_baseline_raw) >= self.co_alert_raw_delta:
            co_triggered = True
            co_value_str = f"raw+{int(mq_raw - self.mq_baseline_raw)}"
        if co_triggered:
            return True, f"HIGH_CO_OVERRIDE_{co_value_str}"

        # 5. TIME/DAY CHECK
        bus_days_start = getattr(config, 'BUSINESS_DAYS_START', 0)
        bus_days_end = getattr(config, 'BUSINESS_DAYS_END', 4)
        if not (bus_days_start <= wd <= bus_days_end):
            return False, "WEEKEND"

        bus_hour_start = getattr(config, 'BUSINESS_HOUR_START', 8)
        bus_min_start = getattr(config, 'BUSINESS_MINUTE_START', 0)
        bus_hour_end = getattr(config, 'BUSINESS_HOUR_END', 17)
        bus_min_end = getattr(config, 'BUSINESS_MINUTE_END', 0)

        start_mins = bus_hour_start * 60 + bus_min_start
        end_mins = bus_hour_end * 60 + bus_min_end
        curr_mins = h * 60 + mi

        if not (start_mins <= curr_mins <= end_mins):
            return False, "AFTER_HOURS"

        return True, "ALLOWED"

    def read_sensors(self):
        readings = {
            'tmp117_f': None, 'shtc3_f': None, 'humidity': None,
            'mq_raw': None, 'mq_ppm': None, 'mq_alert': None,
            'status': []
        }

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

        # --- MQ Gas Sensor Read ---
        raw, ppm, alert = self.mq.read()
        if raw is not None:
            readings['mq_raw'] = raw
            readings['mq_ppm'] = ppm
            readings['mq_alert'] = alert
            readings['status'].append('MQ_OK')
            if not self.mq.working:
                self._log_activity("SENSOR: MQ sensor reconnected")
        else:
            readings['status'].append('MQ_ERR')
            if self.mq.working:
                self._log_activity("SENSOR: MQ sensor disconnected (read error)")

        if not readings['status']: readings['status'].append('NO_SENSORS')

        current_time = time.time()
        has_new_data = any(readings[k] is not None for k in
                          ['tmp117_f', 'shtc3_f', 'humidity', 'mq_raw'])

        if has_new_data:
            for key in ['tmp117_f', 'shtc3_f', 'humidity', 'mq_raw', 'mq_ppm', 'mq_alert']:
                if readings[key] is not None:
                    self.last_valid_readings[key] = readings[key]
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
            oled.rect(0, 0, 128, 64, 1)
            oled.text(f"{self.format_date_day()} {self.format_time_12hr()}", 2, 2)
            oled.hline(2, 11, 124, 1)

            t1 = readings['tmp117_f']
            oled.text(f"TMP: {t1:.1f}F" if t1 else "TMP: --F", 2, 13)

            t2 = readings['shtc3_f']
            oled.text(f"SHT: {t2:.1f}F" if t2 else "SHT: --F", 2, 22)

            h1 = readings['humidity']
            oled.text(f"HUM: {h1:.1f}%" if h1 else "HUM: --%", 2, 31)

            # MQ line: show PPM if available, else raw delta
            mq_ppm = readings['mq_ppm']
            mq_raw = readings['mq_raw']
            mq_alert = readings['mq_alert']
            if mq_ppm is not None:
                alert_flag = "!" if (mq_alert == 0) else " "
                oled.text(f"CO:{mq_ppm:.0f}p{alert_flag} F:{self.fan_speed}%", 2, 40)
            elif mq_raw is not None:
                oled.text(f"GAS:{mq_raw} F:{self.fan_speed}%", 2, 40)
            else:
                oled.text(f"GAS:-- F:{self.fan_speed}%", 2, 40)

            en, reason = self.is_motor_enabled(readings)
            if not en:
                status = "STOP: " + ("A/H" if reason=="AFTER_HOURS" else reason[:10])
            else:
                if reason == "MANUAL_MODE":
                    status = "RUN: Manual"
                elif "HIGH_TEMP_OVERRIDE" in reason:
                    status = "RUN: T-OVR"
                elif "HIGH_HUMIDITY_OVERRIDE" in reason:
                    status = "RUN: H-OVR"
                elif "HIGH_CO_OVERRIDE" in reason:
                    status = "RUN: CO-OVR!"
                else:
                    status = "RUN: Auto"
            oled.text(status, 2, 49)

            if self.has_external_rtc:
                rtc_status = "EXT"
            else:
                rtc_status = "INT"
            oled.text(f"RTC:{rtc_status}", 2, 57)

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
            mq_r = f"{readings['mq_raw']}" if readings['mq_raw'] is not None else ""
            mq_p = f"{readings['mq_ppm']}" if readings['mq_ppm'] is not None else ""
            mq_a = f"{readings['mq_alert']}" if readings['mq_alert'] is not None else ""
            stat = f"{'MANUAL' if self.manual_mode else 'AUTO'}|" + "|".join(readings['status'])

            with open(self.log_file, 'a') as f:
                f.write(f"{ts},{t1},{t2},{h1},{mq_r},{mq_p},{mq_a},{stat}\n")
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
        if log_interval is None:
            log_interval = getattr(config, 'LOGGING_INTERVAL_SECONDS', None) or 60

        rtc_src = "External DS3231 RTC" if self.has_external_rtc else "Internal RTC (UNSYNCED)"
        self._log_activity(f"Time source: {rtc_src}", timestamp=False)
        self._log_activity(f"Current time (24hr): {self.get_timestamp()}", timestamp=False)

        last_log = time.time()
        last_night = self.is_night_mode()
        last_reason = ""
        last_motor_enabled = None
        last_sensor_read = 0
        cached_readings = None

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

                new_spd = self.fan_speed

                both = (self.buttons.buttons['green']['pin'].value()==0 and self.buttons.buttons['red']['pin'].value()==0)
                if both:
                    curr = time.ticks_ms()
                    last = max(self.buttons.buttons['green']['last_press_time'], self.buttons.buttons['red']['last_press_time'])
                    if time.ticks_diff(curr, last) > 200:
                        if self.manual_mode:
                            self.manual_mode = False; self.last_shutdown_reason = None
                            self._log_activity("CONTROL: Manual mode disabled. Returning to Auto.", timestamp=True)
                        else:
                             self.manual_mode = True
                             self._log_activity("CONTROL: Manual mode activated.", timestamp=True)

                        if self.oled_working:
                            try: oled.fill(0); oled.text("MANUAL "+("OFF" if not self.manual_mode else "ON"),0,16); oled.show(); time.sleep(0.5)
                            except: self.oled_working=False
                        self.buttons.buttons['green']['last_press_time']=curr; self.buttons.buttons['red']['last_press_time']=curr
                        continue

                btn_g = self.buttons.check_press('green')
                btn_r = self.buttons.check_press('red')

                button_pressed = None
                if btn_g: button_pressed = 'GREEN'
                elif btn_r: button_pressed = 'RED'

                current_time = time.time()
                if current_time - last_sensor_read >= sensor_read_interval or cached_readings is None:
                    readings = self.read_sensors()
                    cached_readings = readings
                    last_sensor_read = current_time
                else:
                    readings = cached_readings

                en, reason = self.is_motor_enabled(readings)
                is_over = "OVERRIDE" in reason
                is_temp_over = "HIGH_TEMP_OVERRIDE" in reason
                is_co_over = "HIGH_CO_OVERRIDE" in reason
                is_man = reason == "MANUAL_MODE"

                if last_motor_enabled is not None and en != last_motor_enabled and not is_man and not is_over:
                    was_override = "OVERRIDE" in last_reason
                    if not was_override:
                        y, mo, d, wd, h, mi, s, ss = self.rtc.datetime()
                        current_time_str = f"{h:02d}:{mi:02d}"
                        day_name = self.DAY_NAMES[wd]

                        if en and reason == "ALLOWED":
                            bus_start_str = f"{config.BUSINESS_HOUR_START:02d}:{config.BUSINESS_MINUTE_START:02d}"
                            bus_end_str = f"{config.BUSINESS_HOUR_END:02d}:{config.BUSINESS_MINUTE_END:02d}"
                            self._log_activity(f"[BUSINESS HOURS] Started at {current_time_str} ({day_name}). Operating until {bus_end_str}", timestamp=True)
                        elif not en and (reason == "AFTER_HOURS" or reason == "WEEKEND"):
                            next_start_str = f"{config.BUSINESS_HOUR_START:02d}:{config.BUSINESS_MINUTE_START:02d}"
                            if reason == "WEEKEND":
                                self._log_activity(f"[WEEKEND] Business hours ended at {current_time_str}. Resuming Monday at {next_start_str}", timestamp=True)
                            else:
                                self._log_activity(f"[AFTER HOURS] Business day ended at {current_time_str}. Resuming at {next_start_str}", timestamp=True)

                last_motor_enabled = en

                if is_over and "OVERRIDE" not in last_reason and not is_man:
                     val = reason.split('_')[-1]
                     if "TEMP" in reason:
                         type_s = "Temperature"; unit = "F"; target = self.temp_override_min_speed
                     elif "CO" in reason:
                         type_s = "CO/Gas"; unit = ""; target = self.co_override_min_speed
                     else:
                         type_s = "Humidity"; unit = "%"; target = self.humidity_override_min_speed
                     self._log_activity(f"[OVERRIDE] {type_s} ({val}{unit}) detected. Forcing min speed {target}%.", timestamp=True)

                elif not is_over and "OVERRIDE" in last_reason and not is_man:
                    self._log_activity(f"[AUTO] Override ended. Resuming normal operation ({reason}).", timestamp=True)

                if not en and not is_man:
                    if self.last_shutdown_reason != reason:
                        if self.last_shutdown_reason is None:
                            self._log_activity(f"[STOP] Motor disabled: {reason}", timestamp=True)
                        else:
                            self._log_activity(f"[STOP] Motor stop reason changed to: {reason}", timestamp=True)
                        new_spd = 0
                        self.motor.stop()
                        self.last_shutdown_reason = reason

                else:
                    if self.last_shutdown_reason is not None:
                        self._log_activity(f"[RUN] Motor re-enabled: {reason}", timestamp=True)
                        if self.fan_speed == 0:
                            initial_speed = getattr(config, 'MOTOR_INITIAL_SPEED_PERCENT', 65)
                            new_spd = initial_speed
                        self.last_shutdown_reason = None

                    if is_man:
                        motor_min_speed = getattr(config, 'MOTOR_MIN_SPEED_PERCENT', 20)
                        if button_pressed == 'GREEN': new_spd = min(100, self.fan_speed + self.get_increase_step(self.fan_speed))
                        elif button_pressed == 'RED': new_spd = max(motor_min_speed, self.fan_speed - self.get_decrease_step(self.fan_speed))
                        if button_pressed: self._log_activity(f"[MANUAL] Speed: {new_spd:.1f}%", timestamp=True)

                    elif is_over:
                        if is_co_over:
                            target_min = self.co_override_min_speed
                        elif is_temp_over:
                            target_min = self.temp_override_min_speed
                        else:
                            target_min = self.humidity_override_min_speed

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
                                new_spd = target_min
                                self._log_activity(f"[OVERRIDE] Decrease blocked. Min speed enforced ({target_min}%).", timestamp=True)
                        elif self.fan_speed < target_min:
                            new_spd = target_min
                            self._log_activity(f"[OVERRIDE] Enforcing minimum speed: {target_min}%.", timestamp=True)

                    else:
                        motor_min_speed = getattr(config, 'MOTOR_MIN_SPEED_PERCENT', 20)
                        if button_pressed:
                            self.manual_mode = True
                            if button_pressed == 'GREEN': new_spd = min(100, self.fan_speed + self.get_increase_step(self.fan_speed))
                            elif button_pressed == 'RED': new_spd = max(motor_min_speed, self.fan_speed - self.get_decrease_step(self.fan_speed))
                            self._log_activity(f"[CONTROL] Manual Active. Speed: {new_spd:.1f}%", timestamp=True)
                            if self.oled_working:
                                try: oled.fill(0); oled.text("MANUAL ON",0,16); oled.show(); time.sleep(0.5)
                                except: self.oled_working=False

                    if new_spd != self.fan_speed: self.fan_speed = new_spd; self.motor.forward(self.fan_speed)

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

