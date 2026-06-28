from mcp.server.fastmcp import FastMCP
import json
import os

mcp = FastMCP("Teen Health Tracker")

DATA_FILE = "health_tracker_data.json"

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"health_logs": [], "diet_logs": [], "reminders": []}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

@mcp.tool()
def log_health_condition(day: str, symptoms: str, mood: str, sleep_hours: float) -> str:
    """Logs the user's health condition for a specific day.
    
    Args:
        day: Day of the week (e.g. 'Monday', 'Tuesday')
        symptoms: Description of any physical symptoms (e.g. 'fatigue', 'irregular period')
        mood: The user's mood (e.g. 'stressed', 'happy', 'tired')
        sleep_hours: Number of hours slept
    """
    data = load_data()
    data["health_logs"].append({
        "day": day,
        "symptoms": symptoms,
        "mood": mood,
        "sleep_hours": sleep_hours
    })
    save_data(data)
    return f"Successfully logged health condition for {day}."

@mcp.tool()
def log_diet(day: str, meals: str, water_intake_liters: float) -> str:
    """Logs the user's diet and water intake for a specific day.
    
    Args:
        day: Day of the week (e.g. 'Monday', 'Tuesday')
        meals: Summary of meals eaten (e.g. 'oatmeal, chicken salad, rice and beans')
        water_intake_liters: Water consumption in liters
    """
    data = load_data()
    data["diet_logs"].append({
        "day": day,
        "meals": meals,
        "water_intake_liters": water_intake_liters
    })
    save_data(data)
    return f"Successfully logged diet for {day}."

@mcp.tool()
def get_health_history() -> str:
    """Retrieves all logged health entries to analyze trends."""
    data = load_data()
    return json.dumps(data["health_logs"])

@mcp.tool()
def get_diet_history() -> str:
    """Retrieves all logged diet entries to analyze nutrition trends."""
    data = load_data()
    return json.dumps(data["diet_logs"])

@mcp.tool()
def set_health_reminder(reminder_text: str, frequency: str) -> str:
    """Sets a health-related reminder (e.g. 'drink water every 2 hours', 'go to sleep by 10 PM').
    
    Args:
        reminder_text: What the reminder is for
        frequency: How often or when the reminder triggers (e.g. 'daily', 'every morning')
    """
    data = load_data()
    data["reminders"].append({
        "text": reminder_text,
        "frequency": frequency
    })
    save_data(data)
    return f"Successfully set reminder: '{reminder_text}' ({frequency})."

if __name__ == "__main__":
    mcp.run()
