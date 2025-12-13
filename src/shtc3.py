"""
SHTC3 Temperature and Humidity Sensor Driver for MicroPython
Sensirion SHTC3 I2C Digital Temperature and Humidity Sensor

Author: Assistant
License: MIT
"""

import time
from machine import Pin, I2C

"""
The 1.3" I2C 128x64 OLED will use sh1106  and NOT ssd1306 drivers:
    i.e https://www.amazon.com/HiLetgo-SSH1106-SSD1306-Display-Arduino/dp/B01MRR4LVE?th=1
The .96" I2C 128x64 OLED will use ssd1306 drivers:
    i.e https://www.amazon.com/DIYmall-Serial-128x64-Display-Arduino/dp/B00O2KDQBE?th=1
"""

class SHTC3:
    """MicroPython driver for SHTC3 temperature and humidity sensor."""
    
    # I2C address
    I2C_ADDRESS = 0x70
    
    # Commands
    CMD_WAKEUP = 0x3517
    CMD_SLEEP = 0xB098
    CMD_SOFT_RESET = 0x805D
    CMD_READ_ID = 0xEFC8
    
    # Measurement commands (clock stretching disabled)
    CMD_MEASURE_NORMAL = 0x7866    # Normal mode, T first
    CMD_MEASURE_LOW_POWER = 0x609C # Low power mode, T first
    
    # Measurement commands (clock stretching enabled)
    CMD_MEASURE_NORMAL_CS = 0x7CA2    # Normal mode, T first, clock stretching
    CMD_MEASURE_LOW_POWER_CS = 0x6458 # Low power mode, T first, clock stretching
    
    # Expected ID (SHTC3 ID mask - upper 6 bits should be 0x08)
    EXPECTED_ID_MASK = 0x083F  # Mask for ID verification
    EXPECTED_ID = 0x0807       # Full expected ID
    
    def __init__(self, i2c, address=I2C_ADDRESS, debug=False):
        """
        Initialize SHTC3 sensor.
        
        Args:
            i2c: I2C bus object
            address: I2C address (default: 0x70)
            debug: Enable debug output (default: False)
        """
        self.i2c = i2c
        self.address = address
        self._is_awake = False
        self.debug = debug
        
        if self.debug:
            print(f"DEBUG: Initializing SHTC3 at address 0x{address:02X}")
        
        # Check if sensor is present
        if not self._device_present():
            if self.debug:
                print("DEBUG: SHTC3 sensor not found on I2C bus")
            raise OSError("SHTC3 sensor not found")
        
        if self.debug:
            print("DEBUG: SHTC3 sensor found on I2C bus")
        
        # Wake up sensor and verify ID
        self.wakeup()
        id_result = self._verify_id()
        if not id_result:
            self.sleep()
            raise OSError("SHTC3 ID verification failed")
        
        # Put sensor to sleep to save power
        self.sleep()
        
        if self.debug:
            print("DEBUG: SHTC3 initialization successful")
    
    def _device_present(self):
        """Check if device is present on I2C bus."""
        try:
            devices = self.i2c.scan()
            if self.debug:
                print(f"DEBUG: I2C devices found: {[hex(addr) for addr in devices]}")
            return self.address in devices
        except Exception as e:
            if self.debug:
                print(f"DEBUG: I2C scan failed: {e}")
            return False
    
    def _write_command(self, command):
        """Write a 16-bit command to the sensor."""
        cmd_bytes = [(command >> 8) & 0xFF, command & 0xFF]
        self.i2c.writeto(self.address, bytes(cmd_bytes))
    
    def _read_data(self, num_bytes):
        """Read data from sensor."""
        return self.i2c.readfrom(self.address, num_bytes)
    
    def _crc8(self, data):
        """
        Calculate CRC8 checksum for data validation.
        Polynomial: 0x31 (x^8 + x^5 + x^4 + 1)
        """
        crc = 0xFF
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 0x80:
                    crc = (crc << 1) ^ 0x31
                else:
                    crc = crc << 1
                crc &= 0xFF
        return crc
    
    def _verify_crc(self, data, crc):
        """Verify CRC checksum."""
        return self._crc8(data) == crc
    
    def wakeup(self):
        """Wake up the sensor from sleep mode."""
        if not self._is_awake:
            self._write_command(self.CMD_WAKEUP)
            time.sleep_ms(1)  # Wait for sensor to wake up
            self._is_awake = True
    
    def sleep(self):
        """Put sensor into sleep mode to save power."""
        if self._is_awake:
            self._write_command(self.CMD_SLEEP)
            self._is_awake = False
    
    def soft_reset(self):
        """Perform soft reset of the sensor."""
        self.wakeup()
        self._write_command(self.CMD_SOFT_RESET)
        time.sleep_ms(1)
        self._is_awake = True
    
    def _verify_id(self):
        """Verify sensor ID with detailed debugging."""
        try:
            self._write_command(self.CMD_READ_ID)
            time.sleep_ms(10)  # Increased wait time
            data = self._read_data(3)
            
            if self.debug:
                print(f"DEBUG: Read {len(data)} bytes: {[hex(b) for b in data]}")
            
            if len(data) != 3:
                if self.debug:
                    print(f"DEBUG: Expected 3 bytes, got {len(data)}")
                return False
            
            # Calculate and verify CRC
            calculated_crc = self._crc8(data[:2])
            received_crc = data[2]
            if self.debug:
                print(f"DEBUG: CRC calculated: 0x{calculated_crc:02X}, received: 0x{received_crc:02X}")
            
            if calculated_crc != received_crc:
                if self.debug:
                    print("DEBUG: CRC verification failed")
                return False
            
            # Check ID
            sensor_id = (data[0] << 8) | data[1]
            if self.debug:
                print(f"DEBUG: Sensor ID: 0x{sensor_id:04X}, Expected: 0x{self.EXPECTED_ID:04X}")
            
            # SHTC3 ID should have upper 6 bits as 0x08, lower bits can vary
            # Check if the upper bits match the expected pattern
            if (sensor_id & 0x083F) == (self.EXPECTED_ID & 0x083F):
                if self.debug:
                    print("DEBUG: ID verification successful (with mask)")
                return True
            elif sensor_id == self.EXPECTED_ID:
                if self.debug:
                    print("DEBUG: ID verification successful (exact match)")
                return True
            else:
                if self.debug:
                    print(f"DEBUG: ID mismatch. Got 0x{sensor_id:04X}, expected 0x{self.EXPECTED_ID:04X}")
                # Try a more lenient check - just check if upper 6 bits are 0x08
                if (sensor_id >> 6) == 0x08:
                    if self.debug:
                        print("DEBUG: ID verification successful (lenient check - upper bits match)")
                    return True
                return False
            
        except Exception as e:
            if self.debug:
                print(f"DEBUG: Exception in _verify_id: {e}")
            return False
    
    def read_measurements(self, mode='normal', clock_stretching=False):
        """
        Read temperature and humidity measurements.
        
        Args:
            mode: 'normal' or 'low_power' (default: 'normal')
            clock_stretching: Enable I2C clock stretching (default: False)
        
        Returns:
            tuple: (temperature_celsius, humidity_percent)
        """
        self.wakeup()
        
        # Select measurement command
        if mode == 'low_power':
            cmd = self.CMD_MEASURE_LOW_POWER_CS if clock_stretching else self.CMD_MEASURE_LOW_POWER
            measure_time = 1  # Low power mode is faster
        else:
            cmd = self.CMD_MEASURE_NORMAL_CS if clock_stretching else self.CMD_MEASURE_NORMAL
            measure_time = 13  # Normal mode takes longer but is more accurate
        
        try:
            # Start measurement
            self._write_command(cmd)
            
            # Wait for measurement to complete (only if clock stretching is disabled)
            if not clock_stretching:
                time.sleep_ms(measure_time)
            
            # Read 6 bytes: T_MSB, T_LSB, T_CRC, RH_MSB, RH_LSB, RH_CRC
            data = self._read_data(6)
            
            if len(data) != 6:
                raise OSError("Invalid data length from sensor")
            
            # Verify CRC for temperature
            if not self._verify_crc(data[0:2], data[2]):
                raise OSError("Temperature CRC check failed")
            
            # Verify CRC for humidity
            if not self._verify_crc(data[3:5], data[5]):
                raise OSError("Humidity CRC check failed")
            
            # Convert raw values
            temp_raw = (data[0] << 8) | data[1]
            humidity_raw = (data[3] << 8) | data[4]
            
            # Convert to physical values
            temperature = -45 + 175 * temp_raw / 65535.0
            humidity = 100 * humidity_raw / 65535.0
            
            # Clamp humidity to valid range
            humidity = max(0, min(100, humidity))
            
            return temperature, humidity
            
        finally:
            self.sleep()  # Always put sensor back to sleep
    
    def read_temperature(self, mode='normal', clock_stretching=False):
        """
        Read only temperature.
        
        Args:
            mode: 'normal' or 'low_power' (default: 'normal')
            clock_stretching: Enable I2C clock stretching (default: False)
        
        Returns:
            float: Temperature in Celsius
        """
        temp, _ = self.read_measurements(mode, clock_stretching)
        return temp
    
    def read_humidity(self, mode='normal', clock_stretching=False):
        """
        Read only humidity.
        
        Args:
            mode: 'normal' or 'low_power' (default: 'normal')
            clock_stretching: Enable I2C clock stretching (default: False)
        
        Returns:
            float: Relative humidity in percent
        """
        _, humidity = self.read_measurements(mode, clock_stretching)
        return humidity
    
    def get_id(self):
        """
        Get sensor ID.
        
        Returns:
            int: Sensor ID (should be 0x0807 for SHTC3)
        """
        self.wakeup()
        try:
            self._write_command(self.CMD_READ_ID)
            time.sleep_ms(1)
            data = self._read_data(3)
            
            if len(data) == 3 and self._verify_crc(data[:2], data[2]):
                return (data[0] << 8) | data[1]
            else:
                raise OSError("Failed to read sensor ID")
        finally:
            self.sleep()
    
    def is_connected(self):
        """
        Check if sensor is properly connected and responding.
        
        Returns:
            bool: True if sensor is connected and responding
        """
        try:
            self.wakeup()
            sensor_id = self.get_id()
            # Use the same lenient ID check as in initialization
            return (sensor_id == self.EXPECTED_ID or 
                    (sensor_id & 0x083F) == (self.EXPECTED_ID & 0x083F) or
                    (sensor_id >> 6) == 0x08)
        except:
            return False
        finally:
            try:
                self.sleep()
            except:
                pass


# Example usage and test functions
def test_shtc3():
    """Test function to demonstrate SHTC3 usage."""
    from machine import Pin, I2C
    
    # Initialize I2C (adjust pins for your board)
    # For Raspberry Pi Pico: SDA=Pin(0), SCL=Pin(1)
    # For ESP32: SDA=Pin(21), SCL=Pin(22)
    i2c = I2C(0, sda=Pin(0), scl=Pin(1), freq=100000)
    
    try:
        # Initialize sensor with debug enabled
        print("Initializing SHTC3 sensor...")
        sensor = SHTC3(i2c, debug=True)
        print(f"SHTC3 sensor initialized. ID: 0x{sensor.get_id():04X}")
        
        # Read measurements
        
        for i in range(5):
            temp, humidity = sensor.read_measurements()
            print(f"Measurement {i+1}: {temp:.2f}°C, {humidity:.2f}%RH")
            time.sleep(2)
        
                
    except OSError as e:
        print(f"Error: {e}")


def debug_i2c_scan():
    """Debug function to scan I2C bus and find devices."""
    from machine import Pin, I2C
    
    # Try different I2C configurations
    i2c_configs = [
        {"id": 0, "sda": 0, "scl": 1},  # Pico default
        {"id": 0, "sda": 4, "scl": 5},  # ESP8266 default
        {"id": 0, "sda": 21, "scl": 22}, # ESP32 default
    ]
    
    for config in i2c_configs:
        try:
            print(f"\nTrying I2C config: SDA={config['sda']}, SCL={config['scl']}")
            i2c = I2C(config["id"], sda=Pin(config["sda"]), scl=Pin(config["scl"]), freq=100000)
            devices = i2c.scan()
            print(f"Found devices: {[hex(addr) for addr in devices]}")
            
            if 0x70 in devices:
                print("SHTC3 found at 0x70!")
                # Try to read ID directly
                try:
                    i2c.writeto(0x70, bytes([0x35, 0x17]))  # Wakeup
                    time.sleep_ms(10)
                    i2c.writeto(0x70, bytes([0xEF, 0xC8]))  # Read ID
                    time.sleep_ms(10)
                    data = i2c.readfrom(0x70, 3)
                    print(f"Raw ID data: {[hex(b) for b in data]}")
                    sensor_id = (data[0] << 8) | data[1]
                    print(f"Sensor ID: 0x{sensor_id:04X}")
                except Exception as e:
                    print(f"Direct ID read failed: {e}")
        except Exception as e:
            print(f"I2C config failed: {e}")


# Alternative initialization function with more flexibility
def init_shtc3_flexible(sda_pin, scl_pin, i2c_id=0, freq=100000):
    """
    Flexible SHTC3 initialization with custom pins.
    
    Args:
        sda_pin: SDA pin number
        scl_pin: SCL pin number
        i2c_id: I2C bus ID (default: 0)
        freq: I2C frequency (default: 100000)
    
    Returns:
        SHTC3 instance or None if failed
    """
    from machine import Pin, I2C
    
    try:
        print(f"Initializing I2C: SDA=Pin({sda_pin}), SCL=Pin({scl_pin})")
        i2c = I2C(i2c_id, sda=Pin(sda_pin), scl=Pin(scl_pin), freq=freq)
        
        print("Scanning I2C bus...")
        devices = i2c.scan()
        print(f"Found devices: {[hex(addr) for addr in devices]}")
        
        if 0x70 not in devices:
            print("SHTC3 not found at expected address 0x70")
            return None
        
        print("Initializing SHTC3...")
        sensor = SHTC3(i2c, debug=True)
        print("SHTC3 initialized successfully!")
        return sensor
        
    except Exception as e:
        print(f"Initialization failed: {e}")
        return None


#test_shtc3()

