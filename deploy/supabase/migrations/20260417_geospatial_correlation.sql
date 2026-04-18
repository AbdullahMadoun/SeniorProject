-- 1. Enable PostGIS
CREATE EXTENSION IF NOT EXISTS postgis;

-- 2. Create mission tracking tables
CREATE TABLE IF NOT EXISTS public.missions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    description TEXT,
    started_at TIMESTAMPTZ DEFAULT now(),
    ended_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS public.mission_images (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mission_id UUID REFERENCES public.missions(id) ON DELETE CASCADE,
    image_name TEXT,
    processed_image_path TEXT,
    processing_seconds FLOAT,
    timestamp_utc TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS public.damage_detections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    image_id UUID REFERENCES public.mission_images(id) ON DELETE CASCADE,
    severity TEXT,
    confidence FLOAT,
    damage_type TEXT,
    bounding_box JSONB
);

CREATE TABLE IF NOT EXISTS public.flight_telemetry (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mission_id UUID REFERENCES public.missions(id) ON DELETE CASCADE,
    timestamp_utc TIMESTAMPTZ NOT NULL,
    lat FLOAT NOT NULL,
    lon FLOAT NOT NULL,
    alt FLOAT,
    battery_percent FLOAT,
    geom GEOMETRY(Point, 4326)
);

-- 3. Geographic Trigger: Automatically update geom on insert/update
CREATE OR REPLACE FUNCTION update_telemetry_geom() RETURNS TRIGGER AS $$
BEGIN
    NEW.geom := ST_SetSRID(ST_MakePoint(NEW.lon, NEW.lat), 4326);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_update_telemetry_geom
BEFORE INSERT OR UPDATE ON public.flight_telemetry
FOR EACH ROW EXECUTE FUNCTION update_telemetry_geom();

-- 4. Geospatial Correlation View: Link detections to the closest telemetry ping
CREATE OR REPLACE VIEW view_correlated_damage_locations AS
WITH RankedTelemetry AS (
    SELECT 
        mi.id as image_id,
        dd.id as detection_id,
        mi.mission_id,
        dd.severity,
        dd.confidence,
        dd.damage_type,
        mi.processed_image_path,
        mi.timestamp_utc as capture_time,
        ft.lat,
        ft.lon,
        ft.geom,
        ABS(EXTRACT(EPOCH FROM (mi.timestamp_utc - ft.timestamp_utc))) as time_diff,
        ROW_NUMBER() OVER (
            PARTITION BY dd.id 
            ORDER BY ABS(EXTRACT(EPOCH FROM (mi.timestamp_utc - ft.timestamp_utc))) ASC
        ) as rank
    FROM mission_images mi
    JOIN damage_detections dd ON dd.image_id = mi.id
    LEFT JOIN flight_telemetry ft ON ft.mission_id = mi.mission_id
)
SELECT 
    detection_id,
    image_id,
    mission_id,
    severity,
    confidence,
    damage_type,
    processed_image_path,
    capture_time,
    lat,
    lon,
    geom,
    time_diff
FROM RankedTelemetry
WHERE rank = 1;

-- 5. Event & System Logging Lifecycle
CREATE TABLE IF NOT EXISTS public.hardware_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id TEXT,
    event_type TEXT NOT NULL,
    payload JSONB,
    severity TEXT DEFAULT 'info',
    timestamp_utc TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.system_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    service TEXT DEFAULT 'backend',
    module TEXT,
    level TEXT DEFAULT 'INFO',
    message TEXT,
    traceback TEXT,
    timestamp_utc TIMESTAMPTZ DEFAULT now()
);

-- Indexing for performance
CREATE INDEX IF NOT EXISTS idx_telemetry_mission ON public.flight_telemetry(mission_id, timestamp_utc);
CREATE INDEX IF NOT EXISTS idx_detections_image ON public.damage_detections(image_id);
CREATE INDEX IF NOT EXISTS idx_hardware_event_type ON public.hardware_events(event_type, timestamp_utc);

