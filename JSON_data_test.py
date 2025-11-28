import json
import urllib.request

URL = "http://192.168.1.254:8000/positions.json"

# YOUR TEAM NUMBER
MY_TEAM = "3"    # turret team 3


def load_positions(url):
    with urllib.request.urlopen(url) as response:
        data = response.read().decode("utf-8")
        return json.loads(data)


# Load JSON data
positions = load_positions(URL)

turrets = positions["turrets"]
globes = positions["globes"]

# -----------------------------
# 1. Extract *your* turret
# -----------------------------
my_turret = turrets.get(MY_TEAM)

# -----------------------------
# 2. Extract other teams' turrets
# -----------------------------
other_turrets = {
    team: coords for team, coords in turrets.items() if team != MY_TEAM
}

# -----------------------------
# 3. Print everything
# -----------------------------

print("\n--- YOUR TURRET (Team 3) ---")
if my_turret:
    print(f"Team {MY_TEAM}: r={my_turret['r']}, theta={my_turret['theta']}")
else:
    print("Team not found in JSON!")

print("\n--- OTHER TEAMS ---")
for team, coords in other_turrets.items():
    print(f"Team {team}: r={coords['r']}, theta={coords['theta']}")

print("\n--- GLOBES ---")
for i, globe in enumerate(globes):
    print(f"Globe {i+1}: r={globe['r']}, theta={globe['theta']}, z={globe['z']}")
    