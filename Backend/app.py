from flask import Flask, jsonify, request
from flask_cors import CORS

import sqlite3
import subprocess
import platform
import re
import socket
from datetime import datetime


# =========================================================
# FLASK CONFIGURATION
# =========================================================

app = Flask(__name__)

CORS(app)


# =========================================================
# DATABASE
# =========================================================

DB_NAME = "network_monitor.db"


def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


# =========================================================
# INITIALIZE DATABASE
# =========================================================

def initialize_database():

    conn = get_db_connection()
    cursor = conn.cursor()

    # Devices table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS devices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            ip_address TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    # Monitoring history table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS monitoring_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            latency REAL,
            checked_at TEXT NOT NULL,
            FOREIGN KEY(device_id) REFERENCES devices(id)
        )
    """)

    conn.commit()

    # Add default device if database is empty
    cursor.execute("""
        SELECT COUNT(*) FROM devices
    """)

    count = cursor.fetchone()[0]

    if count == 0:

        cursor.execute("""
            INSERT INTO devices
            (name, ip_address, created_at)
            VALUES (?, ?, ?)
        """, (
            "My Computer",
            "127.0.0.1",
            datetime.now().isoformat()
        ))

        conn.commit()

    conn.close()


# =========================================================
# PING DEVICE
# =========================================================

def ping_device(host):

    try:

        if platform.system().lower() == "windows":

            command = [
                "ping",
                "-n",
                "1",
                "-w",
                "1000",
                host
            ]

        else:

            command = [
                "ping",
                "-c",
                "1",
                "-W",
                "1",
                host
            ]

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=5
        )

        output = result.stdout + result.stderr

        if result.returncode == 0:

            latency_match = re.search(
                r"time[=<]\s*(\d+(?:\.\d+)?)\s*ms",
                output,
                re.IGNORECASE
            )

            if latency_match:
                latency = float(
                    latency_match.group(1)
                )
            else:
                latency = 0

            return {
                "status": "UP",
                "latency": latency
            }

        return {
            "status": "DOWN",
            "latency": None
        }

    except Exception:

        return {
            "status": "DOWN",
            "latency": None
        }


# =========================================================
# SAVE MONITORING RESULT
# =========================================================

def save_monitoring_result(
    device_id,
    status,
    latency
):

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO monitoring_history
        (
            device_id,
            status,
            latency,
            checked_at
        )
        VALUES (?, ?, ?, ?)
    """, (
        device_id,
        status,
        latency,
        datetime.now().isoformat()
    ))

    conn.commit()
    conn.close()


# =========================================================
# HEALTH CHECK
# =========================================================

@app.route("/api/health", methods=["GET"])
def health():

    return jsonify({
        "status": "OK",
        "message": "Network Monitoring API is running."
    })


# =========================================================
# GET ALL DEVICES
# =========================================================

@app.route("/api/devices", methods=["GET"])
def get_devices():

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            id,
            name,
            ip_address,
            created_at
        FROM devices
        ORDER BY id
    """)

    rows = cursor.fetchall()

    conn.close()

    devices = []

    for row in rows:

        device_id = row["id"]

        result = ping_device(
            row["ip_address"]
        )

        status = result["status"]
        latency = result["latency"]

        # Save monitoring result
        save_monitoring_result(
            device_id,
            status,
            latency
        )

        devices.append({
            "id": device_id,
            "name": row["name"],
            "ip_address": row["ip_address"],
            "created_at": row["created_at"],
            "status": status,
            "latency": latency
        })

    return jsonify(devices)


# =========================================================
# ADD DEVICE
# =========================================================

@app.route("/api/devices", methods=["POST"])
def add_device():

    data = request.get_json()

    if not data:

        return jsonify({
            "error": "Request body is required."
        }), 400

    name = data.get("name")
    ip_address = data.get("ip_address")

    if not name or not ip_address:

        return jsonify({
            "error": "Name and IP address are required."
        }), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO devices
        (
            name,
            ip_address,
            created_at
        )
        VALUES (?, ?, ?)
    """, (
        name,
        ip_address,
        datetime.now().isoformat()
    ))

    device_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return jsonify({
        "message": "Device added successfully.",
        "id": device_id,
        "name": name,
        "ip_address": ip_address
    }), 201


# =========================================================
# DELETE DEVICE
# =========================================================

@app.route(
    "/api/devices/<int:device_id>",
    methods=["DELETE"]
)
def delete_device(device_id):

    conn = get_db_connection()
    cursor = conn.cursor()

    # Delete monitoring history
    cursor.execute("""
        DELETE FROM monitoring_history
        WHERE device_id = ?
    """, (device_id,))

    # Delete device
    cursor.execute("""
        DELETE FROM devices
        WHERE id = ?
    """, (device_id,))

    if cursor.rowcount == 0:

        conn.close()

        return jsonify({
            "error": "Device not found."
        }), 404

    conn.commit()
    conn.close()

    return jsonify({
        "message": "Device deleted successfully."
    })


# =========================================================
# PING API
# =========================================================

@app.route("/api/ping", methods=["GET"])
def ping_api():

    host = request.args.get("host")

    if not host:

        return jsonify({
            "error": "Host is required."
        }), 400

    result = ping_device(host)

    return jsonify({
        "host": host,
        "status": result["status"],
        "latency": result["latency"]
    })


# =========================================================
# DEVICE HISTORY
# =========================================================

@app.route(
    "/api/devices/<int:device_id>/history",
    methods=["GET"]
)
def get_history(device_id):

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            id,
            device_id,
            status,
            latency,
            checked_at
        FROM monitoring_history
        WHERE device_id = ?
        ORDER BY id DESC
        LIMIT 50
    """, (device_id,))

    rows = cursor.fetchall()

    conn.close()

    history = []

    for row in rows:

        history.append({
            "id": row["id"],
            "device_id": row["device_id"],
            "status": row["status"],
            "latency": row["latency"],
            "checked_at": row["checked_at"]
        })

    return jsonify(history)


# =========================================================
# UPTIME API
# =========================================================

@app.route(
    "/api/devices/<int:device_id>/uptime",
    methods=["GET"]
)
def get_uptime(device_id):

    conn = get_db_connection()
    cursor = conn.cursor()

    # Check device exists
    cursor.execute("""
        SELECT id
        FROM devices
        WHERE id = ?
    """, (device_id,))

    device = cursor.fetchone()

    if not device:

        conn.close()

        return jsonify({
            "error": "Device not found."
        }), 404

    cursor.execute("""
        SELECT

            COUNT(*) AS total_checks,

            SUM(
                CASE
                    WHEN status = 'UP'
                    THEN 1
                    ELSE 0
                END
            ) AS up_checks,

            SUM(
                CASE
                    WHEN status = 'DOWN'
                    THEN 1
                    ELSE 0
                END
            ) AS down_checks

        FROM monitoring_history

        WHERE device_id = ?
    """, (device_id,))

    row = cursor.fetchone()

    conn.close()

    total_checks = row["total_checks"] or 0
    up_checks = row["up_checks"] or 0
    down_checks = row["down_checks"] or 0

    if total_checks > 0:

        uptime_percentage = round(
            (up_checks / total_checks) * 100,
            2
        )

    else:

        uptime_percentage = 0

    return jsonify({
        "device_id": device_id,
        "total_checks": total_checks,
        "up_checks": up_checks,
        "down_checks": down_checks,
        "uptime_percentage": uptime_percentage
    })


# =========================================================
# STATISTICS API
# =========================================================

@app.route(
    "/api/devices/<int:device_id>/statistics",
    methods=["GET"]
)
def get_statistics(device_id):

    conn = get_db_connection()
    cursor = conn.cursor()

    # Check device exists
    cursor.execute("""
        SELECT id
        FROM devices
        WHERE id = ?
    """, (device_id,))

    device = cursor.fetchone()

    if not device:

        conn.close()

        return jsonify({
            "error": "Device not found."
        }), 404

    # Get statistics
    cursor.execute("""
        SELECT

            COUNT(*) AS total_checks,

            SUM(
                CASE
                    WHEN status = 'UP'
                    THEN 1
                    ELSE 0
                END
            ) AS up_checks,

            SUM(
                CASE
                    WHEN status = 'DOWN'
                    THEN 1
                    ELSE 0
                END
            ) AS down_checks,

            AVG(latency) AS average_latency,

            MAX(latency) AS highest_latency,

            MIN(latency) AS lowest_latency

        FROM monitoring_history

        WHERE device_id = ?
    """, (device_id,))

    row = cursor.fetchone()

    # Count outages
    cursor.execute("""
        SELECT COUNT(*)
        FROM monitoring_history
        WHERE device_id = ?
        AND status = 'DOWN'
    """, (device_id,))

    outage_row = cursor.fetchone()

    conn.close()

    total_checks = row["total_checks"] or 0

    up_checks = row["up_checks"] or 0

    down_checks = row["down_checks"] or 0

    average_latency = row["average_latency"]

    highest_latency = row["highest_latency"]

    lowest_latency = row["lowest_latency"]

    outage_count = outage_row[0] or 0

    if average_latency is not None:

        average_latency = round(
            average_latency,
            2
        )

    else:

        average_latency = 0

    if highest_latency is None:
        highest_latency = 0

    if lowest_latency is None:
        lowest_latency = 0

    if total_checks > 0:

        uptime_percentage = round(
            (up_checks / total_checks) * 100,
            2
        )

    else:

        uptime_percentage = 0

    return jsonify({
        "device_id": device_id,
        "total_checks": total_checks,
        "up_checks": up_checks,
        "down_checks": down_checks,
        "uptime_percentage": uptime_percentage,
        "average_latency": average_latency,
        "highest_latency": highest_latency,
        "lowest_latency": lowest_latency,
        "outage_count": outage_count
    })


# =========================================================
# NETWORK TROUBLESHOOTER
# =========================================================

@app.route(
    "/api/troubleshoot",
    methods=["GET"]
)
def troubleshoot():

    host = request.args.get("host")

    if not host:

        return jsonify({
            "error": "Host is required."
        }), 400


    # =====================================================
    # PING TEST
    # =====================================================

    ping_result = ping_device(host)

    if ping_result["status"] == "UP":

        ping_data = {
            "reachable": True,
            "latency": ping_result["latency"]
        }

    else:

        ping_data = {
            "reachable": False,
            "latency": None
        }


    # =====================================================
    # PACKET LOSS TEST
    # =====================================================

    try:

        if platform.system().lower() == "windows":

            command = [
                "ping",
                "-n",
                "4",
                "-w",
                "1000",
                host
            ]

        else:

            command = [
                "ping",
                "-c",
                "4",
                "-W",
                "1",
                host
            ]

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=10
        )

        output = (
            result.stdout +
            result.stderr
        )

        # Windows:
        # Lost = 0 (0% loss)

        # Linux:
        # 0% packet loss

        loss_match = re.search(
            r"(\d+)%\s*(?:packet )?loss",
            output,
            re.IGNORECASE
        )

        if loss_match:

            loss_percentage = int(
                loss_match.group(1)
            )

            packet_success = True

            packet_message = (
                f"{loss_percentage}% packet loss detected."
            )

        else:

            # Windows sometimes gives:
            # (0% loss)

            loss_match = re.search(
                r"\((\d+)%\s*loss\)",
                output,
                re.IGNORECASE
            )

            if loss_match:

                loss_percentage = int(
                    loss_match.group(1)
                )

                packet_success = True

                packet_message = (
                    f"{loss_percentage}% packet loss detected."
                )

            else:

                loss_percentage = 100

                packet_success = False

                packet_message = (
                    "Unable to determine packet loss."
                )

    except Exception as error:

        loss_percentage = 100

        packet_success = False

        packet_message = str(error)


    packet_loss = {
        "success": packet_success,
        "percentage": loss_percentage,
        "message": packet_message
    }


    # =====================================================
    # DNS TEST
    # =====================================================

    try:

        resolved_ip = socket.gethostbyname(
            host
        )

        dns_data = {
            "success": True,
            "ip_address": resolved_ip,
            "message": "DNS resolution successful."
        }

    except Exception:

        dns_data = {
            "success": False,
            "ip_address": None,
            "message": "DNS resolution failed."
        }


    # =====================================================
    # TCP PORT 443 TEST
    # =====================================================

    try:

        tcp_socket = socket.socket(
            socket.AF_INET,
            socket.SOCK_STREAM
        )

        tcp_socket.settimeout(3)

        connection_result = tcp_socket.connect_ex(
            (
                host,
                443
            )
        )

        tcp_socket.close()

        if connection_result == 0:

            tcp_status = "OPEN"

            tcp_message = (
                "TCP port 443 is reachable."
            )

        else:

            tcp_status = "CLOSED/FILTERED"

            tcp_message = (
                "TCP port 443 is closed or filtered."
            )

        tcp_success = True

    except Exception as error:

        tcp_status = "ERROR"

        tcp_message = str(error)

        tcp_success = False


    tcp_data = {
        "success": tcp_success,
        "status": tcp_status,
        "message": tcp_message
    }


    # =====================================================
    # OVERALL RESULT
    # =====================================================

    if ping_data["reachable"]:

        overall_message = (
            f"{host} is reachable."
        )

    else:

        overall_message = (
            f"{host} is not reachable."
        )


    # =====================================================
    # RETURN RESULT
    # =====================================================

    return jsonify({

        "host": host,

        "ping": ping_data,

        "packet_loss": packet_loss,

        "dns": dns_data,

        "tcp": tcp_data,

        "message": overall_message

    })


# =========================================================
# START SERVER
# =========================================================

if __name__ == "__main__":

    initialize_database()

    print()
    print("======================================")
    print(" Network Monitoring Dashboard API")
    print("======================================")
    print("Server: http://127.0.0.1:5000")
    print("======================================")
    print()

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True
    )