import os
import re
import sqlite3
import threading
import time
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path

import psutil
import pystray
from flask import Flask, jsonify, request, send_from_directory
from PIL import Image, ImageDraw

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("APPDATA", BASE_DIR)) / "GameTrack"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "gametrack.db"
WEB_DIR = BASE_DIR / "web"
HOST = "127.0.0.1"
PORT = 5050

app = Flask(__name__, static_folder=str(WEB_DIR), static_url_path="")

tracker_lock = threading.Lock()
tracked_games = {}
# game_id -> {pid, create_time, started_at}
current_sessions = {}
stop_event = threading.Event()


def db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 10000")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db():
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS games (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                process_name TEXT NOT NULL,
                icon TEXT DEFAULT '🎮',
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id INTEGER NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT NOT NULL,
                duration INTEGER NOT NULL,
                FOREIGN KEY(game_id) REFERENCES games(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS public_games (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slug TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                process_name TEXT NOT NULL,
                icon TEXT DEFAULT '🎮',
                platform TEXT DEFAULT 'Windows',
                genre TEXT DEFAULT '',
                description TEXT DEFAULT '',
                cover_url TEXT DEFAULT '',
                is_public INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        # Migration for databases created by older versions.
        columns = {row[1] for row in conn.execute("PRAGMA table_info(games)")}
        if "process_pid" not in columns:
            conn.execute("ALTER TABLE games ADD COLUMN process_pid INTEGER")

        # Keep the existing locally tracked games and seed the public-ready catalog.
        existing_games = conn.execute(
            "SELECT name, process_name, icon, created_at FROM games"
        ).fetchall()
        for game in existing_games:
            slug = make_slug(game[0])
            conn.execute("""
                INSERT OR IGNORE INTO public_games
                (slug, name, process_name, icon, is_public, created_at, updated_at)
                VALUES (?, ?, ?, ?, 1, ?, ?)
            """, (slug, game[0], game[1], game[2], game[3],
                  datetime.now().isoformat(timespec="seconds")))
        conn.commit()


def make_slug(value):
    value = value.casefold().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "game"


def list_games():
    with db() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM games ORDER BY name COLLATE NOCASE"
        ).fetchall()]


def process_snapshot():
    result = []
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            name = proc.info["name"]
            if name:
                result.append({"pid": proc.info["pid"], "name": name})
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return result


def find_process(process_name, preferred_pid=None):
    """Return one matching process with a stable identity, or None."""
    target = process_name.casefold()
    candidates = []
    for proc in psutil.process_iter(["name"]):
        try:
            name = proc.info["name"]
            if not name or name.casefold() != target:
                continue
            candidates.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if not candidates:
        return None

    if preferred_pid:
        candidates.sort(key=lambda p: p.pid != preferred_pid)

    for proc in candidates:
        try:
            return {
                "pid": proc.pid,
                "create_time": proc.create_time(),
            }
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None


def process_identity_is_alive(session, process_name):
    """Check the exact process, not just another process with the same name."""
    try:
        proc = psutil.Process(session["pid"])
        return (
            proc.name().casefold() == process_name.casefold()
            and abs(proc.create_time() - session["create_time"]) < 0.01
        )
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return False


def close_session(game_id, session, ended_at):
    duration = max(1, int((ended_at - session["started_at"]).total_seconds()))
    with db() as conn:
        conn.execute(
            "INSERT INTO sessions(game_id, started_at, ended_at, duration) VALUES (?, ?, ?, ?)",
            (game_id, session["started_at"].isoformat(timespec="seconds"),
             ended_at.isoformat(timespec="seconds"), duration)
        )
        conn.commit()


def tracker_loop():
    while not stop_event.is_set():
        games = list_games()
        now = datetime.now()

        with tracker_lock:
            known_ids = {g["id"] for g in games}

            for game_id in list(current_sessions):
                if game_id not in known_ids:
                    current_sessions.pop(game_id, None)

            sessions_to_close = []
            for game in games:
                game_id = game["id"]
                session = current_sessions.get(game_id)

                if session and not process_identity_is_alive(session, game["process_name"]):
                    current_sessions.pop(game_id, None)
                    sessions_to_close.append((game_id, session))
                    session = None

                if session is None:
                    found = find_process(game["process_name"], game["process_pid"])
                    if found:
                        current_sessions[game_id] = {
                            **found,
                            "started_at": now,
                        }

        # Do database writes outside the tracking lock.
        for game_id, session in sessions_to_close:
            close_session(game_id, session, now)

        stop_event.wait(3)


def stats():
    with db() as conn:
        total = conn.execute(
            "SELECT COALESCE(SUM(duration),0) FROM sessions"
        ).fetchone()[0]

        start_today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        today = conn.execute(
            "SELECT COALESCE(SUM(duration),0) FROM sessions WHERE ended_at >= ?",
            (start_today,)
        ).fetchone()[0]

        games = conn.execute("""
            SELECT g.id, g.name, g.process_name, g.icon,
                   COALESCE(SUM(s.duration),0) AS seconds,
                   COUNT(s.id) AS sessions
            FROM games g
            LEFT JOIN sessions s ON s.game_id=g.id
            GROUP BY g.id
            ORDER BY seconds DESC, g.name COLLATE NOCASE
        """).fetchall()

    with tracker_lock:
        active = []
        for game in list_games():
            session = current_sessions.get(game["id"])
            if session:
                active.append({
                    **game,
                    "pid": session["pid"],
                    "started_at": session["started_at"].isoformat(timespec="seconds"),
                    "elapsed": int((datetime.now() - session["started_at"]).total_seconds())
                })

    return {
        "total": total,
        "today": today,
        "games": [dict(g) for g in games],
        "active": active,
    }


@app.get("/")
def index():
    return send_from_directory(WEB_DIR, "index.html")


@app.get("/<path:path>")
def static_files(path):
    return send_from_directory(WEB_DIR, path)


@app.get("/api/games")
def api_games():
    return jsonify(stats())


@app.get("/api/catalog")
def api_catalog():
    """Public-ready game catalog. Use ?public=1 to filter published entries."""
    only_public = request.args.get("public") == "1"
    query = "SELECT * FROM public_games"
    if only_public:
        query += " WHERE is_public=1"
    query += " ORDER BY name COLLATE NOCASE"
    with db() as conn:
        return jsonify([dict(row) for row in conn.execute(query).fetchall()])


@app.get("/api/catalog/export")
def export_catalog():
    """Export only published entries in a portable JSON shape."""
    with db() as conn:
        rows = conn.execute("""
            SELECT slug, name, process_name, icon, platform, genre,
                   description, cover_url, updated_at
            FROM public_games
            WHERE is_public=1
            ORDER BY name COLLATE NOCASE
        """).fetchall()
    return jsonify({"version": 1, "games": [dict(row) for row in rows]})


@app.post("/api/catalog")
def add_catalog_game():
    """Add a catalog entry locally; publication remains an explicit flag."""
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    process_name = str(data.get("process_name", "")).strip()
    if not name or not process_name:
        return jsonify({"error": "Nom et processus obligatoires."}), 400

    now = datetime.now().isoformat(timespec="seconds")
    values = (
        make_slug(name), name, process_name,
        str(data.get("icon", "🎮")).strip() or "🎮",
        str(data.get("platform", "Windows")).strip() or "Windows",
        str(data.get("genre", "")).strip(),
        str(data.get("description", "")).strip(),
        str(data.get("cover_url", "")).strip(),
        1 if data.get("is_public") is True else 0, now, now,
    )
    with db() as conn:
        try:
            conn.execute("""
                INSERT INTO public_games
                (slug, name, process_name, icon, platform, genre,
                 description, cover_url, is_public, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, values)
            conn.commit()
        except sqlite3.IntegrityError:
            return jsonify({"error": "Ce jeu existe déjà dans le catalogue."}), 409
    return jsonify({"ok": True, "slug": values[0]})


@app.get("/api/processes")
def api_processes():
    return jsonify(process_snapshot())


@app.post("/api/games")
def add_game():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    process_name = str(data.get("process_name", "")).strip()
    process_pid = data.get("process_pid")
    icon = str(data.get("icon", "🎮")).strip() or "🎮"

    if not name or not process_name:
        return jsonify({"error": "Nom et processus obligatoires."}), 400

    if len(name) > 80 or len(process_name) > 255:
        return jsonify({"error": "Nom trop long."}), 400

    try:
        process_pid = int(process_pid) if process_pid else None
    except (TypeError, ValueError):
        process_pid = None

    with db() as conn:
        try:
            conn.execute(
                "INSERT INTO games(name, process_name, process_pid, icon, created_at) VALUES (?, ?, ?, ?, ?)",
                (name, process_name, process_pid, icon, datetime.now().isoformat(timespec="seconds"))
            )
            conn.commit()
        except sqlite3.IntegrityError:
            return jsonify({"error": "Ce jeu existe déjà."}), 409

    return jsonify({"ok": True})


@app.delete("/api/games/<int:game_id>")
def delete_game(game_id):
    with tracker_lock:
        current_sessions.pop(game_id, None)

    with db() as conn:
        conn.execute("DELETE FROM sessions WHERE game_id=?", (game_id,))
        cur = conn.execute("DELETE FROM games WHERE id=?", (game_id,))
        conn.commit()

    if cur.rowcount == 0:
        return jsonify({"error": "Jeu introuvable."}), 404
    return jsonify({"ok": True})


def tray_image():
    image = Image.new("RGBA", (64, 64), (20, 20, 28, 255))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((7, 7, 57, 57), radius=13, fill=(111, 91, 255, 255))
    draw.text((17, 15), "G", fill="white")
    return image


def open_dashboard(icon=None, item=None):
    webbrowser.open(f"http://{HOST}:{PORT}")


def quit_app(icon, item):
    stop_event.set()
    icon.stop()


def tray_loop():
    menu = pystray.Menu(
        pystray.MenuItem("Ouvrir GameTrack", open_dashboard, default=True),
        pystray.MenuItem("Quitter", quit_app)
    )
    icon = pystray.Icon("GameTrack", tray_image(), "GameTrack", menu)
    icon.run()


if __name__ == "__main__":
    init_db()
    threading.Thread(target=tracker_loop, daemon=True).start()
    threading.Thread(target=tray_loop, daemon=True).start()
    webbrowser.open(f"http://{HOST}:{PORT}")
    app.run(host=HOST, port=PORT, debug=False, use_reloader=False)

