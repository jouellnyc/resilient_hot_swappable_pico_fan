#  Dedicated driver for AT24C-series EEPROM on DS3231 Module

from machine import Pin, I2C
import time
import struct # Required for packing/unpacking multi-byte data (like 5150)

# --- I2C CONSTANTS (The ESSENTIAL Hardware Defaults) ---

# The I2C Device Address for the AT24C32/64 chip (common address when A0-A2 are grounded).
EEPROM_ADDR = 0x57      
# The fixed memory address for single-byte configuration data (1-byte wide).
CONFIG_ADDR = 0x0001     
# CRITICAL: Address size must be 16-bit (2 bytes) to access the 4KB+ memory map.
ADDR_SIZE = 16          
# Standard I2C initialization defaults (change pins/bus if your wiring is different).
I2C_BUS = 0             
SDA_PIN = 12            
SCL_PIN = 13            
I2C_FREQ = 400000       
# Required delay for the EEPROM chip to complete its internal flash write cycle.
WRITE_TIME_MS = 5       

# Global I2C object (initialized by init() function)
i2c = None

# --- CONSTANTS FOR 16-BIT INTEGER STORAGE ---

# Example starting address for 16-bit integer data (2 bytes wide).
INT_16_ADDR = 0x0100 
# '<h' means: Little-endian (<) Short Integer (h), which is 2 bytes.
INT_16_FORMAT = '<h'


def init():
    """Initializes the I2C bus and verifies the EEPROM is present."""
    global i2c
    try:
        # Set up the I2C bus on the Pico.
        i2c = I2C(I2C_BUS, sda=Pin(SDA_PIN), scl=Pin(SCL_PIN), freq=I2C_FREQ)
        
        # Verify the EEPROM device is responding on the bus.
        if EEPROM_ADDR not in i2c.scan():
            raise OSError(f"EEPROM not found at address {hex(EEPROM_ADDR)}")
            
        print(f"EEPROM module initialized at {hex(EEPROM_ADDR)}")
        return True
    except Exception as e:
        print(f"ERROR: Initialization failed: {e}")
        i2c = None
        return False

# ----------------------------------------------------------------------
# --- FUNCTIONS FOR SINGLE-BYTE (0-255) STORAGE ---
# ----------------------------------------------------------------------

def save_value(value):
    """
    Saves a single byte (0-255) to the fixed CONFIG_ADDR (0x0001).
    Args: value (int): The 8-bit value to store.
    """
    if not i2c: return False
    
    # NOTE: The hardware will truncate values > 255 using modulo 256.
    if not 0 <= value <= 255:
        print("WARNING: Value exceeds 1 byte capacity (0-255) and will be truncated.")

    try:
        # Convert the integer into a single-byte array for transmission.
        data_bytes = bytearray([value])
        
        # Write the data. Uses fixed EEPROM_ADDR, CONFIG_ADDR, and 16-bit ADDR_SIZE.
        i2c.writeto_mem(EEPROM_ADDR, CONFIG_ADDR, data_bytes, addrsize=ADDR_SIZE)
        time.sleep_ms(WRITE_TIME_MS)
        return True
    except OSError as e:
        print(f"ERROR: Failed to save value: {e}")
        return False

def load_value():
    """
    Loads the single byte (0-255) from the fixed CONFIG_ADDR (0x0001).
    Returns: int: The stored 8-bit integer, or None on failure.
    """
    if not i2c: return None

    try:
        # Read exactly 1 byte. Uses fixed EEPROM_ADDR, CONFIG_ADDR, and 16-bit ADDR_SIZE.
        bytes_read = i2c.readfrom_mem(EEPROM_ADDR, CONFIG_ADDR, 1, addrsize=ADDR_SIZE)
        
        # Return the integer value from the 1-byte result array.
        return bytes_read[0]
    except OSError as e:
        print(f"ERROR: Failed to load value: {e}")
        return None

# ----------------------------------------------------------------------
# --- FUNCTIONS FOR 16-BIT INTEGER (e.g., 5150) STORAGE ---
# ----------------------------------------------------------------------

def save_large_int(address, value):
    """
    Saves a 16-bit signed integer (-32768 to 32767) across two consecutive bytes.
    Args: 
        address (int): The starting memory address (e.g., 0x0100).
        value (int): The integer to store (e.g., 5150).
    """
    if not i2c: return False
    
    # Check bounds for a standard 16-bit signed integer (necessary for struct.pack).
    if not -32768 <= value <= 32767:
        print("ERROR: Value must be a 16-bit signed integer (-32768 to 32767).")
        return False

    try:
        # Use struct to convert the Python integer into a 2-byte sequence.
        data_bytes = struct.pack(INT_16_FORMAT, value)
        
        # Write the 2 bytes starting at the provided address.
        i2c.writeto_mem(EEPROM_ADDR, address, data_bytes, addrsize=ADDR_SIZE)
        time.sleep_ms(WRITE_TIME_MS)
        print(f"Stored large integer '{value}' across two bytes starting at {hex(address)}")
        return True
    except OSError as e:
        print(f"ERROR: Failed to write large int: {e}")
        return False

def load_large_int(address):
    """
    Loads a 16-bit integer from two consecutive bytes.
    Args: address (int): The starting memory address (e.g., 0x0100).
    Returns: int: The loaded 16-bit integer, or None on failure.
    """
    if not i2c: return None

    try:
        # Read exactly 2 bytes from the starting address.
        bytes_read = i2c.readfrom_mem(EEPROM_ADDR, address, 2, addrsize=ADDR_SIZE)
        
        # Use struct to convert the 2-byte sequence back into a single integer.
        return struct.unpack(INT_16_FORMAT, bytes_read)[0]
    except OSError as e:
        print(f"ERROR: Failed to load large int: {e}")
        return None