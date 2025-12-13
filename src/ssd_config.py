from machine import Pin, SoftI2C # Use SoftI2C for successful communication
import ssd1306
import time

# --- Configuration ---
# Use the proven SoftI2C setup with slower frequency
i2c_bus = SoftI2C(scl=Pin(15), sda=Pin(14), freq=100000)

display_width = 128
display_height = 64
oled_address = 0x3C  # Confirmed address (60 decimal)
# ---------------------

try:
    # Initialize the display object with the confirmed address
    oled = ssd1306.SSD1306_I2C(display_width, display_height, i2c_bus, addr=oled_address)
    print("OLED initialized successfully.")

    # 1. Clear the display buffer
    oled.fill(0) 

    # 2. Write the text "Hi"
    oled.text("Text...", 0, 0, 1)        
    # 3. Push the buffer content to the actual display
    oled.show()
    sleep=1
    print(f"Text displayed on OLED. Waiting {sleep} seconds...")
    time.sleep(sleep)
    
    # 4. Clear the screen again
    oled.fill(0)
    oled.show()
    
except Exception as e:
    print(f"An error occurred: {e}")
    print("The issue is now likely with the ssd1306.py file itself.")