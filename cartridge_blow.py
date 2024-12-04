import time
import board
import busio
import adafruit_ads1x15.ads1115 as ADS
from adafruit_ads1x15.analog_in import AnalogIn
import subprocess
import threading
import xml.etree.ElementTree as ET
import os
from datetime import datetime, timedelta

# Initialize ADC
i2c = busio.I2C(board.SCL, board.SDA)
ads = ADS.ADS1115(i2c)
wind_sensor = AnalogIn(ads, ADS.P3)

# Initialize variables
WIND_FLOOR = 2.35  # Minimum voltage to trigger alert
last_trigger_time = None
COOLDOWN_SECONDS = 10

time.sleep(10)

def launch_emulationstation():
    os.system('sudo systemctl restart getty@tty1')

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
    home_dir = os.path.expanduser('~pi')
    es_settings_path = os.path.join(home_dir, '.emulationstation', 'es_settings.cfg')
    
    try:
        with open(es_settings_path, 'r') as file:
            lines = file.readlines()
        
        for i, line in enumerate(lines):
            if '<string name="StartupSystem"' in line:
                lines[i] = f'<string name="StartupSystem" value="{new_system}" />\n'
                break
        
        with open(es_settings_path, 'w') as file:
            file.writelines(lines)
            
        print(f"Updated startup system to: {new_system}")
        
    except Exception as e:
        print(f"Error updating startup system: {e}")

def play_video_overlay(system):
    video_file = "gameboy_boot_overlay.mp4" if system == 'gb' else "nes_loading_overlay.mp4"
    video_path = f"/home/pi/{video_file}"
    
    cmd = f'su - pi -c "omxplayer --layer 10000 --aspect-mode stretch --adev alsa {video_path}"'
    subprocess.Popen(cmd, shell=True)
    time.sleep(0.5)

def determine_next_system():
    roms_path = "/home/pi/RetroPie/roms"
    gb_path = os.path.join(roms_path, "gb")
    nes_disabled_path = os.path.join(roms_path, "nes_disabled")
    
    if os.path.exists(gb_path) and os.path.exists(nes_disabled_path):
        return 'nes'
    return 'gb'

def update_theme_overlay(new_system):
    theme_file = "/etc/emulationstation/themes/es-theme-ssimple-ve/theme.xml"
    old_overlay = "nes_overlay.png" if new_system == 'gb' else "gb_overlay.png"
    new_overlay = "gb_overlay.png" if new_system == 'gb' else "nes_overlay.png"
    
    try:
        with open(theme_file, 'r') as f:
            content = f.read()
        
        if old_overlay in content:
            updated_content = content.replace(old_overlay, new_overlay)
            
            with open(theme_file, 'w') as f:
                f.write(updated_content)
                print(f"Updated theme overlay to: {new_overlay}")
                
    except Exception as e:
        print(f"Error updating theme overlay: {e}")

def toggle_system_folders():
    roms_path = "/home/pi/RetroPie/roms"
    
    gb_path = os.path.join(roms_path, "gb")
    gb_disabled_path = os.path.join(roms_path, "gb_disabled")
    nes_path = os.path.join(roms_path, "nes")
    nes_disabled_path = os.path.join(roms_path, "nes_disabled")
    
    if os.path.exists(gb_path) and os.path.exists(nes_disabled_path):
        os.rename(gb_path, gb_disabled_path)
        os.rename(nes_disabled_path, nes_path)
        update_startup_system('nes')
        update_theme_overlay('nes')
        print("Switched: Disabled GB and enabled NES")
        return 'nes'
    
    elif os.path.exists(nes_path) and os.path.exists(gb_disabled_path):
        os.rename(nes_path, nes_disabled_path)
        os.rename(gb_disabled_path, gb_path)
        update_startup_system('gb')
        update_theme_overlay('gb')
        print("Switched: Enabled GB and disabled NES")
        return 'gb'
    
    elif os.path.exists(gb_path) and os.path.exists(nes_path):
        os.rename(nes_path, nes_disabled_path)
        update_startup_system('gb')
        update_theme_overlay('gb')
        print("Both were enabled: Disabled NES, kept GB enabled")
        return 'gb'
    elif os.path.exists(gb_disabled_path) and os.path.exists(nes_disabled_path):
        os.rename(gb_disabled_path, gb_path)
        update_startup_system('gb')
        update_theme_overlay('gb')
        print("Both were disabled: Enabled GB")
        return 'gb'

def handle_trigger():
    global last_trigger_time
    
    # Wait for voltage to drop below threshold before proceeding
    while True:
        # Take two readings with a delay
        reading1 = wind_sensor.voltage
        time.sleep(0.5)
        reading2 = wind_sensor.voltage
        
        # If both readings are below threshold, we can proceed
        if reading1 < WIND_FLOOR and reading2 < WIND_FLOOR:
            break
    
    next_system = determine_next_system()
    play_video_overlay(next_system)
    
    subprocess.run(['killall', 'retroarch'])
    subprocess.run(['killall', 'emulationstation'])
    toggle_system_folders()
    move_gb_to_top_of_systems()
    
    print("Attempting to restart EmulationStation...")
    threading.Thread(target=launch_emulationstation).start()
    print("EmulationStation restart command sent")
    
    last_trigger_time = datetime.now()

# Main loop
while True:
    # Take first reading
    reading1 = wind_sensor.voltage
    time.sleep(0.1)
    # Take second reading
    reading2 = wind_sensor.voltage
    
    # Only trigger if both readings are at or above threshold
    if not is_cooldown_active() and reading1 >= WIND_FLOOR and reading2 >= WIND_FLOOR:
        print("\033[91m" + f"ALERT: Wind threshold exceeded!" + "\033[0m")
        print(f"First reading: {reading1:.2f}V")
        print(f"Second reading: {reading2:.2f}V")
        print("-" * 50)
        handle_trigger()
    
    time.sleep(0.5)