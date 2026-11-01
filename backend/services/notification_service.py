import sqlite3
from backend.database import get_db

def create_notification(user_id: int, message: str, severity: str = "info"):
    """
    Record an alert/notification for a user.
    Severity can be: 'info', 'warning', 'critical', 'success'
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO notifications (user_id, message, severity)
        VALUES (?, ?, ?)
    """, (user_id, message, severity))
    conn.commit()
    notif_id = cursor.lastrowid
    conn.close()
    return notif_id

def get_user_notifications(user_id: int, unread_only: bool = False):
    conn = get_db()
    cursor = conn.cursor()
    if unread_only:
        rows = cursor.execute("""
            SELECT * FROM notifications
            WHERE user_id = ? AND read_at IS NULL
            ORDER BY created_at DESC LIMIT 50
        """, (user_id,)).fetchall()
    else:
        rows = cursor.execute("""
            SELECT * FROM notifications
            WHERE user_id = ?
            ORDER BY created_at DESC LIMIT 50
        """, (user_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def mark_notification_read(notif_id: int, user_id: int):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE notifications
        SET read_at = CURRENT_TIMESTAMP
        WHERE id = ? AND user_id = ?
    """, (notif_id, user_id))
    conn.commit()
    conn.close()
