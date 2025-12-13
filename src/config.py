# config.py
# Configuration settings for Resilient RTC Sensor Logger
# =========================================================

# =============================================================================
# HARDWARE PINS
# =============================================================================

# --- Motor Control Pins ---
MOTOR_PWM_PIN = 16
MOTOR_IN1_PIN = 17 
MOTOR_IN2_PIN = 18
MOTOR_PWM_FREQUENCY = 1000  # PWM frequency in Hz (1kHz standard for motors)

# --- Button Pins ---
BUTTON_GREEN_PIN = 20
BUTTON_RED_PIN = 21

# --- Sensor I2C Bus (SHTC3 / TMP117) ---
SENSOR_I2C_SDA_PIN = 0
SENSOR_I2C_SCL_PIN = 1
I2C_FREQUENCY = 400000  # 400kHz


# =============================================================================
# MOTOR CONTROL SETTINGS
# =============================================================================

MOTOR_INITIAL_SPEED_PERCENT = 65  # Starting speed when fan turns on
MOTOR_MIN_SPEED_PERCENT = 20      # Minimum speed to prevent stalling


# =============================================================================
# ENVIRONMENTAL OVERRIDE THRESHOLDS
# =============================================================================

# --- Temperature Override ---
# If temp goes above this (Fahrenheit), override business hours and run fan
TEMP_OVERRIDE_THRESHOLD_F = 78.0
TEMP_OVERRIDE_MIN_SPEED = 90  # Minimum fan speed during temp override

# --- Humidity Override ---
# If humidity goes above this (%), override business hours and run fan
HUMIDITY_OVERRIDE_THRESHOLD = 43.0
HUMIDITY_OVERRIDE_MIN_SPEED = 80  # Minimum fan speed during humidity override


# =============================================================================
# BUSINESS HOURS SCHEDULE
# =============================================================================

# --- Days of Operation (0=Monday, 6=Sunday) ---
BUSINESS_DAYS_START = 0  # Monday
BUSINESS_DAYS_END = 4    # Friday

# --- Daily Operating Hours (24-hour format) ---
BUSINESS_HOUR_START = 8
BUSINESS_MINUTE_START = 0
BUSINESS_HOUR_END = 17
BUSINESS_MINUTE_END = 22


# =============================================================================
# NIGHT MODE (OLED Display Off)
# =============================================================================

# --- Night Mode Start (Display turns off) ---
NIGHT_MODE_START_HOUR = 23
NIGHT_MODE_START_MINUTE = 0

# --- Night Mode End (Display turns on) ---
NIGHT_MODE_END_HOUR = 7
NIGHT_MODE_END_MINUTE = 0


# =============================================================================
# TIMING INTERVALS
# =============================================================================

# --- System Loop Timing ---
MAIN_LOOP_INTERVAL_SECONDS = 0.1      # Button checking, display updates (10 Hz)
SENSOR_READ_INTERVAL_SECONDS = 1.0    # Temperature/humidity sensor reads (1 Hz)
LOGGING_INTERVAL_SECONDS = 60         # CSV file write interval (1 minute)

# --- RTC Sync Timing ---
RTC_SYNC_NORMAL_INTERVAL_SECONDS = 3600  # Drift correction when RTC working (1 hour)
RTC_SYNC_RETRY_INTERVAL_SECONDS = 30     # Retry interval when RTC failed (30 sec)

# --- Sensor Cache ---
SENSOR_CACHE_TIMEOUT_SECONDS = 30  # Keep last readings during brief disconnections


# =============================================================================
# FILE SETTINGS
# =============================================================================

LOG_FILE = "sensor_log.csv"      # CSV data log file
ACTIVITY_LOG_FILE = "activity.log"  # Activity/event log file