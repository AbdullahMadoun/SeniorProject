import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if SUPABASE_URL and SUPABASE_KEY:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
else:
    supabase = None

def save_analysis_to_supabase(
    mission_name: str,
    image_name: str,
    image_bytes: bytes,
    boxes: list[dict],
    gps_lat: float,
    gps_lon: float,
    timestamp_utc: str
):
    """
    Example function inserting a new mission (if it doesn't exist), 
    uploading the raw image to Supabase Storage, and persisting
    the mission_images and damage_detections DB records.
    """
    if not supabase:
        print("Supabase client not configured.")
        return
        
    # 1. Fetch or create a mission
    mission_resp = supabase.table("missions") \
        .select("id") \
        .eq("name", mission_name) \
        .execute()
        
    if mission_resp.data:
        mission_id = mission_resp.data[0]["id"]
    else:
        new_mission = supabase.table("missions") \
            .insert({"name": mission_name, "status": "analyzing"}) \
            .execute()
        mission_id = new_mission.data[0]["id"]

    # 2. Upload image to Storage Bucket
    # Ensure a unique file name in storage
    storage_path = f"{mission_id}/{image_name}"
    
    # Upload (Using content type for JPEG)
    supabase.storage.from_("skylink_images") \
        .upload(storage_path, image_bytes, {"content-type": "image/jpeg"})
        
    # Get public URL
    public_url = supabase.storage.from_("skylink_images").get_public_url(storage_path)

    # 3. Create the mission_images record
    image_record = {
        "mission_id": mission_id,
        "image_name": image_name,
        "processed_image_path": public_url,  # or raw_image_path if this is the raw image
        "gps_lat": gps_lat,
        "gps_lon": gps_lon,
        "timestamp_utc": timestamp_utc
    }
    img_resp = supabase.table("mission_images").insert(image_record).execute()
    image_id = img_resp.data[0]["id"]
    
    # 4. Insert each detection/damage found
    detections_to_insert = []
    for box in boxes:
        severity = box.get("severity", "Low Severity")
        confidence = box.get("confidence", 0.0)
        bounding_box = box.get("box", [])  # [x1, y1, x2, y2]
        damage_type = "crack" # Or however you determine damage type
        
        detections_to_insert.append({
            "image_id": image_id,
            "severity": severity,
            "confidence": confidence,
            "bounding_box": bounding_box,
            "damage_type": damage_type
        })
        
    if detections_to_insert:
        supabase.table("damage_detections").insert(detections_to_insert).execute()
        
    print(f"Successfully saved {len(detections_to_insert)} detections to Supabase!")

if __name__ == "__main__":
    # Dummy run
    with open("app/src/static/skylink_logo.png", "rb") as f:
        dummy_bytes = f.read()

    save_analysis_to_supabase(
        mission_name="Test Mission A",
        image_name="test_img_01.jpg",
        image_bytes=dummy_bytes,
        boxes=[{"severity": "High Severity", "confidence": 0.95, "box": [10, 10, 50, 50]}],
        gps_lat=26.3073,
        gps_lon=50.1456,
        timestamp_utc="2026-04-17T12:00:00Z"
    )
