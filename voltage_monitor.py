#!/usr/bin/python3
import time
import os
import board
import busio
import adafruit_ads1x15.ads1115 as ADS
from adafruit_ads1x15.analog_in import AnalogIn

# Create the I2C bus
i2c = busio.I2C(board.SCL, board.SDA)

# Create the ADC object using the I2C bus
ads = ADS.ADS1115(i2c)

# Create single-ended input on channel A3
chan = AnalogIn(ads, ADS.P3)

# Define the voltage threshold for shutdown (in volts)
VOLTAGE_THRESHOLD = 3.0  # Adjust this value based on your needs

def check_voltage():
    try:
        while True:
            # Get the voltage reading
            voltage = chan.voltage
            print(f"Current voltage: {voltage:.2f}V")
            
            # Check if voltage is below threshold
            if voltage < VOLTAGE_THRESHOLD:
                print("Voltage below threshold, initiating shutdown...")
                # Wait a moment to ensure it's not a momentary drop
                time.sleep(1)
                
                # Check voltage again to confirm
                if chan.voltage < VOLTAGE_THRESHOLD:
                    os.system("sudo shutdown -h now")
            
            # Wait before next reading
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("Monitoring stopped by user")
    except Exception as e:
        print(f"Error occurred: {e}")

if __name__ == "__main__":
    print("Starting voltage monitoring...")
    check_voltage()
