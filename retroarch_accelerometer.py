#!/usr/bin/env python3
import time
import board
import bma400
import subprocess
import os
import re
import configparser
from pathlib import Path

class RetroArchAccelerometerMonitor:
    def __init__(self):
        # Initialize I2C and accelerometer
        self.i2c = board.I2C()
        self.bma = bma400.BMA400(self.i2c)
        
        # Configuration paths
        self.config_path = "/opt/retropie/configs/all/retroarch.cfg"
        self.runcommand_log = "/dev/shm/runcommand.log"
        self.current_rotation = "0"
        
        # Default settings
        self.default_settings = {
            "input_overlay_enable": "true",
            "video_rotation": "0",
            "custom_viewport_height": "360",
            "custom_viewport_y": "0"
        }

    def manage_touch_keyboard(self, should_run):
        """Manage the touch-keyboard service."""
        try:
            action = "start" if should_run else "stop"
            print(f"{action.capitalize()}ing touch-keyboard service")
            subprocess.run(['sudo', 'systemctl', action, 'touch-keyboard.service'], check=False)
        except Exception as e:
            print(f"Error managing touch-keyboard service: {e}")

    def is_retroarch_running(self):
        """Check if RetroArch is currently running."""
        try:
            result = subprocess.run(['pgrep', 'retroarch'], capture_output=True, text=True)
            return result.returncode == 0
        except Exception as e:
            print(f"Error checking RetroArch process: {e}")
            return False
        
    def is_emulationstation_running(self):
        """Check if EmulationStation is currently running."""
        try:
            # Use ps to find EmulationStation processes
            result = subprocess.run(
                ['ps', 'aux'], 
                capture_output=True, 
                text=True
            )
            return 'emulationstatio' in result.stdout
        except Exception as e:
            print(f"Error checking EmulationStation process: {e}")
            return False

    def read_config(self):
        """Read the current RetroArch configuration."""
        config = {}
        try:
            with open(self.config_path, 'r') as f:
                for line in f:
                    if '=' in line:
                        key, value = line.strip().split('=', 1)
                        config[key.strip()] = value.strip()
        except Exception as e:
            print(f"Error reading config: {e}")
        return config

    def write_config(self, config):
        """Write the updated configuration to file."""
        try:
            with open(self.config_path, 'r') as f:
                lines = f.readlines()
            
            # Update existing lines
            for i, line in enumerate(lines):
                if '=' in line:
                    key = line.split('=')[0].strip()
                    if key in config:
                        lines[i] = f"{key} = {config[key]}\n"
            
            with open(self.config_path, 'w') as f:
                f.writelines(lines)
        except Exception as e:
            print(f"Error writing config: {e}")

    def get_retroarch_command(self):
        """Extract the RetroArch command from runcommand.log."""
        try:
            with open(self.runcommand_log, 'r') as f:
                content = f.read()
                match = re.search(r'Executing: (.+)$', content, re.MULTILINE)
                if match:
                    return match.group(1)
        except Exception as e:
            print(f"Error reading runcommand.log: {e}")
        return None

    def restart_retroarch(self):
        """Handle RetroArch restart sequence."""
        try:
            # 1. Kill RetroArch if it's running
            retroarch_was_running = self.is_retroarch_running()
            if retroarch_was_running:
                print("Killing RetroArch")
                subprocess.run(['killall', 'retroarch'], check=False)
            
            # 2. Configuration changes are handled by the caller (update_rotation method)
            
            # 3. Wait a second
            time.sleep(1)
            
            # 4. Relaunch RetroArch if it was running and we have a command
            if retroarch_was_running:
                command = self.get_retroarch_command()
                if command:
                    
                    # 5. Kill EmulationStation only if we've relaunched RetroArch
                    if self.is_emulationstation_running():
                        print("Killing EmulationStation")
                        subprocess.run(['killall', 'emulationstation'], check=False)
                        time.sleep(1)

                    print(f"Command: {command}")
                    print("Relaunching RetroArch")
                    subprocess.Popen(command, shell=True, start_new_session=True)

                else:
                    print("No RetroArch command found in log - skipping relaunch")
            else:
                print("RetroArch was not running - skipping relaunch")
                
        except Exception as e:
            print(f"Error in restart sequence: {e}")

    def reset_to_defaults(self):
        """Reset all settings to default values."""
        current_config = self.read_config()
        current_config.update(self.default_settings)
        self.write_config(current_config)
        self.manage_touch_keyboard(True)  # Ensure touch keyboard is running at startup
        print("Reset to default settings")

    def update_rotation(self, x_acceleration):
        """Update configuration based on X-axis acceleration."""
        current_config = self.read_config()
        new_rotation = "1" if x_acceleration >= 0.5 else "3" if x_acceleration <= -0.5 else "0"
        
        # Only update if rotation has changed
        if new_rotation != self.current_rotation:
            self.current_rotation = new_rotation
            
            # Update configuration
            updates = {
                "input_overlay_enable": "false",
                "video_rotation": new_rotation,
                "custom_viewport_height": "640",
                "custom_viewport_y": "80"
            }
            
            # Only update if not in default position
            if new_rotation != "0":
                current_config.update(updates)
                self.manage_touch_keyboard(False)  # Stop touch keyboard when rotated
            else:
                current_config.update(self.default_settings)
                self.manage_touch_keyboard(True)  # Start touch keyboard when back to normal
            
            # Write changes and restart RetroArch if it's running
            self.write_config(current_config)
            self.restart_retroarch()
            print(f"Updated rotation to {new_rotation}")

    def run(self):
        """Main monitoring loop."""
        print("Starting accelerometer monitoring...")
        self.reset_to_defaults()
        
        while True:
            try:
                accx, _, _ = self.bma.acceleration
                self.update_rotation(accx)
                time.sleep(0.5)
            except Exception as e:
                print(f"Error in monitoring loop: {e}")
                time.sleep(1)

if __name__ == "__main__":
    monitor = RetroArchAccelerometerMonitor()
    monitor.run()