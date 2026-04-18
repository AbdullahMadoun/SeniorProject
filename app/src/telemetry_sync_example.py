import os
import time
from datetime import datetime
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if SUPABASE_URL and SUPABASE_KEY:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
else:
    supabase = None

def simulate_companion_node_loop(mission_id: str):
    """
    This represents the real-time node onboard the drone.
    It has two parallel jobs:
    1. Stream Telemetry to Supabase
    2. Stream Captured Image logic to Supabase
    """
    if not supabase:
        print("Missing SUPABASE config.")
        return

    # Simulate 1: Pushing a hardware heartbeat
    supabase.table("hardware_devices").upsert({
        "device_id": "PX4-FlightController",
        "device_type": "flight_controller",
        "status": "healthy",
        "last_seen": datetime.utcnow().isoformat()
    }).execute()
    
    supabase.table("hardware_events").insert({
        "device_id": "PX4-FlightController",
        "event_type": "HEALTH_CHANGED"
    }).execute()

    print(f"Hardware node checked in for mission {mission_id}.")

    # Simulate 2: High frequency telemetry stream (e.g. 5hz)
    # The drone flies and logs GPS.
    telemetry_payload = []
    base_time = time.time()
    for i in range(5):
        t_time = datetime.utcfromtimestamp(base_time + i).isoformat()
        telemetry_payload.append({
            "mission_id": mission_id,
            "timestamp_utc": t_time,
            "lat": 26.3073 + (i * 0.0001), 
            "lon": 50.1456 + (i * 0.0001),
            "alt": 15.0,
            "battery_percent": 98.0 - (i * 0.1)
        })
    
    supabase.table("flight_telemetry").insert(telemetry_payload).execute()
    print("Streamed 5 frames of Telemetry to DB.")

    # Simulate 3: A camera trigger happens WITHOUT GPS!
    # Just the image bytes and the time it was captured.
    capture_time = datetime.utcfromtimestamp(base_time + 2.4).isoformat() # Right between ping 2 and 3
    
    # Upload to storage... (mocking this out to save space)
    image_name = "frame_908.jpg"
    public_url = f"https://mockbase/storage/v1/object/public/skylink_images/{mission_id}/{image_name}"
    
    # Notice: NO LAT/LON IS INSERTED HERE!
    image_resp = supabase.table("mission_images").insert({
        "mission_id": mission_id,
        "image_name": image_name,
        "processed_image_path": public_url,
        "timestamp_utc": capture_time
    }).execute()
    
    image_id = image_resp.data[0]["id"]
    
    # 4. Insert the edge intelligence bounding box
    supabase.table("damage_detections").insert({
        "image_id": image_id,
        "severity": "High Severity",
        "confidence": 0.88,
        "bounding_box": [10, 20, 100, 200]
    }).execute()
    
    print("Logged Image + Damage geometry.")
    
    print("---")
    print("Now open Supabase and query `view_correlated_damage_locations`.")
    print("You will see that the database automatically found the telemetry ping from `base_time + 2`")
    print("and assigned that GPS coordinate to the damage location. Magic!")

if __name__ == "__main__":
    # Create a mock mission first
    if supabase:
        mission_resp = supabase.table("missions").insert({"name": "Live SITL Test Loop"}).execute()
        m_id = mission_resp.data[0]["id"]
        simulate_companion_node_loop(m_id)
