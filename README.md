# Resilient RTC Sensor Logger & Fan Controller

A production-ready environmental monitoring and fan control system for Raspberry Pi Pico, featuring intelligent override conditions, resilient sensor handling, and comprehensive logging.

## Features

### Core Functionality
- ✅ **Dual Temperature Sensors** - TMP117 and SHTC3 with automatic failover
- ✅ **Humidity Monitoring** - SHTC3 integrated humidity sensor
- ✅ **PWM Motor Control** - Variable speed fan control (20-100%)
- ✅ **OLED Display** - Real-time status display with night mode
- ✅ **External RTC** - DS3231 for accurate timekeeping with battery backup
- ✅ **Dual Button Interface** - Manual control with green (increase) and red (decrease) buttons

### Smart Control Logic
- ✅ **Priority Hierarchy** - Manual → Temperature Override → Humidity Override → Business Hours → Weekend
- ✅ **Environmental Overrides** - Temperature and humidity thresholds override time-based restrictions
- ✅ **Business Hours Scheduling** - Configurable days of week and time windows
- ✅ **Night Mode** - Auto-dim OLED display during configured hours

### Resilience & Reliability
- ✅ **Sensor Reading Cache** - Maintains last valid readings for 30 seconds during brief disconnections
- ✅ **Automatic Reconnection** - Sensors and display auto-recover from failures
- ✅ **RTC Drift Correction** - Hourly sync with external DS3231 when available
- ✅ **Fallback Operation** - Internal RTC runs unsynced if external RTC fails
- ✅ **Memory-Safe Log Pruning** - Activity log automatically maintained under 100KB

### Logging & Monitoring
- ✅ **CSV Data Logging** - Temperature, humidity, and status at configurable intervals
- ✅ **Activity Log** - Timestamped events including state transitions, overrides, errors
- ✅ **Comprehensive Status Messages** - Business hours transitions, sensor disconnects/reconnects, override events
- ✅ **Real-time OLED Display** - Date, time, temperatures, humidity, fan speed, operational status

### Advanced Features
- ✅ **Configurable Timing Intervals** - Main loop, sensor reads, logging, RTC sync all adjustable
- ✅ **Dual-Speed Architecture** - Fast button polling (10 Hz) + efficient sensor reads (1 Hz)
- ✅ **Minute-Precision Scheduling** - Business hours and night mode down to the minute
- ✅ **Speed Step Scaling** - Variable speed increments based on current fan speed
- ✅ **Override Minimum Enforcement** - Prevents manual reduction below environmental override thresholds

---

## Hardware Components

### Required Components

| Component | Model/Type | Purpose | Notes |
|-----------|------------|---------|-------|
| **Microcontroller** | Raspberry Pi Pico (RP2040) | Main controller | 133 MHz dual-core |
| **Temperature Sensor 1** | TMP117 | High-accuracy temp sensor | I2C address 0x48 |
| **Temp/Humidity Sensor** | SHTC3 | Temperature + humidity | I2C address 0x70 |
| **Real-Time Clock** | DS3231 | External RTC with battery | I2C address 0x68 |
| **Display** | SSD1306 OLED (128x64) | Status display | I2C (separate bus) |
| **Motor Driver** | L298N / L9110 / Similar | PWM motor control | Dual H-bridge |
| **Fan/Motor** | 12V DC Motor/Fan | Controlled device | Rated for motor driver |
| **Buttons** | 2x Momentary Push Buttons | Manual control | Active-low (pull-up) |
| **Power Supply** | 5V for Pico, 12V for motor | Power | Separate rails recommended |

### Pin Connections (Default Config)
```
Raspberry Pi Pico Pinout:
├─ GP0  (Pin 1)  → Sensor I2C SDA (TMP117 + SHTC3)
├─ GP1  (Pin 2)  → Sensor I2C SCL (TMP117 + SHTC3)
├─ GP12 (Pin 16) → RTC I2C SDA (DS3231)
├─ GP13 (Pin 17) → RTC I2C SCL (DS3231)
├─ GP16 (Pin 21) → Motor PWM (to motor driver)
├─ GP17 (Pin 22) → Motor IN1 (direction control)
├─ GP18 (Pin 24) → Motor IN2 (direction control)
├─ GP20 (Pin 26) → Green Button (speed up)
├─ GP21 (Pin 27) → Red Button (speed down)
└─ (Separate I2C) → OLED Display (SDA/SCL - see ssd_config.py)
```

---

## Important Considerations

### Before You Build

#### 1. **Power Requirements**
- **Pico**: 5V via USB or VSYS (up to 500mA for sensors)
- **Motor**: Typically 12V (check your motor specs)
- **Separate Grounds**: Connect all ground pins together (common ground)
- **Isolation**: Consider using separate power supplies for motor and logic

#### 2. **I2C Bus Design**
- **Two Separate I2C Buses**: Sensors on one bus, OLED on another (reduces conflicts)
- **Pull-up Resistors**: Most breakout boards have built-in 4.7kΩ resistors
- **Wire Length**: Keep I2C wires under 1 meter for reliability
- **Bus Speed**: 400kHz is standard, can reduce to 100kHz for long wires

#### 3. **Motor Driver Selection**
- **Current Rating**: Must exceed motor stall current (typically 2-3A for small fans)
- **PWM Frequency**: 1kHz is standard (audible), 20kHz+ is silent
- **Logic Level**: Ensure 3.3V compatible (Pico output voltage)
- **Heat Dissipation**: Add heatsink for continuous operation

#### 4. **Button Debouncing**
- **Hardware**: 0.1µF capacitor across button (optional, software handles it)
- **Pull-up**: Pico has internal pull-ups enabled
- **Active-Low**: Buttons connect pin to GND when pressed

#### 5. **RTC Battery Backup**
- **CR2032**: Standard coin cell for DS3231 (lasts 5-10 years)
- **First Boot**: May show incorrect time until first sync
- **Strict Policy**: System NEVER writes to external RTC (read-only)

### Code Configuration

#### Essential Files
```
project/
├── rtc_logger.py          # Main application (this file)
├── config.py              # All settings and constants
├── motor_control.py       # Motor driver interface
├── button_handler.py      # Button debouncing and state
├── rtc_driver.py          # DS3231 RTC driver
├── tmp117.py              # TMP117 sensor driver
├── shtc3.py               # SHTC3 sensor driver
└── ssd_config.py          # OLED display configuration
```

#### Key Configuration Items (config.py)
- **Business Hours**: Days of week and time windows
- **Override Thresholds**: Temperature (°F) and humidity (%) limits
- **Night Mode**: OLED display off hours
- **Timing Intervals**: How often sensors read, logs write, RTC syncs
- **Pin Assignments**: All GPIO mappings

### Operational Notes

#### 1. **Priority System (High to Low)**
```
1. Manual Mode (always runs, ignores everything)
2. Temperature Override (runs even outside business hours)
3. Humidity Override (runs even outside business hours)
4. After Hours (stops motor)
5. Weekend (stops motor)
6. Auto Mode (normal business hours operation)
```

#### 2. **Sensor Resilience**
- **30-Second Cache**: System maintains last valid readings during brief glitches
- **Auto-Reconnect**: Sensors automatically re-initialize when detected
- **Graceful Degradation**: System continues with one sensor if other fails

#### 3. **Logging Behavior**
- **CSV Log**: Temperature, humidity, status every 60 seconds (configurable)
- **Activity Log**: All events, state changes, errors with timestamps
- **Auto-Pruning**: Activity log kept under 100KB (last 1000 lines)
- **Log Files**: `sensor_log.csv` and `activity.log` in Pico root

#### 4. **Performance Characteristics**
- **Button Response**: ~100ms latency (10 Hz polling)
- **Sensor Updates**: 1 second refresh rate
- **OLED Refresh**: 10 Hz (smooth updates)
- **CPU Usage**: <5% typical (mostly idle)
- **Memory**: ~40KB Python heap usage

### Common Pitfalls to Avoid

❌ **Don't**: Connect motor power directly to Pico pins (use motor driver!)  
❌ **Don't**: Run motors without heat dissipation for driver  
❌ **Don't**: Forget common ground between Pico and motor power supply  
❌ **Don't**: Use long I2C wires without reducing bus speed  
❌ **Don't**: Set override thresholds lower than normal operating temps  

✅ **Do**: Test motor driver separately before integrating  
✅ **Do**: Add flyback diodes if using relay instead of PWM  
✅ **Do**: Calibrate sensor readings against known reference  
✅ **Do**: Monitor activity log during first week of operation  
✅ **Do**: Set realistic business hours for your environment  

---

## Quick Start

1. **Install MicroPython** on Raspberry Pi Pico
2. **Wire hardware** according to pin configuration above
3. **Upload all Python files** to Pico root directory
4. **Edit config.py** to match your environment and preferences
5. **Set DS3231 time** using external tool or manual script
6. **Run**: `import rtc_logger; rtc_logger.main()`

---

## System Output Examples

### Activity Log
```
[2025-11-22 08:00:00] [BUSINESS HOURS] Started at 08:00 (MO). Operating until 17:22
[2025-11-22 14:35:12] [OVERRIDE] Temperature (82.3F) detected. Forcing min speed 90%.
[2025-11-22 14:35:12] [RUN] Motor re-enabled: HIGH_TEMP_OVERRIDE_82.3
[2025-11-22 15:20:45] [AUTO] Override ended. Resuming normal operation (ALLOWED).
[2025-11-22 17:22:00] [AFTER HOURS] Business day ended at 17:22. Resuming at 08:00
```

### OLED Display
```
┌──────────────────────────┐
│ 11/22 FR  3:45PM         │
├──────────────────────────┤
│ TMP: 78.5F               │
│ SHT: 79.1F               │
│ HUM: 42.3%               │
│ FAN: 85%                 │
│ RUN: Auto                │
│ RTC: EXT (SYNC)          │
└──────────────────────────┘
```

---

## License

This project is provided as-is for educational and hobbyist use.

## Contributing

Feel free to fork, modify, and improve! Suggestions welcome.

---

**Version**: V9.9 (Robust Config + Optimized Sensor Reads)  
**Last Updated**: November 2025


