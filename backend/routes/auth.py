from flask import Blueprint, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from backend.database import get_db

auth_bp = Blueprint("auth", __name__)

@auth_bp.route("/api/auth/register", methods=["POST"])
def register():
    data = request.get_json() or {}
    username = data.get("username", "").strip()
    email = data.get("email", "").strip()
    password = data.get("password", "")

    if not username or not email or not password:
        return jsonify({"error": "Username, email, and password are required"}), 400

    conn = get_db()
    cursor = conn.cursor()
    try:
        pwd_hash = generate_password_hash(password)
        cursor.execute("""
            INSERT INTO users (username, email, password_hash, timezone, units)
            VALUES (?, ?, ?, 'Asia/Kolkata', 'metric')
        """, (username, email, pwd_hash))
        conn.commit()
        user_id = cursor.lastrowid
        conn.close()
        return jsonify({"message": "Registration successful", "user_id": user_id, "username": username}), 201
    except Exception as e:
        conn.close()
        return jsonify({"error": f"Registration failed: {str(e)}"}), 409

@auth_bp.route("/api/auth/login", methods=["POST"])
def login():
    data = request.get_json() or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")

    if not username or not password:
        return jsonify({"error": "Username and password required"}), 400

    conn = get_db()
    cursor = conn.cursor()
    user = cursor.execute("SELECT * FROM users WHERE username = ? OR email = ?", (username, username)).fetchone()
    conn.close()

    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "Invalid username or password"}), 401

    return jsonify({
        "message": "Login successful",
        "user": {
            "id": user["id"],
            "username": user["username"],
            "email": user["email"],
            "timezone": user["timezone"],
            "units": user["units"]
        },
        "token": f"dharaa-token-user-{user['id']}"  # Lightweight session token
    })

@auth_bp.route("/api/auth/profile", methods=["GET", "PUT"])
def profile():
    conn = get_db()
    cursor = conn.cursor()

    if request.method == "GET":
        user_id = request.args.get("user_id", 1, type=int)
        user = cursor.execute("SELECT id, username, email, timezone, units, created_at FROM users WHERE id = ?", (user_id,)).fetchone()
        conn.close()
        if not user:
            return jsonify({"error": "User not found"}), 404
        return jsonify(dict(user))

    elif request.method == "PUT":
        data = request.get_json() or {}
        user_id = data.get("user_id", 1)
        timezone = data.get("timezone", "Asia/Kolkata")
        units = data.get("units", "metric")

        cursor.execute("""
            UPDATE users
            SET timezone = ?, units = ?
            WHERE id = ?
        """, (timezone, units, user_id))
        conn.commit()
        conn.close()
        return jsonify({"message": "Profile updated successfully"})
