# main.py
# Entry point for the MicroPython application.

import rtc_logger

# Start the application instance
if __name__ == "__main__":
    rtc_logger.main()

# Note: The logger uses rtc_set.py (not provided here) 
# to set the initial time. If the time is unset, the logger 
# will start, but logging dates will be incorrect until a time is set 
# via rtc_set.py or external RTC syncs correctly.