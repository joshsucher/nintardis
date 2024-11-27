import time
import board
import bmp384
import subprocess
import xml.etree.ElementTree as ET
import os
from collections import deque
from datetime import datetime, timedelta

# Initialize sensor
i2c = board.I2C()  # uses board.SCL and board.SDA
bmp = bmp384.BMP384(i2c)

# Initialize variables
readings = deque(maxlen=3)  # Rolling window of last 3 readings
first_reading = True  # Flag to ignore first reading
PRESSURE_THRESHOLD = 0.25  # Minimum pressure difference to trigger alert
last_trigger_time = None
COOLDOWN_SECONDS = 10

def get_rolling_average():
    return sum(readings) / len(readings)

def is_cooldown_active():
    if last_trigger_time is None:
        return False
    return (datetime.now() - last_trigger_time).total_seconds() < COOLDOWN_SECONDS

def move_gb_to_top_of_systems():
    xml_path = "/opt/retropie/configs/all/emulationstation/es_systems.cfg"
    tree = ET.parse(xml_path)
    root = tree.getroot()
    
    # Find the GB system
    systems = root.findall('system')
    gb_system = None
    for system in systems:
        if system.find('name').text == 'gb':
            gb_system = system
            break
    
    if gb_system is not None:
        # Remove GB system and insert at the beginning
        root.remove(gb_system)
        root.insert(0, gb_system)
        
        # Save the modified XML
        tree.write(xml_path)

def update_startup_system(new_system):
    # Get the path for the pi user's home directory
    home_dir = os.path.expanduser('~pi')
    es_settings_path = os.path.join(home_dir, '.emulationstation', 'es_settings.cfg')
    
    try:
        # Read the file lines
        with open(es_settings_path, 'r') as file:
            lines = file.readlines()
        
        # Find and replace the startup system line
        for i, line in enumerate(lines):
            if '<string name="StartupSystem"' in line:
                lines[i] = f'<string name="StartupSystem" value="{new_system}" />\n'
                break
        
        # Write the modified content back
        with open(es_settings_path, 'w') as file:
            file.writelines(lines)
            
        print(f"Updated startup system to: {new_system}")
        
    except Exception as e:
        print(f"Error updating startup system: {e}")
        # Continue execution even if this fails

def play_video_overlay(system):
    video_file = "gameboy_boot_overlay.mp4" if system == 'gb' else "nes_loading_overlay.mp4"
    # Construct full path to video file
    video_path = f"/home/pi/{video_file}"  # Adjust path as needed
    
    # Run omxplayer as the pi user with proper environment
    cmd = f'su - pi -c "omxplayer --layer 10000 --aspect-mode stretch --adev alsa {video_path}"'
    # Start the video and don't wait for it to finish
    subprocess.Popen(cmd, shell=True)
    # Give the video a moment to start
    time.sleep(0.5)

def determine_next_system():
    roms_path = "/home/pi/RetroPie/roms"
    gb_path = os.path.join(roms_path, "gb")
    nes_disabled_path = os.path.join(roms_path, "nes_disabled")
    
    # If GB is enabled and NES is disabled, we'll switch to NES
    if os.path.exists(gb_path) and os.path.exists(nes_disabled_path):
        return 'nes'
    return 'gb'  # Default to GB in all other cases

def update_theme_overlay(new_system):
    theme_file = "/etc/emulationstation/themes/es-theme-ssimple-ve/theme.xml"
    old_overlay = "nes_overlay.png" if new_system == 'gb' else "gb_overlay.png"
    new_overlay = "gb_overlay.png" if new_system == 'gb' else "nes_overlay.png"
    
    try:
        # Read the file content
        with open(theme_file, 'r') as f:
            content = f.read()
        
        # Only proceed if we find the old overlay reference
        if old_overlay in content:
            # Replace the overlay filename
            updated_content = content.replace(old_overlay, new_overlay)
            
            # Write the updated content back
            with open(theme_file, 'w') as f:
                f.write(updated_content)
                print(f"Updated theme overlay to: {new_overlay}")
                
    except Exception as e:
        print(f"Error updating theme overlay: {e}")

def toggle_system_folders():
    roms_path = "/home/pi/RetroPie/roms"
    
    # Check for GB folders
    gb_path = os.path.join(roms_path, "gb")
    gb_disabled_path = os.path.join(roms_path, "gb_disabled")
    
    # Check for NES folders
    nes_path = os.path.join(roms_path, "nes")
    nes_disabled_path = os.path.join(roms_path, "nes_disabled")
    
    # If GB is enabled and NES is disabled, switch them
    if os.path.exists(gb_path) and os.path.exists(nes_disabled_path):
        os.rename(gb_path, gb_disabled_path)
        os.rename(nes_disabled_path, nes_path)
        update_startup_system('nes')
        update_theme_overlay('nes')
        print("Switched: Disabled GB and enabled NES")
        return 'nes'
    
    # If NES is enabled and GB is disabled, switch them
    elif os.path.exists(nes_path) and os.path.exists(gb_disabled_path):
        os.rename(nes_path, nes_disabled_path)
        os.rename(gb_disabled_path, gb_path)
        update_startup_system('gb')
        update_theme_overlay('gb')
        print("Switched: Enabled GB and disabled NES")
        return 'gb'
    
    # Handle edge cases where both might be enabled or disabled
    elif os.path.exists(gb_path) and os.path.exists(nes_path):
        # Default to enabling GB and disabling NES if both are enabled
        os.rename(nes_path, nes_disabled_path)
        update_startup_system('gb')
        update_theme_overlay('gb')
        print("Both were enabled: Disabled NES, kept GB enabled")
        return 'gb'
    elif os.path.exists(gb_disabled_path) and os.path.exists(nes_disabled_path):
        # Default to enabling GB if both are disabled
        os.rename(gb_disabled_path, gb_path)
        update_startup_system('gb')
        update_theme_overlay('gb')
        print("Both were disabled: Enabled GB")
        return 'gb'

def handle_pressure_spike():
    global last_trigger_time
    
    # Figure out which system we're switching to before we start
    next_system = determine_next_system()
    
    # Start playing the appropriate video overlay
    play_video_overlay(next_system)
    
    # Now do all our system changes while video is playing
    subprocess.run(['killall', 'emulationstation'])
    toggle_system_folders()
    move_gb_to_top_of_systems()
    
    # Give the video a moment to play before restarting ES
    time.sleep(2)
    
    # Restart EmulationStation as pi user
    print("Attempting to restart EmulationStation...")
    os.system('su - pi -c "nohup emulationstation >/dev/null 2>&1 &"')
    print("EmulationStation restart command sent")
    
    # Update cooldown timer
    last_trigger_time = datetime.now()

# Main loop
while True:
    current_pressure = bmp.pressure
    
    if first_reading:
        first_reading = False
        time.sleep(0.5)
        continue
        
    if len(readings) == 3 and not is_cooldown_active():  # Only check if not in cooldown
        avg_pressure = get_rolling_average()
        pressure_difference = current_pressure - avg_pressure
        
        if pressure_difference >= PRESSURE_THRESHOLD:
            print("\033[91m" + f"ALERT: Pressure spike detected!" + "\033[0m")  # Red text
            print(f"Current: {current_pressure:.2f}hPa")
            print(f"Rolling avg: {avg_pressure:.2f}hPa")
            print(f"Difference: +{pressure_difference:.2f}hPa")
            print("-" * 50)
            handle_pressure_spike()
    
    readings.append(current_pressure)
    #print(f"Pressure: {current_pressure:.2f}hPa")
    time.sleep(0.5)
