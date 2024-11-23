#!/usr/bin/env python3
import time
import asyncio
import board
import busio
import adafruit_drv2605
from evdev import InputDevice, UInput, categorize, ecodes

# Touch regions with physical coordinates
TOUCH_REGIONS = [
    {'name': 'LOAD',   'key': [ecodes.KEY_L, ecodes.KEY_E], 'coords': (39, 388, 159, 437)},
    {'name': 'A BTN',  'key': ecodes.KEY_A,        'coords': (355, 508, 458, 609)},
    {'name': 'B BTN',  'key': ecodes.KEY_B,        'coords': (250, 509, 351, 608)},
    {'name': 'START',  'key': ecodes.KEY_ENTER,    'coords': (240, 685, 337, 728)},
    {'name': 'SELECT', 'key': ecodes.KEY_LEFTCTRL, 'coords': (156, 686, 240, 731)},
    {'name': 'RIGHT',  'key': ecodes.KEY_RIGHT,    'coords': (117, 534, 218, 594)},
    {'name': 'UP',     'key': ecodes.KEY_UP,       'coords': (79, 464, 162, 522)},
    {'name': 'LEFT',   'key': ecodes.KEY_LEFT,     'coords': (22,  523, 96,  594)},
    {'name': 'DOWN',   'key': ecodes.KEY_DOWN,     'coords': (87,  594, 159, 658)},
    {'name': 'SAVE',   'key': [ecodes.KEY_S, ecodes.KEY_E],     'coords': (168,  388, 309, 437)},
    {'name': 'EXIT',   'key': [ecodes.KEY_ENTER, ecodes.KEY_E],     'coords': (319, 388, 456, 438)}
    #{'name': 'IEWPORT',   'key': ecodes.KEY_ENTER, 'coords': (0, 0, 480, 388)}
]

VIEWPORT_REGION = {'name': 'VIEWPORT', 'key': ecodes.KEY_ENTER, 'coords': (0, 0, 480, 388)}

# Screen dimensions and scaling
PHYSICAL_WIDTH = 480
PHYSICAL_HEIGHT = 800
TOUCH_MAX_X = 799
TOUCH_MAX_Y = 479
X_SCALE = (TOUCH_MAX_X + 1) / PHYSICAL_WIDTH
Y_SCALE = (TOUCH_MAX_Y + 1) / PHYSICAL_HEIGHT

# Adjusted gesture detection parameters
SWIPE_MIN_DISTANCE = 60  # Reduced from 100
SWIPE_MIN_VERTICAL = 50  # Reduced from 80
SWIPE_MAX_OFF_AXIS = 70  # Increased from 50
SWIPE_COOLDOWN = 0.3     # Reduced from 0.5
VIEWPORT_TAP_TIMEOUT = 0.15  # Maximum time to wait before triggering viewport button

class TouchKeyboardMapper:
    def __init__(self, touch_device_path):
        self.touch_device = InputDevice(touch_device_path)
        print(f"Touch device: {self.touch_device.name}")
        
        # Initialize haptic controller
        i2c = busio.I2C(board.SCL, board.SDA)
        self.drv = adafruit_drv2605.DRV2605(i2c)
        self.drv.sequence[0] = adafruit_drv2605.Effect(1)
        print("Haptic controller initialized")

        # Track which buttons are currently active
        self.active_buttons = set()
        self.TOUCH_SIZE_THRESHOLD = 40
        
        # Convert touch regions
        self.touch_regions = []
        for region in TOUCH_REGIONS:
            x1, y1, x2, y2 = region['coords']
            touch_coords = (
                int(x1 * X_SCALE),
                int(y1 * Y_SCALE),
                int(x2 * X_SCALE),
                int(y2 * Y_SCALE)
            )
            self.touch_regions.append({
                'name': region['name'],
                'key': region['key'],
                'coords': touch_coords
            })
            print(f"Region {region['name']}: Physical ({x1},{y1})-({x2},{y2}) -> "
                  f"Touch {touch_coords}")

        # Convert viewport region
        x1, y1, x2, y2 = VIEWPORT_REGION['coords']
        self.viewport = {
            'name': VIEWPORT_REGION['name'],
            'key': VIEWPORT_REGION['key'],
            'coords': (
                int(x1 * X_SCALE),
                int(y1 * Y_SCALE),
                int(x2 * X_SCALE),
                int(y2 * Y_SCALE)
            )
        }
        print(f"Viewport: Physical ({x1},{y1})-({x2},{y2}) -> "
              f"Touch {self.viewport['coords']}")

        # Create virtual keyboard
        events = {
            ecodes.EV_KEY: [
                ecodes.KEY_ESC, ecodes.KEY_ENTER, ecodes.KEY_A, ecodes.KEY_B,
                ecodes.KEY_LEFTCTRL, ecodes.KEY_RIGHT, ecodes.KEY_UP,
                ecodes.KEY_LEFT, ecodes.KEY_DOWN, ecodes.KEY_E, ecodes.KEY_L, ecodes.KEY_S
            ]
        }
        self.virtual_keyboard = UInput(events, name="Virtual-Touch-Keyboard")
        
        # Improved multitouch handling
        self.touch_slots = {}
        self.current_slot = 0
        self.active_gestures = set()

    def check_touch_regions(self, x, y, touch_size=0):
        # Returns list of regions that should be active based on position and touch size
        active_regions = []
        
        # Check if we're in the RIGHT+B combo box (138x505 to 339x607)
        in_right_b_box = (138 * X_SCALE <= x <= 339 * X_SCALE and 
                         505 * Y_SCALE <= y <= 607 * Y_SCALE)
        
        # First check regular button regions
        for region in self.touch_regions:
            x1, y1, x2, y2 = region['coords']
            # If touch is directly in region
            if x1 <= x <= x2 and y1 <= y <= y2:
                active_regions.append(region)
                
                # If touch is large enough and we're in either A or B button,
                # check if we should activate both A+B
                if (touch_size >= self.TOUCH_SIZE_THRESHOLD and 
                    region['name'] in ['A BTN', 'B BTN']):
                    # Find and add the other button
                    other_button = 'B BTN' if region['name'] == 'A BTN' else 'A BTN'
                    for other_region in self.touch_regions:
                        if other_region['name'] == other_button:
                            active_regions.append(other_region)
                            break
        
        # Handle RIGHT+B combination box
        if in_right_b_box and touch_size >= self.TOUCH_SIZE_THRESHOLD:
            # Ensure both RIGHT and B are in active regions
            found_b = False
            found_right = False
            for region in active_regions:
                if region['name'] == 'B BTN':
                    found_b = True
                elif region['name'] == 'RIGHT':
                    found_right = True
            
            if not found_b:
                for region in self.touch_regions:
                    if region['name'] == 'B BTN':
                        active_regions.append(region)
                        break
            
            if not found_right:
                for region in self.touch_regions:
                    if region['name'] == 'RIGHT':
                        active_regions.append(region)
                        break
        
        return active_regions

    def is_in_viewport(self, x, y):
        x1, y1, x2, y2 = self.viewport['coords']
        return x1 <= x <= x2 and y1 <= y <= y2

    async def trigger_haptic(self):
        try:
            self.drv.play()
        except Exception as e:
            print(f"Haptic error: {e}")

    async def emit_key(self, key_code, value, region_name):
        timestamp = time.strftime("%H:%M:%S")
        event_type = "Press" if value == 1 else "Release"
        
        if isinstance(key_code, list):
            for key in key_code:
                self.virtual_keyboard.write(ecodes.EV_KEY, key, value)
                print(f"[{timestamp}] Key {event_type}: {region_name} (code: {key})")
        else:
            self.virtual_keyboard.write(ecodes.EV_KEY, key_code, value)
            print(f"[{timestamp}] Key {event_type}: {region_name} (code: {key_code})")
        
        if value == 1:
            await self.trigger_haptic()
        
        self.virtual_keyboard.syn()

    def can_trigger_swipe(self, slot_id):
        slot = self.touch_slots.get(slot_id, {})
        return (
            slot_id not in self.active_gestures and
            not slot.get('button_pressed', False) and
            time.time() - slot.get('last_swipe_time', 0) > SWIPE_COOLDOWN
        )

    async def process_tracking_id(self, event):
        slot = self.touch_slots.get(self.current_slot, {})
        if event.value == -1:  # Touch ended
            # Release any active buttons
            for button in slot.get('active_buttons', set()):
                for region in self.touch_regions:
                    if region['name'] == button:
                        await self.emit_key(region['key'], 0, region['name'])

            if self.current_slot in self.active_gestures:
                self.active_gestures.remove(self.current_slot)
            
            # Check for viewport tap
            if (slot.get('in_viewport', False) and 
                not slot.get('swipe_detected', False) and 
                not slot.get('button_pressed', False) and
                time.time() - slot.get('touch_start_time', 0) < VIEWPORT_TAP_TIMEOUT):
                await self.emit_key(self.viewport['key'], 1, "VIEWPORT")
                await self.emit_key(self.viewport['key'], 0, "VIEWPORT")
            
            self.touch_slots[self.current_slot] = {}
        else:  # New touch started
            self.touch_slots[self.current_slot] = {
                'tracking_id': event.value,
                'start_x': None,
                'start_y': None,
                'last_swipe_time': 0,
                'button_pressed': False,
                'touch_start_time': time.time(),
                'swipe_detected': False,
                'in_viewport': False,
                'active_buttons': set(),
                'touch_size': 0
            }

    async def update_active_buttons(self, slot, new_regions):
        """
        Updates the active buttons for a slot, with different behavior for directional keys
        """
        current_buttons = set()
        directional_keys = {'UP', 'DOWN', 'LEFT', 'RIGHT'}
        
        # First, handle directional keys - more sensitive to release
        old_directionals = {btn for btn in slot.get('active_buttons', set()) 
                          if btn in directional_keys}
        new_directionals = {region['name'] for region in new_regions 
                          if region['name'] in directional_keys}
        
        # Release any directional keys not directly in their regions
        for old_dir in old_directionals - new_directionals:
            for region in self.touch_regions:
                if region['name'] == old_dir:
                    await self.emit_key(region['key'], 0, region['name'])
        
        # Handle non-directional buttons with more forgiving state management
        new_regular_regions = [region for region in new_regions 
                             if region['name'] not in directional_keys]
        
        # Add all new regions to current buttons set
        for region in new_regions:
            current_buttons.add(region['name'])
            if region['name'] not in slot.get('active_buttons', set()):
                # Only emit key press for newly active buttons
                await self.emit_key(region['key'], 1, region['name'])
        
        # Only release non-directional buttons that are no longer in any active region
        old_non_directionals = {btn for btn in slot.get('active_buttons', set()) 
                              if btn not in directional_keys}
        for old_button in old_non_directionals - current_buttons:
            for region in self.touch_regions:
                if region['name'] == old_button:
                    await self.emit_key(region['key'], 0, region['name'])
        
        return current_buttons

    async def process_touch_position(self, event):
        slot = self.touch_slots.get(self.current_slot, {})
        
        if event.code == ecodes.ABS_MT_POSITION_X:
            slot['x'] = event.value
            if slot.get('start_x') is None:
                slot['start_x'] = event.value
        elif event.code == ecodes.ABS_MT_POSITION_Y:
            slot['y'] = event.value
            if slot.get('start_y') is None:
                slot['start_y'] = event.value
        elif event.code == ecodes.ABS_MT_TOUCH_MAJOR:
            slot['touch_size'] = event.value
        
        self.touch_slots[self.current_slot] = slot

        if 'x' in slot and 'y' in slot:
            touch_size = slot.get('touch_size', 0)

            # First check regular button regions
            regions = self.check_touch_regions(slot['x'], slot['y'], touch_size)
            
            # Handle button regions (non-viewport)
            if regions:
                # Update active buttons without unnecessary press/release cycles
                slot['active_buttons'] = await self.update_active_buttons(slot, regions)
                slot['button_pressed'] = True
                self.touch_slots[self.current_slot] = slot
                
            # Handle viewport region and gestures
            elif self.is_in_viewport(slot['x'], slot['y']):
                slot['in_viewport'] = True

                # Release any previously active buttons
                if slot.get('active_buttons'):
                    for old_button in slot['active_buttons']:
                        for region in self.touch_regions:
                            if region['name'] == old_button:
                                await self.emit_key(region['key'], 0, region['name'])
                    slot['active_buttons'] = set()

                if self.can_trigger_swipe(self.current_slot):
                    dx = slot['x'] - slot['start_x']
                    dy = slot['y'] - slot['start_y']
                    
                    # Check for horizontal swipe
                    if abs(dx) > SWIPE_MIN_DISTANCE and abs(dy) < SWIPE_MAX_OFF_AXIS:
                        key = ecodes.KEY_RIGHT if dx > 0 else ecodes.KEY_LEFT
                        await self.emit_key(key, 1, f"Swipe {'right' if dx > 0 else 'left'}")
                        await self.emit_key(key, 0, f"Swipe {'right' if dx > 0 else 'left'}")
                        slot['last_swipe_time'] = time.time()
                        slot['start_x'] = slot['x']
                        slot['start_y'] = slot['y']
                        slot['swipe_detected'] = True
                    
                    # Check for vertical swipe
                    elif abs(dy) > SWIPE_MIN_VERTICAL and abs(dx) < SWIPE_MAX_OFF_AXIS:
                        key = ecodes.KEY_DOWN if dy > 0 else ecodes.KEY_UP
                        await self.emit_key(key, 1, f"Swipe {'down' if dy > 0 else 'up'}")
                        await self.emit_key(key, 0, f"Swipe {'down' if dy > 0 else 'up'}")
                        slot['last_swipe_time'] = time.time()
                        slot['start_x'] = slot['x']
                        slot['start_y'] = slot['y']
                        slot['swipe_detected'] = True
                
                self.touch_slots[self.current_slot] = slot
            
            # If we're not in any region, release any active buttons
            else:
                if slot.get('active_buttons'):
                    for old_button in slot['active_buttons']:
                        for region in self.touch_regions:
                            if region['name'] == old_button:
                                await self.emit_key(region['key'], 0, region['name'])
                    slot['active_buttons'] = set()
                    slot['button_pressed'] = False
                    self.touch_slots[self.current_slot] = slot

    async def run(self):
        print("\nMonitoring touches... (Press Ctrl+C to exit)\n")
        
        async for event in self.touch_device.async_read_loop():
            if event.type == ecodes.EV_ABS:
                if event.code == ecodes.ABS_MT_SLOT:
                    self.current_slot = event.value
                elif event.code == ecodes.ABS_MT_TRACKING_ID:
                    await self.process_tracking_id(event)
                elif event.code in (ecodes.ABS_MT_POSITION_X, ecodes.ABS_MT_POSITION_Y):
                    await self.process_touch_position(event)

    def cleanup(self):
        self.virtual_keyboard.close()
        self.touch_device.close()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Touch to Keyboard mapper with haptic feedback")
    parser.add_argument('device', help="Touch input device (e.g., /dev/input/event1)")
    args = parser.parse_args()

    mapper = TouchKeyboardMapper(args.device)
    try:
        asyncio.run(mapper.run())
    except KeyboardInterrupt:
        print("\nExiting...")
    finally:
        mapper.cleanup()
