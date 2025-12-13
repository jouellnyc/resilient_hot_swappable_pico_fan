# DS3231 RTC Driver (rtc_driver.py)
# This module encapsulates the logic for interacting with the external DS3231 RTC.

from machine import SoftI2C, Pin
import time

# --- Helper Functions for BCD conversion ---
def dec_to_bcd(dec):
    """Convert decimal number to BCD format for DS3231"""
    return (dec // 10) << 4 | (dec % 10)

def bcd_to_dec(bcd):
    """Convert BCD format from DS3231 to decimal number"""
    return (bcd >> 4) * 10 + (bcd & 0x0F)

class DS3231_RTC:
    """Driver for the external DS3231 Real-Time Clock module."""
    
    ADDRESS = 0x68
    
    def __init__(self, sda_pin=12, scl_pin=13, freq=100000):
        # Initialize I2C bus (SoftI2C is used for reliability)
        self.i2c = SoftI2C(sda=Pin(sda_pin), scl=Pin(scl_pin), freq=freq)
        self.is_present = self.ADDRESS in self.i2c.scan()
        
        if not self.is_present:
            print(f"[WARN] DS3231 not found at {hex(self.ADDRESS)}")

    def read_time(self):
        """
        Reads time from the DS3231.
        Returns a tuple: (year, month, day, hour, minute, second) or None if error/not present.
        """
        if not self.is_present:
            return None
            
        try:
            # Read 7 bytes starting from register 0x00
            data = self.i2c.readfrom_mem(self.ADDRESS, 0x00, 7)
            
            second = bcd_to_dec(data[0] & 0x7F)
            minute = bcd_to_dec(data[1] & 0x7F)
            hour = bcd_to_dec(data[2] & 0x3F) # 24-hour mode
            day = bcd_to_dec(data[4] & 0x3F)
            month = bcd_to_dec(data[5] & 0x1F)
            year = bcd_to_dec(data[6]) + 2000
            
            # Basic validation
            if 2020 <= year <= 2030 and 1 <= month <= 12 and 1 <= day <= 31:
                return (year, month, day, hour, minute, second)
            else:
                return None # Time is invalid (e.g., reset to 2000-01-01)
                
        except Exception as e:
            print(f"[ERROR] Failed to read DS3231 time: {e}")
            return None

    def set_time(self, year, month, day, hour, minute, second):
        """Sets the time on the DS3231."""
        if not self.is_present:
            print("[WARN] Cannot set time: DS3231 not present.")
            return False
            
        try:
            # Data array: [Second, Minute, Hour, Day of Week, Day of Month, Month/Century, Year]
            data = bytearray(7)
            data[0] = dec_to_bcd(second)  # Seconds (0x00)
            data[1] = dec_to_bcd(minute)  # Minutes (0x01)
            data[2] = dec_to_bcd(hour)    # Hours (0x02, 24-hour mode)
            data[3] = dec_to_bcd(1)       # Day of Week (0x03, placeholder=Sunday=1)
            data[4] = dec_to_bcd(day)     # Day of Month (0x04)
            data[5] = dec_to_bcd(month)   # Month (0x05)
            data[6] = dec_to_bcd(year % 100) # Year (0x06)

            self.i2c.writeto_mem(self.ADDRESS, 0x00, data)
            return True
            
        except Exception as e:
            print(f"[ERROR] Failed to write time to DS3231: {e}")
            return False

# Example usage (for testing/setting):
# To set the time, we can still use the previous approach but import this class
def set_ds3231_from_target(target_time):
    """
    Utility function to set the DS3231 RTC. 
    (Year, Month, Day, Hour, Minute, Second)
    """
    Y, M, D, H, MI, S = target_time
    print(f"Attempting to set DS3231 RTC to: {Y:04d}-{M:02d}-{D:02d} {H:02d}:{MI:02d}:{S:02d}")
    
    # RTC pins are 12 and 13 as defined in your setup
    ds3231 = DS3231_RTC(sda_pin=12, scl_pin=13)
    
    if ds3231.set_time(Y, M, D, H, MI, S):
        print("DS3231 RTC successfully set.")
        # Also set internal RTC for immediate use
        rtc_internal = RTC()
        rtc_internal.datetime((Y, M, D, 0, H, MI, S, 0))
        print(f"Internal RTC also set to: {rtc_internal.datetime()}")
    else:
        print("Failed to set DS3231 RTC.")

# Remove the 'if __name__ == "__main__":' block from rtc_set.py
# We can use a simplified, temporary rtc_set.py for setting purposes if needed,
# but the core logic is now here.