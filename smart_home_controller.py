# ==========================================
# N.O.V.A. - Smart Home Device Controller & IoT Emulator
# Manages virtual IoT states (Lights, Plugs, Thermostats, Locks)
# with persistent JSON state storage and tactical voice intent parsing
# Fully compatible with Python 3.14.7 runtime
# ==========================================
import os
import json
import re
import datetime
from typing import Tuple, Dict, Any, Optional

DEVICES_FILE = "smart_home_devices.json"

DEFAULT_DEVICES = {
    # --- LIGHTING ---
    "living_room_lights": {
        "id": "living_room_lights",
        "name": "Living Room Lights",
        "aliases": ["living room light", "living room lights", "lounge light", "main lights", "hall lights"],
        "type": "light",
        "room": "Living Room",
        "power": "off",
        "brightness": 100,
        "color": "warm white"
    },
    "bedroom_light": {
        "id": "bedroom_light",
        "name": "Bedroom Light",
        "aliases": ["bedroom light", "bedroom lights", "bed light", "master bedroom light"],
        "type": "light",
        "room": "Bedroom",
        "power": "off",
        "brightness": 75,
        "color": "soft white"
    },
    "kitchen_light": {
        "id": "kitchen_light",
        "name": "Kitchen Light",
        "aliases": ["kitchen light", "kitchen lights", "cooking light"],
        "type": "light",
        "room": "Kitchen",
        "power": "off",
        "brightness": 100,
        "color": "daylight"
    },
    "office_lamp": {
        "id": "office_lamp",
        "name": "Office Lamp",
        "aliases": ["office lamp", "office light", "desk lamp", "desk light", "study light"],
        "type": "light",
        "room": "Office",
        "power": "off",
        "brightness": 90,
        "color": "cool white"
    },

    # --- SMART PLUGS & APPLIANCES ---
    "coffee_maker": {
        "id": "coffee_maker",
        "name": "Coffee Maker",
        "aliases": ["coffee maker", "coffee machine", "espresso machine", "coffee plug"],
        "type": "plug",
        "room": "Kitchen",
        "power": "off",
        "wattage": 0,
        "active_wattage": 1200
    },
    "living_room_plug": {
        "id": "living_room_plug",
        "name": "Living Room Plug",
        "aliases": ["living room plug", "tv plug", "entertainment plug"],
        "type": "plug",
        "room": "Living Room",
        "power": "off",
        "wattage": 0,
        "active_wattage": 250
    },
    "office_charger": {
        "id": "office_charger",
        "name": "Office Charger",
        "aliases": ["office charger", "laptop charger", "desk plug"],
        "type": "plug",
        "room": "Office",
        "power": "on",
        "wattage": 65,
        "active_wattage": 65
    },

    # --- THERMOSTATS & CLIMATE ---
    "thermostat": {
        "id": "thermostat",
        "name": "Main Thermostat",
        "aliases": ["thermostat", "main thermostat", "ac", "air conditioner", "temperature", "climate"],
        "type": "thermostat",
        "room": "Central",
        "target_temperature": 22,
        "current_temperature": 24,
        "unit": "Celsius",
        "mode": "cool"
    },
    "bedroom_ac": {
        "id": "bedroom_ac",
        "name": "Bedroom AC",
        "aliases": ["bedroom ac", "bedroom thermostat", "bedroom air conditioner"],
        "type": "thermostat",
        "room": "Bedroom",
        "target_temperature": 21,
        "current_temperature": 23,
        "unit": "Celsius",
        "mode": "cool"
    },

    # --- LOCKS & PERIMETER ---
    "front_door": {
        "id": "front_door",
        "name": "Front Door Lock",
        "aliases": ["front door", "front door lock", "main entrance", "front lock"],
        "type": "lock",
        "room": "Entrance",
        "locked": True,
        "battery": 94
    },
    "back_door": {
        "id": "back_door",
        "name": "Back Door Lock",
        "aliases": ["back door", "back door lock", "patio lock", "patio door"],
        "type": "lock",
        "room": "Patio",
        "locked": True,
        "battery": 89
    },
    "garage_door": {
        "id": "garage_door",
        "name": "Garage Door Lock",
        "aliases": ["garage door", "garage door lock", "garage lock"],
        "type": "lock",
        "room": "Garage",
        "locked": True,
        "battery": 96
    }
}

class SmartHomeController:
    def __init__(self, filepath: str = DEVICES_FILE):
        self.filepath = filepath
        self.devices: Dict[str, Dict[str, Any]] = {}
        self.load_devices()

    def load_devices(self):
        """Loads IoT device states from disk or initializes defaults."""
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    self.devices = json.load(f)
                return
            except Exception:
                pass
        self.devices = DEFAULT_DEVICES.copy()
        self.save_devices()

    def save_devices(self):
        """Persists current state to JSON."""
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(self.devices, f, indent=4)
        except Exception as e:
            print(f"[SmartHome] Error saving devices: {e}")

    def _match_device(self, query: str) -> Optional[Dict[str, Any]]:
        """Matches a device by name or alias from the user's speech."""
        query_clean = query.lower()
        # Direct exact or alias match
        for dev in self.devices.values():
            if dev["name"].lower() in query_clean:
                return dev
            for alias in dev.get("aliases", []):
                if alias in query_clean:
                    return dev
                    
        # Token overlap matching
        for dev in self.devices.values():
            dev_tokens = set(dev["name"].lower().split())
            query_tokens = set(re.findall(r'\b\w+\b', query_clean))
            if dev_tokens.issubset(query_tokens):
                return dev
                
        return None

    def _match_all_devices_of_type(self, dev_type: str) -> list:
        return [d for d in self.devices.values() if d.get("type") == dev_type]

    def handle_command(self, query: str) -> Tuple[bool, str]:
        """
        Parses smart home voice requests and executes corresponding IoT state changes.
        Returns: (handled: bool, response_speech: str)
        """
        q = query.lower().strip()
        
        # 1. Global / Blanket commands: "Turn on/off all lights", "Lock all doors"
        if re.search(r'\b(turn on|switch on|power on)\b.*\b(all lights|every light|all the lights)\b', q):
            lights = self._match_all_devices_of_type("light")
            for l in lights:
                l["power"] = "on"
            self.save_devices()
            return True, f"All {len(lights)} lights powered on, Boss."

        if re.search(r'\b(turn off|switch off|power off)\b.*\b(all lights|every light|all the lights)\b', q):
            lights = self._match_all_devices_of_type("light")
            for l in lights:
                l["power"] = "off"
            self.save_devices()
            return True, f"All {len(lights)} lights switched off, Boss."

        if re.search(r'\b(lock|secure)\b.*\b(all doors|all locks|every door)\b', q):
            locks = self._match_all_devices_of_type("lock")
            for l in locks:
                l["locked"] = True
            self.save_devices()
            return True, f"All {len(locks)} perimeter locks secured, Boss."

        # 2. General Smart Home Status / List Devices
        if any(phrase in q for phrase in [
            "smart home status", "device status", "home status", "iot status",
            "list smart devices", "list devices", "check my devices", "check smart home"
        ]):
            summary = self.get_summary()
            return True, f"Smart home telemetry: {summary}"

        # 3. Thermostat queries & controls
        # "Set thermostat to 22 degrees", "Set temperature to 20"
        temp_match = re.search(r'\b(?:set|adjust|change)\b.*?\b(?:thermostat|temperature|temp|ac)\b.*?\b(?:to\s+)?(\d{1,2})\b', q) or \
                     re.search(r'\b(?:set|make)\b.*?\b(?:the\s+)?(?:thermostat|ac)\b.*?\b(\d{1,2})\b', q)
        if temp_match:
            target_deg = int(temp_match.group(1))
            dev = self._match_device(q)
            if not dev or dev.get("type") != "thermostat":
                dev = self.devices["thermostat"]
            dev["target_temperature"] = target_deg
            self.save_devices()
            return True, f"{dev['name']} set to {target_deg} degrees Celsius, Boss."

        if "what is the temperature" in q or "current temperature" in q or "thermostat status" in q:
            t = self.devices.get("thermostat", {})
            target = t.get("target_temperature", 22)
            current = t.get("current_temperature", 24)
            return True, f"Main thermostat is reading {current} degrees Celsius, holding target at {target} degrees, Boss."

        # 4. Brightness / Dimming
        # "Set living room lights to 50 percent", "Dim living room lights to 30"
        bright_match = re.search(r'\b(?:set|adjust|dim|brighten)\b.*?\b(?:brightness|light|lights)\b.*?\b(?:to\s+)?(\d{1,3})\b', q) or \
                       re.search(r'\b(?:dim|brighten)\b.*?\bto\s+(\d{1,3})\b', q)
        if bright_match:
            level = max(0, min(100, int(bright_match.group(1))))
            dev = self._match_device(q)
            if not dev or dev.get("type") != "light":
                dev = self.devices["living_room_lights"]
            dev["brightness"] = level
            dev["power"] = "on" if level > 0 else "off"
            self.save_devices()
            return True, f"{dev['name']} brightness adjusted to {level} percent, Boss."

        # 5. Lock / Unlock
        # "Lock the front door", "Unlock the garage door"
        if re.search(r'\b(lock|secure)\b', q) and not re.search(r'\b(unlock)\b', q):
            dev = self._match_device(q)
            if dev and dev.get("type") == "lock":
                dev["locked"] = True
                self.save_devices()
                return True, f"{dev['name']} engaged and confirmed locked, Boss."

        if re.search(r'\b(unlock|open)\b', q) and any(word in q for word in ["door", "lock", "garage", "entrance"]):
            dev = self._match_device(q)
            if dev and dev.get("type") == "lock":
                dev["locked"] = False
                self.save_devices()
                return True, f"Warning: {dev['name']} has been unlocked per your authorization, Boss."

        # 6. Turn On / Turn Off (Lights & Plugs)
        # "Turn on the living room lights", "Switch on the coffee maker"
        is_turn_on = bool(re.search(r'\b(turn on|switch on|power on|activate|start)\b', q))
        is_turn_off = bool(re.search(r'\b(turn off|switch off|power off|deactivate|shut off)\b', q))

        if is_turn_on or is_turn_off:
            dev = self._match_device(q)
            if dev:
                new_state = "on" if is_turn_on else "off"
                dev["power"] = new_state
                if dev.get("type") == "plug":
                    dev["wattage"] = dev.get("active_wattage", 100) if is_turn_on else 0
                self.save_devices()
                verb = "powered on" if is_turn_on else "switched off"
                return True, f"{dev['name']} {verb}, Boss."

        # 7. Device query / specific check: "Is the front door locked?", "Is living room light on?"
        if any(phrase in q for phrase in ["is the", "is my", "status of", "check the"]):
            dev = self._match_device(q)
            if dev:
                if dev.get("type") == "lock":
                    status_text = "locked and secure" if dev.get("locked") else "UNLOCKED"
                    return True, f"{dev['name']} is currently {status_text}, Boss."
                elif dev.get("type") in ["light", "plug"]:
                    p = dev.get("power", "off")
                    extra = f" at {dev.get('brightness')}%" if dev.get("type") == "light" and p == "on" else ""
                    return True, f"{dev['name']} is {p}{extra}, Boss."
                elif dev.get("type") == "thermostat":
                    return True, f"{dev['name']} is set to {dev.get('target_temperature')} degrees in {dev.get('mode')} mode, Boss."

        return False, ""

    def get_summary(self) -> str:
        """Returns a concise tactical summary of all IoT nodes."""
        total = len(self.devices)
        lights_on = sum(1 for d in self.devices.values() if d.get("type") == "light" and d.get("power") == "on")
        plugs_on = sum(1 for d in self.devices.values() if d.get("type") == "plug" and d.get("power") == "on")
        unlocked = sum(1 for d in self.devices.values() if d.get("type") == "lock" and not d.get("locked"))
        thermostat = self.devices.get("thermostat", {})
        temp = thermostat.get("target_temperature", 22)

        sec_status = "Perimeter fully locked" if unlocked == 0 else f"ALERT: {unlocked} doors unlocked"
        return f"{total} nodes active. {lights_on} lights on, {plugs_on} plugs drawing power. Thermostat calibrated at {temp}°C. {sec_status}, Boss."

# Singleton controller instance for easy import
smart_home_controller = SmartHomeController()
