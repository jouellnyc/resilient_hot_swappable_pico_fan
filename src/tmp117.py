"""
TMP117 High-Precision Digital Temperature Sensor Driver for MicroPython

This driver provides a simple interface to the TMP117 temperature sensor
which communicates over I2C and provides temperature readings with 
±0.1°C accuracy and 0.0078125°C resolution.

Author: Assistant
License: MIT
"""

import time
from machine import I2C

class TMP117:
    # Default I2C address
    DEFAULT_ADDRESS = 0x48
    
    # Register addresses
    REG_TEMP_RESULT = 0x00
    REG_CONFIGURATION = 0x01
    REG_T_HIGH_LIMIT = 0x02
    REG_T_LOW_LIMIT = 0x03
    REG_EEPROM_UL = 0x04
    REG_EEPROM1 = 0x05
    REG_EEPROM2 = 0x06
    REG_TEMP_OFFSET = 0x07
    REG_EEPROM3 = 0x08
    REG_DEVICE_ID = 0x0F
    
    # Configuration register bits
    CONFIG_RESET = 0x0002
    CONFIG_ONE_SHOT = 0x0004
    CONFIG_CONV_CYCLE_MASK = 0x01C0
    CONFIG_AVG_MASK = 0x0060
    CONFIG_THERM_MODE = 0x0010
    CONFIG_POL = 0x0008
    CONFIG_DR_ALERT = 0x0004
    CONFIG_ALERT_EN = 0x0002
    CONFIG_EEPROM_BUSY = 0x4000
    CONFIG_DATA_READY = 0x2000
    CONFIG_LOW_ALERT = 0x8000
    CONFIG_HIGH_ALERT = 0x4000
    
    # Conversion cycle times (in bits for config register)
    CONV_15_5MS = 0x00
    CONV_125MS = 0x01
    CONV_250MS = 0x02
    CONV_500MS = 0x03
    CONV_1000MS = 0x04
    CONV_4000MS = 0x05
    CONV_8000MS = 0x06
    CONV_16000MS = 0x07
    
    # Averaging modes
    AVG_NONE = 0x00
    AVG_8 = 0x01
    AVG_32 = 0x02
    AVG_64 = 0x03
    
    # Temperature resolution (°C per LSB)
    TEMP_RESOLUTION = 0.0078125
    
    def __init__(self, i2c, address=DEFAULT_ADDRESS, verify_device=True):
        """
        Initialize TMP117 sensor
        
        Args:
            i2c: I2C object
            address: I2C address of the sensor (default: 0x48)
            verify_device: Whether to verify device ID (default: True)
        """
        self.i2c = i2c
        self.address = address
        
        # Check if device responds at given address
        try:
            self.i2c.writeto(self.address, b'')
        except OSError as e:
            raise RuntimeError(f"No device found at I2C address 0x{address:02X}. Check wiring and address.") from e
        
        if verify_device:
            try:
                # Verify device ID
                device_id = self._read_register(self.REG_DEVICE_ID)
                if device_id != 0x0117:
                    raise RuntimeError(f"Invalid device ID: 0x{device_id:04X}, expected 0x0117")
            except OSError as e:
                raise RuntimeError(f"Failed to read device ID. Check I2C connection.") from e
        
        # Perform soft reset
        try:
            self.reset()
        except OSError as e:
            raise RuntimeError(f"Failed to reset device. Check I2C connection.") from e
        
    def _read_register(self, reg):
        """Read a 16-bit register with error handling"""
        try:
            data = self.i2c.readfrom_mem(self.address, reg, 2)
            return (data[0] << 8) | data[1]
        except OSError as e:
            raise OSError(f"Failed to read register 0x{reg:02X} from TMP117") from e
    
    def _write_register(self, reg, value):
        """Write a 16-bit register with error handling"""
        try:
            data = bytes([(value >> 8) & 0xFF, value & 0xFF])
            self.i2c.writeto_mem(self.address, reg, data)
        except OSError as e:
            raise OSError(f"Failed to write register 0x{reg:02X} to TMP117") from e
    
    def reset(self):
        """Perform software reset"""
        config = self._read_register(self.REG_CONFIGURATION)
        self._write_register(self.REG_CONFIGURATION, config | self.CONFIG_RESET)
        time.sleep_ms(2)  # Wait for reset to complete
    
    def read_temperature(self):
        """
        Read temperature in Celsius
        
        Returns:
            float: Temperature in degrees Celsius
        """
        # Read temperature register
        temp_raw = self._read_register(self.REG_TEMP_RESULT)
        
        # Convert to signed 16-bit value
        if temp_raw & 0x8000:
            temp_raw = temp_raw - 0x10000
        
        # Convert to temperature
        return temp_raw * self.TEMP_RESOLUTION
    
    def read_temperature_f(self):
        """
        Read temperature in Fahrenheit
        
        Returns:
            float: Temperature in degrees Fahrenheit
        """
        celsius = self.read_temperature()
        return celsius * 9.0 / 5.0 + 32.0
    
    def set_conversion_cycle(self, cycle):
        """
        Set conversion cycle time
        
        Args:
            cycle: Conversion cycle constant (CONV_15_5MS, CONV_125MS, etc.)
        """
        config = self._read_register(self.REG_CONFIGURATION)
        config = (config & ~self.CONFIG_CONV_CYCLE_MASK) | ((cycle & 0x07) << 7)
        self._write_register(self.REG_CONFIGURATION, config)
    
    def set_averaging(self, avg):
        """
        Set averaging mode
        
        Args:
            avg: Averaging constant (AVG_NONE, AVG_8, AVG_32, AVG_64)
        """
        config = self._read_register(self.REG_CONFIGURATION)
        config = (config & ~self.CONFIG_AVG_MASK) | ((avg & 0x03) << 5)
        self._write_register(self.REG_CONFIGURATION, config)
    
    def set_high_limit(self, temp_c):
        """
        Set high temperature limit
        
        Args:
            temp_c: Temperature limit in Celsius
        """
        temp_raw = int(temp_c / self.TEMP_RESOLUTION)
        if temp_raw < 0:
            temp_raw = temp_raw + 0x10000
        self._write_register(self.REG_T_HIGH_LIMIT, temp_raw)
    
    def set_low_limit(self, temp_c):
        """
        Set low temperature limit
        
        Args:
            temp_c: Temperature limit in Celsius
        """
        temp_raw = int(temp_c / self.TEMP_RESOLUTION)
        if temp_raw < 0:
            temp_raw = temp_raw + 0x10000
        self._write_register(self.REG_T_LOW_LIMIT, temp_raw)
    
    def get_high_limit(self):
        """Get high temperature limit in Celsius"""
        temp_raw = self._read_register(self.REG_T_HIGH_LIMIT)
        if temp_raw & 0x8000:
            temp_raw = temp_raw - 0x10000
        return temp_raw * self.TEMP_RESOLUTION
    
    def get_low_limit(self):
        """Get low temperature limit in Celsius"""
        temp_raw = self._read_register(self.REG_T_LOW_LIMIT)
        if temp_raw & 0x8000:
            temp_raw = temp_raw - 0x10000
        return temp_raw * self.TEMP_RESOLUTION
    
    def enable_alert(self, enable=True):
        """Enable or disable alert functionality"""
        config = self._read_register(self.REG_CONFIGURATION)
        if enable:
            config |= self.CONFIG_ALERT_EN
        else:
            config &= ~self.CONFIG_ALERT_EN
        self._write_register(self.REG_CONFIGURATION, config)
    
    def is_data_ready(self):
        """Check if new temperature data is ready"""
        config = self._read_register(self.REG_CONFIGURATION)
        return bool(config & self.CONFIG_DATA_READY)
    
    def get_alert_status(self):
        """
        Get alert status
        
        Returns:
            dict: Alert status with 'high' and 'low' keys
        """
        config = self._read_register(self.REG_CONFIGURATION)
        return {
            'high': bool(config & self.CONFIG_HIGH_ALERT),
            'low': bool(config & self.CONFIG_LOW_ALERT)
        }
    
    def one_shot_measurement(self):
        """
        Trigger a one-shot measurement in shutdown mode
        """
        config = self._read_register(self.REG_CONFIGURATION)
        self._write_register(self.REG_CONFIGURATION, config | self.CONFIG_ONE_SHOT)
    
    def set_temperature_offset(self, offset_c):
        """
        Set temperature offset for calibration
        
        Args:
            offset_c: Offset in Celsius
        """
        offset_raw = int(offset_c / self.TEMP_RESOLUTION)
        if offset_raw < 0:
            offset_raw = offset_raw + 0x10000
        self._write_register(self.REG_TEMP_OFFSET, offset_raw)
    
    def get_temperature_offset(self):
        """Get current temperature offset in Celsius"""
        offset_raw = self._read_register(self.REG_TEMP_OFFSET)
        if offset_raw & 0x8000:
            offset_raw = offset_raw - 0x10000
        return offset_raw * self.TEMP_RESOLUTION


# Debugging and troubleshooting functions
def scan_i2c_devices(i2c):
    """Scan for I2C devices and return list of addresses"""
    devices = []
    for addr in range(0x08, 0x78):
        try:
            i2c.writeto(addr, b'')
            devices.append(addr)
        except OSError:
            pass
    return devices

def identify_device_at_address(i2c, address):
    """Try to identify what device is at a given address"""
    try:
        # Try reading first few bytes to see if we can identify the device
        data = i2c.readfrom(address, 2)
        print(f"Device at 0x{address:02X} responded with: {[hex(b) for b in data]}")
        
        # Try reading what would be device ID register for TMP117
        try:
            device_id_data = i2c.readfrom_mem(address, 0x0F, 2)
            device_id = (device_id_data[0] << 8) | device_id_data[1]
            print(f"  Register 0x0F (TMP117 device ID): 0x{device_id:04X}")
            if device_id == 0x0117:
                print("  This IS a TMP117!")
                return True
        except:
            print("  Cannot read register 0x0F")
            
        # Common device addresses
        if address == 0x3C or address == 0x3D:
            print("  Likely: OLED display (SSD1306/SH1106)")
        elif address == 0x48:
            print("  Could be: TMP117, ADS1115, or other sensor")
        elif address == 0x68:
            print("  Likely: RTC (DS1307/DS3231) or IMU (MPU6050)")
        elif address == 0x76 or address == 0x77:
            print("  Likely: BMP280/BME280 pressure sensor")
            
    except Exception as e:
        print(f"Error communicating with device at 0x{address:02X}: {e}")
    
    return False

def comprehensive_i2c_scan(i2c):
    """Comprehensive I2C scan with device identification"""
    print("=== Comprehensive I2C Device Scan ===")
    devices = scan_i2c_devices(i2c)
    
    if not devices:
        print("No I2C devices found!")
        print("\nTroubleshooting:")
        print("1. Check wiring connections")
        print("2. Verify power supply")
        print("3. Check I2C bus and pin configuration")
        return
    
    print(f"Found {len(devices)} I2C device(s):")
    
    for addr in devices:
        print(f"\n--- Device at 0x{addr:02X} ---")
        identify_device_at_address(i2c, addr)

def find_tmp117_address(i2c):
    """Scan all possible TMP117 addresses and test for valid device"""
    possible_addresses = [0x48, 0x49, 0x4A, 0x4B]
    
    print("Scanning for TMP117 at all possible addresses...")
    
    for addr in possible_addresses:
        print(f"\nTesting address 0x{addr:02X}:")
        if test_tmp117_connection(i2c, addr):
            return addr
    
    print("\nNo TMP117 found at any standard address.")
    print("Running comprehensive scan to identify connected devices...")
    comprehensive_i2c_scan(i2c)
    return None

def test_tmp117_connection(i2c, address=0x48):
    """Test TMP117 connection and print diagnostic info"""
    print(f"Testing TMP117 connection at address 0x{address:02X}")
    
    # Scan for I2C devices
    devices = scan_i2c_devices(i2c)
    print(f"Found I2C devices at addresses: {[hex(addr) for addr in devices]}")
    
    if address not in devices:
        print(f"ERROR: No device found at 0x{address:02X}")
        print("Check:")
        print("- Wiring (SDA, SCL, VCC, GND)")
        print("- Pull-up resistors on SDA/SCL lines")
        print("- I2C address (A0/A1 pins on TMP117)")
        print("- Power supply voltage")
        return False
    
    try:
        # Try to create TMP117 instance without device verification
        tmp117 = TMP117(i2c, address, verify_device=False)
        
        # Try to read device ID
        device_id = tmp117._read_register(tmp117.REG_DEVICE_ID)
        print(f"Device ID: 0x{device_id:04X}")
        
        if device_id == 0x0117:
            print("SUCCESS: TMP117 detected and responding correctly")
            
            # Try reading temperature
            temp = tmp117.read_temperature()
            print(f"Current temperature: {temp:.2f}°C")
            return True
        else:
            print(f"ERROR: Wrong device ID. Expected 0x0117, got 0x{device_id:04X}")
            return False
            
    except Exception as e:
        print(f"ERROR: {e}")
        return False

def test_both_i2c_buses():
    """Test both I2C buses on Pi Pico to find TMP117"""
    from machine import I2C, Pin
    
    print("=== Testing Both I2C Buses ===")
    
    # Test I2C0 on pins 0/1
    print("\n--- Testing I2C0 (pins 0/1) ---")
    try:
        i2c0 = I2C(0, scl=Pin(1), sda=Pin(0), freq=400000)
        print("I2C0 initialized successfully")
        devices0 = scan_i2c_devices(i2c0)
        print(f"I2C0 devices: {[hex(addr) for addr in devices0]}")
        
        for addr in devices0:
            if addr in [0x48, 0x49, 0x4A, 0x4B]:
                print(f"Testing potential TMP117 at 0x{addr:02X} on I2C0...")
                if test_tmp117_connection(i2c0, addr):
                    print(f"SUCCESS: Found TMP117 on I2C0 at address 0x{addr:02X}")
                    return i2c0, addr
        
        # Even if not at standard addresses, check all devices on this bus
        for addr in devices0:
            print(f"Checking device at 0x{addr:02X} on I2C0...")
            if identify_device_at_address(i2c0, addr):
                return i2c0, addr
                
    except Exception as e:
        print(f"Error with I2C0: {e}")
    
    # Test I2C1 on pins 14/15 (or other combinations)
    print("\n--- Testing I2C1 (pins 14/15) ---")
    try:
        i2c1 = I2C(1, scl=Pin(15), sda=Pin(14), freq=400000)
        print("I2C1 initialized successfully") 
        devices1 = scan_i2c_devices(i2c1)
        print(f"I2C1 devices: {[hex(addr) for addr in devices1]}")
        
        for addr in devices1:
            if addr in [0x48, 0x49, 0x4A, 0x4B]:
                print(f"Testing potential TMP117 at 0x{addr:02X} on I2C1...")
                if test_tmp117_connection(i2c1, addr):
                    print(f"SUCCESS: Found TMP117 on I2C1 at address 0x{addr:02X}")
                    return i2c1, addr
        
        # Even if not at standard addresses, check all devices on this bus
        for addr in devices1:
            print(f"Checking device at 0x{addr:02X} on I2C1...")
            if identify_device_at_address(i2c1, addr):
                return i2c1, addr
                
    except Exception as e:
        print(f"Error with I2C1: {e}")
    
    print("\nNo TMP117 found on either I2C bus")
    return None, None

def example_usage():
    """Example of how to use the TMP117 driver with error handling"""
    from machine import I2C, Pin
    
    try:
        print("Searching for TMP117 on both I2C buses...")
        
        # Test both buses to find TMP117
        i2c, address = test_both_i2c_buses()
        
        if not i2c:
            print("No TMP117 found on any I2C bus. Exiting.")
            return
        
        print(f"\nFound TMP117 at address 0x{address:02X}")
        
        # Initialize TMP117 sensor at found address
        tmp117 = TMP117(i2c, address)
        print("TMP117 initialized successfully")
        
        # Configure sensor
        tmp117.set_conversion_cycle(tmp117.CONV_250MS)
        tmp117.set_averaging(tmp117.AVG_8)
        
        # Set temperature limits
        tmp117.set_high_limit(30.0)  # 30°C
        tmp117.set_low_limit(10.0)   # 10°C
        tmp117.enable_alert(True)
        
        print("Starting temperature readings...")
        
        # Read temperature continuously
     
        for i in range(10):  # Read 10 times then exit
            temp_c = tmp117.read_temperature()
            temp_f = tmp117.read_temperature_f()
            
            print(f"Reading {i+1}: {temp_c:.4f}°C ({temp_f:.4f}°F)")
            #print(f"Reading {temp_c:.4f} C {temp_f:.4f} F)")
         
            # Check alerts
            alerts = tmp117.get_alert_status()
            if alerts['high']:
                print("HIGH TEMPERATURE ALERT!")
            if alerts['low']:
                print("LOW TEMPERATURE ALERT!")
            
            time.sleep(1)
            
    except Exception as e:
        print(f"Error: {e}")
        print("\nTroubleshooting tips:")
        print("1. Check wiring: VCC to 3.3V, GND to GND, SDA to SDA pin, SCL to SCL pin")
        print("2. Verify I2C pins match your board")
        print("3. Add pull-up resistors (4.7kΩ) to SDA and SCL if not built-in")
        print("4. Check TMP117 address pins (A0/A1) - default is 0x48")
        print("5. Try different I2C addresses: 0x48, 0x49, 0x4A, 0x4B")
        
        
        
