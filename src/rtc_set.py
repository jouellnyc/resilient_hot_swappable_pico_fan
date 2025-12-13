# Save this as rtc_set.py
# Use this utility to set the internal and external DS3231 RTCs.

from machine import RTC
from rtc_driver import set_ds3231_from_target # Import the utility function from the new driver

# --- Configuration: CHANGE THIS TO YOUR CURRENT TIME ---
# Format: (Year, Month, Day, Hour, Minute, Second)
# Update this if your time has drifted or been lost.
TARGET_TIME = (2025, 11, 16, 18, 56, 0) 

if __name__ == "__main__":
    # The imported function handles setting both internal and external RTCs.
    set_ds3231_from_target(TARGET_TIME)
    print("\n--- Time Set Complete ---")
    print("Please re-run 'rtc_logger.py' now to start logging with the correct time.")