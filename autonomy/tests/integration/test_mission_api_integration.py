"""
Integration tests for Mission API endpoints.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
import json

class TestMissionAPIIntegration:
    """Integration tests for FastAPI mission endpoints."""
    
    def test_mission_api_app_exists(self):
        """Mission API app can be imported."""
        from autonomy.scripts import mission_api
        assert hasattr(mission_api, 'app')


class TestMissionValidationIntegration:
    """Integration tests for mission validation."""
    
    def test_mission_request_validation(self):
        """MissionPlanRequest should validate waypoints."""
        from autonomy.drone_system.mission_control import MissionPlanRequest, validate_mission_request
        from autonomy.drone_system.models import Waypoint
        from autonomy.drone_system.config import load_system_baseline
        
        baseline = load_system_baseline()
        
        # Valid request
        valid_request = MissionPlanRequest(
            mission_id="test_mission",
            home=baseline.home,
            waypoints=[
                Waypoint(baseline.home.lat + 0.0001, baseline.home.lon + 0.0001, 20.0),
                Waypoint(baseline.home.lat + 0.0002, baseline.home.lon + 0.0002, 20.0),
            ],
            cruise_speed_mps=3.0,
            rtl_after_mission=True,
        )
        
        # Should not raise
        validate_mission_request(valid_request, baseline)
    
    def test_mission_request_rejects_invalid_altitude(self):
        """MissionPlanRequest should reject altitude above max."""
        from autonomy.drone_system.mission_control import MissionPlanRequest, validate_mission_request
        from autonomy.drone_system.models import Waypoint
        from autonomy.drone_system.config import load_system_baseline
        
        baseline = load_system_baseline()
        
        # Invalid request - altitude above max
        invalid_request = MissionPlanRequest(
            mission_id="test_mission",
            home=baseline.home,
            waypoints=[
                Waypoint(baseline.home.lat + 0.0001, baseline.home.lon + 0.0001, 500.0),  # Above 120m max
                Waypoint(baseline.home.lat + 0.0002, baseline.home.lon + 0.0002, 500.0),
            ],
            cruise_speed_mps=3.0,
            rtl_after_mission=True,
        )
        
        with pytest.raises(ValueError, match="altitude"):
            validate_mission_request(invalid_request, baseline)
