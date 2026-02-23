CREATE TABLE IF NOT EXISTS public.detections (
    id BIGSERIAL PRIMARY KEY,
    image_name TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    image_url TEXT,
    detection_count INTEGER NOT NULL,
    max_confidence DOUBLE PRECISION NOT NULL,
    severity TEXT NOT NULL,
    gps_lat DOUBLE PRECISION,
    gps_lon DOUBLE PRECISION,
    localization_m DOUBLE PRECISION,
    localization_target_met BOOLEAN,
    estimated_accuracy DOUBLE PRECISION,
    accuracy_target_met BOOLEAN,
    processing_seconds DOUBLE PRECISION,
    timestamp_utc TIMESTAMPTZ NOT NULL,
    boxes JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_detections_timestamp_utc ON public.detections (timestamp_utc DESC);
CREATE INDEX IF NOT EXISTS idx_detections_severity ON public.detections (severity);
