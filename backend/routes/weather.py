from flask import Blueprint, request, jsonify
from backend.database import get_db
from backend.services.weather_service import get_weather_forecast

weather_bp = Blueprint("weather", __name__)

@weather_bp.route("/api/weather", methods=["GET"])
def get_weather():
    farm_id = request.args.get("farm_id", type=int)
    lat = request.args.get("lat", type=float)
    lon = request.args.get("lon", type=float)

    if farm_id and (lat is None or lon is None):
        conn = get_db()
        cursor = conn.cursor()
        farm = cursor.execute("SELECT lat, lon, name, state_district FROM farms WHERE id = ?", (farm_id,)).fetchone()
        conn.close()
        if farm and farm["lat"] is not None and farm["lon"] is not None:
            lat = farm["lat"]
            lon = farm["lon"]
        else:
            lat = 17.3850
            lon = 78.4867

    if lat is None or lon is None:
        lat = 17.3850
        lon = 78.4867

    forecast = get_weather_forecast(lat, lon)
    return jsonify(forecast)
