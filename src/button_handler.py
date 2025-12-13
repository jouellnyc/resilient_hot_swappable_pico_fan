# File: button_handler.py
# Description: Handles debouncing and tracking state for the physical buttons.

from machine import Pin
import time
import config

class ButtonHandler:
    
    def __init__(self, debounce_delay_ms=200):
        self.debounce_delay = debounce_delay_ms
        
        # Define buttons dictionary using variable names from config.py
        self.buttons = {
            'green': {
                'pin': Pin(config.BUTTON_GREEN_PIN, Pin.IN, Pin.PULL_UP),
                'last_press_time': 0,
                'state': 1 # Assuming PULL_UP means 1 is released, 0 is pressed
            },
            'red': {
                'pin': Pin(config.BUTTON_RED_PIN, Pin.IN, Pin.PULL_UP),
                'last_press_time': 0,
                'state': 1
            }
        }
        
    def check_press(self, button_name):
        """Checks if a button has been pressed and debounced."""
        btn = self.buttons.get(button_name)
        if not btn:
            return False

        current_value = btn['pin'].value()
        current_time = time.ticks_ms()
        
        # Check if the button is currently pressed (value 0 for PULL_UP)
        if current_value == 0:
            # Check for debouncing delay
            if time.ticks_diff(current_time, btn['last_press_time']) > self.debounce_delay:
                btn['last_press_time'] = current_time
                # Return True only on the leading edge (the moment it's pressed)
                # The state tracking in this implementation is simplified for a clean return.
                return True
        
        return False