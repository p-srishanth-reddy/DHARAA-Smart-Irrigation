import requests
import time

CACHE_TTL_SECONDS = 1800  # 30 minutes
_weather_cache = {}

def get_weather_forecast(lat: float, lon: float):
    """
    Fetch current and hourly weather from Open-Meteo for given coordinates.
    Caches responses to prevent rate limiting and tracks retrieval timestamp.
    """
    cache_key = f"{round(lat, 4)},{round(lon, 4)}"
    current_time = time.time()

    if cache_key in _weather_cache:
        cached_entry = _weather_cache[cache_key]
        cache_age = current_time - cached_entry["retrieved_at"]
        if cache_age < CACHE_TTL_SECONDS:
            data = cached_entry["data"]
            data["is_stale"] = False
            data["cache_age_seconds"] = round(cache_age)
            return data

    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        f"&current=temperature_2m,relative_humidity_2m,precipitation,rain,weather_code,wind_speed_10m"
        f"&hourly=temperature_2m,relative_humidity_2m,precipitation_probability,precipitation"
        f"&forecast_days=3"
        f"&timezone=auto"
    )

    try:
        response = requests.get(url, timeout=8)
        response.raise_for_status()
        api_data = response.json()

        forecast_payload = {
            "latitude": lat,
            "longitude": lon,
            "retrieved_at": current_time,
            "retrieved_at_iso": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(current_time)),
            "is_stale": False,
            "cache_age_seconds": 0,
            "current": {
                "temperature": api_data.get("current", {}).get("temperature_2m"),
                "humidity": api_data.get("current", {}).get("relative_humidity_2m"),
                "precipitation": api_data.get("current", {}).get("precipitation", 0.0),
                "rain": api_data.get("current", {}).get("rain", 0.0),
                "weather_code": api_data.get("current", {}).get("weather_code", 0),
                "wind_speed": api_data.get("current", {}).get("wind_speed_10m", 0.0)
            },
            "hourly": {
                "time": api_data.get("hourly", {}).get("time", [])[:24],
                "precipitation_probability": api_data.get("hourly", {}).get("precipitation_probability", [])[:24],
                "precipitation": api_data.get("hourly", {}).get("precipitation", [])[:24],
                "temperature": api_data.get("hourly", {}).get("temperature_2m", [])[:24],
            }
        }

        _weather_cache[cache_key] = {
            "retrieved_at": current_time,
            "data": forecast_payload
        }
        return forecast_payload

    except Exception as e:
        # If network error occurs but we have an older cached item, return it marked as stale
        if cache_key in _weather_cache:
            stale_entry = _weather_cache[cache_key]
            data = stale_entry["data"]
            data["is_stale"] = True
            data["cache_age_seconds"] = round(current_time - stale_entry["retrieved_at"])
            data["warning"] = f"Using cached forecast due to network error: {str(e)}"
            return data
        
        # Return fallback mock structure if no cache exists
        return {
            "latitude": lat,
            "longitude": lon,
            "retrieved_at": current_time,
            "retrieved_at_iso": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(current_time)),
            "is_stale": True,
            "cache_age_seconds": 0,
            "warning": f"Live weather API unreachable ({str(e)}). Providing fallback estimates.",
            "current": {
                "temperature": 28.5,
                "humidity": 62.0,
                "precipitation": 0.0,
                "rain": 0.0,
                "weather_code": 1,
                "wind_speed": 4.2
            },
            "hourly": {
                "time": [f"{i:02d}:00" for i in range(24)],
                "precipitation_probability": [5, 5, 10, 10, 15, 20, 25, 20, 15, 10, 5, 0, 0, 0, 5, 10, 10, 5, 5, 5, 5, 5, 5, 5],
                "precipitation": [0.0]*24,
                "temperature": [24 + (i % 6) for i in range(24)]
            }
        }
