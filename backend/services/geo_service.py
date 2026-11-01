import logging
import requests
from zoneinfo import ZoneInfo
from timezonefinder import TimezoneFinder

logger = logging.getLogger("dharaa.geo")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(asctime)s] [GEO] %(levelname)s: %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

# Singleton TimezoneFinder instance for fast in-memory reuse
_tz_finder = None

def get_timezone_finder() -> TimezoneFinder:
    global _tz_finder
    if _tz_finder is None:
        _tz_finder = TimezoneFinder()
    return _tz_finder

def is_valid_iana_timezone(tz_name: str) -> bool:
    """Verifies whether a given string is a valid, recognized IANA timezone."""
    if not tz_name or not isinstance(tz_name, str):
        return False
    try:
        ZoneInfo(tz_name.strip())
        return True
    except Exception:
        return False

def resolve_timezone(lat: float, lon: float) -> str:
    """
    Finds the nearest valid IANA time zone for given latitude and longitude
    using the maintained geographic dataset (timezonefinder).
    
    Guarantees returning a valid IANA timezone string that works with
    Python's zoneinfo for native daylight saving transitions.
    """
    try:
        lat = float(lat)
        lon = float(lon)
    except (ValueError, TypeError):
        return "Asia/Kolkata"

    try:
        tf = get_timezone_finder()
        tz_str = tf.timezone_at(lat=lat, lng=lon)
        if not tz_str:
            # Fallback to closest timezone if slightly offshore or near boundary
            tz_str = tf.closest_timezone_at(lat=lat, lng=lon)

        if tz_str and is_valid_iana_timezone(tz_str):
            return tz_str
    except Exception as e:
        logger.warning(f"Error querying timezone for ({lat}, {lon}): {e}")

    # Fallback heuristic for Indian subcontinent
    if 6.0 <= lat <= 38.0 and 68.0 <= lon <= 98.0:
        return "Asia/Kolkata"

    return "UTC"

def reverse_geocode_location(lat: float, lon: float, timeout_seconds: float = 3.5) -> dict:
    """
    Looks up place details from coordinates to extract the locality hierarchy:
    - village/locality
    - mandal or taluk (subdistrict)
    - district
    - state
    
    If network is unavailable or fields are absent, returns available details
    gracefully without throwing unhandled exceptions, so user can edit them manually.
    """
    result = {
        "village_locality": "",
        "mandal_taluk": "",
        "district": "",
        "state": "",
        "country": "",
        "formatted_address": "",
        "lookup_success": False
    }

    try:
        lat = float(lat)
        lon = float(lon)
    except (ValueError, TypeError):
        return result

    headers = {
        "User-Agent": "DHARAA-Smart-Irrigation/1.0 (https://github.com/p-srishanth-reddy/DHARAA-Smart-Irrigation; contact@dharaa.org)"
    }
    url = f"https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat={lat}&lon={lon}&addressdetails=1"

    try:
        resp = requests.get(url, headers=headers, timeout=timeout_seconds)
        if resp.status_code == 200:
            data = resp.json() or {}
            addr = data.get("address", {})

            # 1. Village / Locality level
            village = (
                addr.get("village") or
                addr.get("hamlet") or
                addr.get("neighbourhood") or
                addr.get("suburb") or
                addr.get("residential") or
                addr.get("locality") or
                addr.get("city_district") or
                addr.get("town") or
                addr.get("road") or
                ""
            )

            # 2. Mandal / Taluk (Subdistrict) level
            mandal = (
                addr.get("subdistrict") or
                addr.get("county") or
                addr.get("taluk") or
                addr.get("mandal") or
                addr.get("tehsil") or
                addr.get("municipality") or
                ""
            )

            # 3. District level
            district = (
                addr.get("state_district") or
                addr.get("district") or
                addr.get("city") or
                ""
            )

            # 4. State level
            state = (
                addr.get("state") or
                addr.get("province") or
                addr.get("region") or
                ""
            )

            country = addr.get("country") or ""

            formatted = format_locality_hierarchy(village, mandal, district, state)

            result.update({
                "village_locality": village.strip(),
                "mandal_taluk": mandal.strip(),
                "district": district.strip(),
                "state": state.strip(),
                "country": country.strip(),
                "formatted_address": formatted,
                "lookup_success": True
            })
            return result
    except Exception as e:
        logger.warning(f"Reverse geocode lookup failed for ({lat}, {lon}): {e}. Local editing available.")

    return result

def format_locality_hierarchy(village_locality: str, mandal_taluk: str, district: str, state: str) -> str:
    """Formats available location levels into a clear geographic hierarchy string."""
    parts = []
    seen = set()
    for item in [village_locality, mandal_taluk, district, state]:
        if item and item.strip() and item.strip().lower() not in seen:
            clean = item.strip()
            parts.append(clean)
            seen.add(clean.lower())
    return ", ".join(parts) if parts else "Location not specified"
