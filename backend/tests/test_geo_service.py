import sys
import os
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from backend.database import init_db, get_db
from backend.services.geo_service import (
    resolve_timezone,
    reverse_geocode_location,
    format_locality_hierarchy,
    is_valid_iana_timezone
)

class TestGeoService(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        self.conn = get_db()
        self.cursor = self.conn.cursor()

    def tearDown(self):
        self.conn.close()

    def test_01_coordinate_timezone_lookup(self):
        """Verify that coordinate-based timezone lookup resolves correct IANA zones."""
        # Hyderabad, Telangana, India
        tz_hyd = resolve_timezone(17.3850, 78.4867)
        self.assertEqual(tz_hyd, "Asia/Kolkata")

        # New York, USA
        tz_ny = resolve_timezone(40.7128, -74.0060)
        self.assertEqual(tz_ny, "America/New_York")

        # London, UK
        tz_ldn = resolve_timezone(51.5074, -0.1278)
        self.assertEqual(tz_ldn, "Europe/London")

        # Tokyo, Japan
        tz_tko = resolve_timezone(35.6762, 139.6503)
        self.assertEqual(tz_tko, "Asia/Tokyo")

        # Sydney, Australia
        tz_syd = resolve_timezone(-33.8688, 151.2093)
        self.assertEqual(tz_syd, "Australia/Sydney")

    def test_02_locality_hierarchy_formatting(self):
        """Verify formatting of village, mandal, district, and state into clean hierarchy."""
        formatted = format_locality_hierarchy(
            village_locality="Sultan Bazar",
            mandal_taluk="Nampally mandal",
            district="Hyderabad",
            state="Telangana"
        )
        self.assertEqual(formatted, "Sultan Bazar, Nampally mandal, Hyderabad, Telangana")

        # Test partial hierarchy (some levels missing)
        partial = format_locality_hierarchy(
            village_locality="",
            mandal_taluk="Nampally mandal",
            district="Hyderabad",
            state="Telangana"
        )
        self.assertEqual(partial, "Nampally mandal, Hyderabad, Telangana")

    def test_03_offline_and_fallback_resilience(self):
        """Verify that invalid coordinates or lookup timeouts fail gracefully without crashes."""
        # Invalid coordinates
        res = reverse_geocode_location(lat=999.0, lon=999.0)
        self.assertIsInstance(res, dict)
        self.assertIn("village_locality", res)
        self.assertIn("mandal_taluk", res)
        self.assertIn("district", res)
        self.assertIn("state", res)

        # Fallback timezone for invalid coordinates
        tz_invalid = resolve_timezone(999.0, 999.0)
        self.assertIn(tz_invalid, ["UTC", "Asia/Kolkata"])

    def test_04_iana_daylight_saving_handling(self):
        """
        Verify that IANA timezones handle daylight saving transitions naturally
        rather than relying on a fixed UTC offset.
        """
        # America/New_York has EDT (UTC-4) in Summer and EST (UTC-5) in Winter
        summer_dt = datetime(2026, 7, 1, 12, 0, tzinfo=ZoneInfo("America/New_York"))
        winter_dt = datetime(2026, 1, 1, 12, 0, tzinfo=ZoneInfo("America/New_York"))

        # In July (summer), offset is -4 hours (-14400s)
        self.assertEqual(summer_dt.utcoffset().total_seconds(), -14400)

        # In January (winter), offset is -5 hours (-18000s)
        self.assertEqual(winter_dt.utcoffset().total_seconds(), -18000)

        # Europe/London has BST (UTC+1) in Summer and GMT (UTC+0) in Winter
        london_summer = datetime(2026, 7, 1, 12, 0, tzinfo=ZoneInfo("Europe/London"))
        london_winter = datetime(2026, 1, 1, 12, 0, tzinfo=ZoneInfo("Europe/London"))
        self.assertEqual(london_summer.utcoffset().total_seconds(), 3600)
        self.assertEqual(london_winter.utcoffset().total_seconds(), 0)

    def test_05_farm_coordinate_change_and_manual_correction(self):
        """
        Verify:
        1. Changing farm coordinates recalculates timezone.
        2. Operator manual timezone correction overrides automatic lookup.
        """
        from backend.app import create_app
        app = create_app()
        client = app.test_client()

        # Create test farm in Hyderabad (17.3850, 78.4867)
        resp = client.post("/api/farms", json={
            "name": "Geo Test Farm",
            "lat": 17.3850,
            "lon": 78.4867,
            "crop": "Cotton",
            "area": 2.0
        })
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()
        farm_id = data["farm_id"]
        self.assertEqual(data["timezone"], "Asia/Kolkata")

        # Update coordinates to London, UK (51.5074, -0.1278) -> Timezone should recalculate
        update_resp = client.put(f"/api/farms/{farm_id}", json={
            "lat": 51.5074,
            "lon": -0.1278
        })
        self.assertEqual(update_resp.status_code, 200)
        update_data = update_resp.get_json()
        self.assertEqual(update_data["timezone"], "Europe/London")

        # Operator manual correction: explicitly set timezone to America/Chicago
        manual_resp = client.put(f"/api/farms/{farm_id}", json={
            "timezone": "America/Chicago"
        })
        self.assertEqual(manual_resp.status_code, 200)
        manual_data = manual_resp.get_json()
        self.assertEqual(manual_data["timezone"], "America/Chicago")

        # Verify persisted state via GET
        get_resp = client.get(f"/api/farms/{farm_id}")
        get_data = get_resp.get_json()
        self.assertEqual(get_data["timezone"], "America/Chicago")

        # Clean up
        self.cursor.execute("DELETE FROM farms WHERE id = ?", (farm_id,))
        self.cursor.execute("DELETE FROM devices WHERE farm_id = ?", (farm_id,))
        self.conn.commit()

if __name__ == "__main__":
    unittest.main()
