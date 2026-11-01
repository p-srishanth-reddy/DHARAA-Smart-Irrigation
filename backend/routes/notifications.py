from flask import Blueprint, request, jsonify
from backend.services.notification_service import get_user_notifications, mark_notification_read

notifications_bp = Blueprint("notifications", __name__)

@notifications_bp.route("/api/notifications", methods=["GET"])
def list_notifications():
    user_id = request.args.get("user_id", 1, type=int)
    unread_only = request.args.get("unread", "false").lower() == "true"
    notifs = get_user_notifications(user_id, unread_only=unread_only)
    return jsonify(notifs)

@notifications_bp.route("/api/notifications/<int:notif_id>/read", methods=["POST"])
def read_notification(notif_id):
    user_id = request.args.get("user_id", 1, type=int)
    mark_notification_read(notif_id, user_id)
    return jsonify({"message": "Notification marked as read"})
