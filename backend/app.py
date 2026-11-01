import os
from flask import Flask, send_from_directory, jsonify
from flask_cors import CORS

from backend.database import init_db
from backend.routes.auth import auth_bp
from backend.routes.telemetry import telemetry_bp
from backend.routes.farms import farms_bp
from backend.routes.schedules import schedules_bp
from backend.routes.irrigation import irrigation_bp
from backend.routes.weather import weather_bp
from backend.routes.advisor import advisor_bp
from backend.routes.analytics import analytics_bp
from backend.routes.notifications import notifications_bp

FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))

def create_app():
    app = Flask(__name__, static_folder=FRONTEND_DIR)
    CORS(app)

    # Initialize Database Schema & Seed Data
    init_db()

    # Register API Blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(telemetry_bp)
    app.register_blueprint(farms_bp)
    app.register_blueprint(schedules_bp)
    app.register_blueprint(irrigation_bp)
    app.register_blueprint(weather_bp)
    app.register_blueprint(advisor_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(notifications_bp)

    # Frontend Page Serving Routes
    @app.route("/")
    @app.route("/dashboard")
    def serve_dashboard():
        return send_from_directory(FRONTEND_DIR, "index.html")

    @app.route("/farms")
    def serve_farms():
        return send_from_directory(FRONTEND_DIR, "farms.html")

    @app.route("/schedules")
    def serve_schedules():
        return send_from_directory(FRONTEND_DIR, "schedules.html")

    @app.route("/weather-view")
    def serve_weather():
        return send_from_directory(FRONTEND_DIR, "weather.html")

    @app.route("/advisor-view")
    def serve_advisor():
        return send_from_directory(FRONTEND_DIR, "advisor.html")

    @app.route("/analytics-view")
    def serve_analytics():
        return send_from_directory(FRONTEND_DIR, "analytics.html")

    @app.route("/profile-view")
    def serve_profile():
        return send_from_directory(FRONTEND_DIR, "profile.html")

    @app.route("/<path:filename>")
    def serve_static(filename):
        if os.path.exists(os.path.join(FRONTEND_DIR, filename)):
            return send_from_directory(FRONTEND_DIR, filename)
        return send_from_directory(FRONTEND_DIR, "index.html")

    @app.route("/api/health")
    def health_check():
        return jsonify({
            "status": "healthy",
            "system": "DHARAA Smart Irrigation Platform",
            "version": "1.0.0",
            "endpoints": [
                "/api/telemetry", "/api/telemetry/latest", "/api/telemetry/history",
                "/api/farms", "/api/schedules", "/api/irrigation/command",
                "/api/irrigation/events", "/api/weather", "/api/advisor/crop",
                "/api/advisor/irrigation", "/api/analytics/summary", "/api/notifications"
            ]
        })

    return app

if __name__ == "__main__":
    app = create_app()
    # Runs on port 5000; host 0.0.0.0 allows ESP32 on same LAN to connect!
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
