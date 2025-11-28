import json
import urllib.request
import os

# ---------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------
USE_LOCAL_FILE = True          # ← set to False to use the URL
LOCAL_FILE = "positions.json"  # local JSON filename
URL = "http://192.168.1.254:8000/positions.json"

MY_TEAM = "3"  # your turret team number
# ---------------------------------------------------


def load_positions():
    """Loads the positions JSON from local file OR URL."""
    
    if USE_LOCAL_FILE:
        if not os.path.exists(LOCAL_FILE):
            print(f"ERROR: Local file '{LOCAL_FILE}' not found!")
            return None

        with open(LOCAL_FILE, "r") as f:
            print(f"Loaded JSON from local file: {LOCAL_FILE}")
            return json.load(f)

    else:
        print(f"Loading JSON from URL: {URL}")
        with urllib.request.urlopen(URL) as response:
            data = response.read().decode("utf-8")
            return json.loads(data)


# Load the JSON data
positions = load_positions()
if positions is None:
    exit()

turrets = positions["turrets"]
globes = positions["globes"]

# ---------------------------------------------------
# Extract your turret and others
# ---------------------------------------------------

my_turret = turrets.get(MY_TEAM)

other_turrets = {
    team: coords for team, coords in turrets.items() if team != MY_TEAM
}

# ---------------------------------------------------
# Printing results
# ---------------------------------------------------

print("\n--- YOUR TURRET (Team 3) ---")
if my_turret:
    print(f"Team {MY_TEAM}: r={my_turret['r']}, theta={my_turret['theta']}")
else:
    print("ERROR: Your team number was not found in the JSON!")

print("\n--- OTHER TEAMS ---")
for team, coords in other_turrets.items():
    print(f"Team {team}: r={coords['r']}, theta={coords['theta']}")

print("\n--- GLOBES ---")
for i, globe in enumerate(globes):
    print(f"Globe {i+1}: r={globe['r']}, theta={globe['theta']}, z={globe['z']}")
