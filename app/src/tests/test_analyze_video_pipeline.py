"""
Tests for analyze_video_pipeline.py
"""
import pytest
from unittest.mock import patch, MagicMock, mock_open
from pathlib import Path
import sys
import os

# Ensure the module can be imported
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analyze_video_pipeline import run_pipeline, encode_image

@pytest.fixture
def mock_supabase():
    mock_sb = MagicMock()
    
    # Custom side effect function that creates separate fresh Mocks for every database table operation!
    def table_mock(table_name):
        tbl = MagicMock()
        if table_name == "missions":
            # For .insert().execute()
            tbl.insert.return_value.execute.return_value.data = [{"id": "miss-123"}]
            # For .update().eq().execute()
            tbl.update.return_value.eq.return_value.execute.return_value.data = []
        elif table_name == "mission_images":
            tbl.insert.return_value.execute.return_value.data = [{"id": "img-456"}]
        elif table_name == "damage_detections":
            tbl.insert.return_value.execute.return_value.data = [{"id": "det-789"}]
        return tbl
        
    mock_sb.table = MagicMock(side_effect=table_mock)
    
    # Mock storage
    mock_sb.storage.from_.return_value.upload.return_value = None
    mock_sb.storage.from_.return_value.get_public_url.return_value = "http://mock-url"
    
    return mock_sb

@patch("analyze_video_pipeline.extract_frames")
@patch("analyze_video_pipeline.encode_image")
@patch("analyze_video_pipeline.upload_image_to_supabase")
def test_successful_pipeline_run(mock_upload, mock_encode, mock_extract, mock_supabase):
    # Setup mocks
    mock_extract.return_value = [Path("frame_0.jpg"), Path("frame_1.jpg")]
    mock_encode.return_value = "mock_b64"
    mock_upload.return_value = "http://mock/public"
    
    mock_response = MagicMock()
    mock_response.data = {
        "report": {
            "boxes": [
                {"bbox_xyxy": [10, 10, 20, 20], "severity": "high", "confidence": 0.9, "class": "crack"}
            ]
        }
    }
    # Mocking standard edge function logic
    mock_supabase.functions.invoke.return_value = mock_response

    # Execute
    run_pipeline(
        video_path=Path("dummy.mp4"),
        mission_name="Test Mission",
        speed_mps=5.0,
        altitude_m=10.0,
        fov=82.6,
        max_frames=2,
        api_url="http://mock-vast",
        api_key="mock-key",
        supabase=mock_supabase
    )

    # Asserts
    mock_supabase.table.assert_any_call("missions")
    mock_extract.assert_called_once()
    assert mock_supabase.functions.invoke.call_count == 2
    

@patch("analyze_video_pipeline.extract_frames")
def test_pipeline_rollback_on_extract_fail(mock_extract, mock_supabase):
    mock_extract.side_effect = Exception("FFmpeg failure mock")
    
    with pytest.raises(Exception):
         run_pipeline(
            video_path=Path("dummy.mp4"),
            mission_name="Test Mission",
            supabase=mock_supabase,
            max_frames=None
         )

@patch("analyze_video_pipeline.extract_frames")
@patch("analyze_video_pipeline.analyze_frame_vast")
@patch("analyze_video_pipeline.encode_image")
def test_pipeline_skip_faulty_frame(mock_encode, mock_analyze, mock_extract, mock_supabase):
    """If one frame fails vast analysis, the pipeline should log error and continue."""
    mock_extract.return_value = [Path("frame_0.jpg"), Path("frame_1.jpg")]
    mock_encode.return_value = "mock_b64"
    
    # First fails, second succeeds
    mock_analyze.side_effect = [Exception("Timeout"), {"boxes": []}]

    run_pipeline(
        video_path=Path("dummy.mp4"),
        mission_name="Test Skip",
        supabase=mock_supabase,
        max_frames=None
    )
