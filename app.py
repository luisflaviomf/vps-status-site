import os
import time
import socket
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, render_template, jsonify, request, abort

app = Flask(__name__)

# -------------------- Config --------------------
VPS_HOST = os.getenv("VPS_HOST", "roberto.ic.ufmt.br")
CONNECT_TIMEOUT = float(os.getenv("CONNECT_TIMEOUT", "1.5"))
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "60"))
APP_PORT = int(os.getenv("APP_PORT", "8080"))
START_PORT = int(os.getenv("START_PORT", "50101"))
END_PORT = int(os.getenv("END_PORT", "50200"))
START_ID = int(os.getenv("START_ID", "701"))
SAMPLE_INTERVAL_SEC = int(os.getenv("SAMPLE_INTERVAL_SEC", "60"))
DB_BACKEND = os.getenv("DB_BACKEND", "postgres").lower()

# Postgres
DB_HOST = os.getenv("DB_HOST", "db")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "appdb")
DB_USER = os.getenv("DB_USER", "appuser")
DB_PASSWORD = os.getenv("DB_PASSWORD", "appsecret")

# -------------------- Alvos --------------------
USERS = [
    "alan","andre","asafe","bianca","bruno","caio","carlos","eduardo","enzo","eric",
    "erick","fabio","fernando","gabrielr","gabriels","giovani","isis","joao","jose","juan",
    "julia","juliana","kristiann","laura","lorenzo","lucas","luis","marcos","milton","murilos",
    "murilot","palloma","pedrog","pedrov","raphael","raul","rhafael","tuliana","victor","vitor",
    "wagner","wellinghton"
]
user_by_port = {50101+i: USERS[i] for i in range(len(USERS))}

def parse_static_targets(raw: str):
    items = []
    if not raw:
        return items
    for part in [p.strip() for p in raw.split(",") if p.strip()]:
        host_port, *label = part.split("@", 1)
        label = label[0] if label else ""
        host, port = host_port.split(":")
        items.append({"host": host.strip(), "port": int(port.strip()), "user": label.strip() or "-"})
    return items

STATIC_TARGETS = parse_static_targets(os.getenv("STATIC_TARGETS", ""))

# Constrói linhas baseadas na faixa
ROWS = []
for idx, port in enumerate(range(START_PORT, END_PORT + 1)):
    rid = START_ID + idx
    user = user_by_port.get(port, "-")
    ROWS.append({"id": rid, "user": user, "port": port, "host": VPS_HOST})

# Adiciona alvos estáticos com IDs seguintes
next_id = (START_ID + (END_PORT - START_PORT)) + 1
for i, r in enumerate(STATIC_TARGETS):
    ROWS.append({"id": next_id + i, "user": r["user"], "port": r["port"], "host": r["host"]})

# -------------------- DB --------------------
def db_connect():
    if DB_BACKEND == "postgres":
        import psycopg2
        return psycopg2.connect(
            host=DB_HOST, port=DB_PORT, dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD
        )
    else:
        # fallback opcional (não necessário para a atividade)
        import sqlite3, pathlib
        path = pathlib.Path("data/data.db")
        path.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(str(path), check_same_thread=False)

def db_init():
    ddl_pg = """
    CREATE TABLE IF NOT EXISTS samples (
        id SERIAL PRIMARY KEY,
        host TEXT NOT NULL,
        port INTEGER NOT NULL,
        ts BIGINT NOT NULL,
        online INTEGER NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_samples_host_port_ts ON samples(host, port, ts);
    """
    ddl_sqlite = """
    CREATE TABLE IF NOT EXISTS samples (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        host TEXT NOT NULL,
        port INTEGER NOT NULL,
        ts INTEGER NOT NULL,
        online INTEGER NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_samples_host_port_ts ON samples(host, port, ts);
    """
    with db_connect() as conn:
        cur = conn.cursor()
        cur.execute(ddl_pg if DB_BACKEND == "postgres" else ddl_sqlite)
        conn.commit()

db_init()

# -------------------- Checagem --------------------
def check_port(host: str, port: int, timeout: float = 1.5) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        try:
            sock.connect((host, port))
            return True
        except Exception:
            return False

def check_all(rows):
    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(check_port, r["host"], r["port"], CONNECT_TIMEOUT): r for r in rows}
        for fut in as_completed(futures):
            r = futures[fut]
            ok = fut.result()
            results.append({"id": r["id"], "user": r["user"], "port": r["port"], "host": r["host"], "online": ok})
    results.sort(key=lambda x: x["id"])
    return results

# -------------------- Coletor em background --------------------
def sampler_loop():
    while True:
        start = time.time()
        results = check_all(ROWS)
        now = int(time.time())
        with db_connect() as conn:
            cur = conn.cursor()
            cur.executemany(
                "INSERT INTO samples (host, port, ts, online) VALUES (%s, %s, %s, %s);" if DB_BACKEND == "postgres"
                else "INSERT INTO samples (host, port, ts, online) VALUES (?, ?, ?, ?);",
                [(r["host"], r["port"], now, 1 if r["online"] else 0) for r in results]
            )
            conn.commit()
        elapsed = time.time() - start
        time.sleep(max(1.0, SAMPLE_INTERVAL_SEC - elapsed))

threading.Thread(target=sampler_loop, daemon=True).start()

# -------------------- Uptime e séries --------------------
def uptime_percentage(host: str, port: int, since_epoch: int):
    with db_connect() as conn:
        cur = conn.cursor()
        q = ("SELECT COUNT(*), SUM(online) FROM samples WHERE host=%s AND port=%s AND ts>=%s;"
             if DB_BACKEND == "postgres"
             else "SELECT COUNT(*), SUM(online) FROM samples WHERE host=? AND port=? AND ts>=?;")
        cur.execute(q, (host, port, since_epoch))
        total, up = cur.fetchone()
        if total == 0:
            return None
        up = up or 0
        return (up / total) * 100.0

def series_for(host: str, port: int, since_epoch: int):
    with db_connect() as conn:
        cur = conn.cursor()
        q = ("SELECT ts, online FROM samples WHERE host=%s AND port=%s AND ts>=%s ORDER BY ts ASC;"
             if DB_BACKEND == "postgres"
             else "SELECT ts, online FROM samples WHERE host=? AND port=? AND ts>=? ORDER BY ts ASC;")
        cur.execute(q, (host, port, since_epoch))
        rows = cur.fetchall()
        return [{"t": int(ts), "v": int(online)} for (ts, online) in rows]

# -------------------- Rotas --------------------
@app.route("/")
def index():
    return render_template("index.html", rows=ROWS, start_port=START_PORT, end_port=END_PORT)

@app.route("/api/status")
def api_status():
    return jsonify(check_all(ROWS))

@app.route("/vps/<path:host>/<int:port>")
def vps_page(host: str, port: int):
    match = next((r for r in ROWS if r["host"] == host and r["port"] == port), None)
    if not match:
        abort(404)
    user = match["user"]
    now = int(time.time())
    day = 24 * 3600
    week = 7 * day
    p1 = uptime_percentage(host, port, now - 3600)
    p24 = uptime_percentage(host, port, now - day)
    p7 = uptime_percentage(host, port, now - week)
    return render_template("vps.html", host=host, port=port, user=user, p1=p1, p24=p24, p7=p7)

@app.route("/api/series")
def api_series():
    host = request.args.get("host")
    port = int(request.args.get("port", "0"))
    if not host or port <= 0:
        abort(400)
    window = request.args.get("window", "24h")
    now = int(time.time())
    if window.endswith("h"):
        hours = int(window[:-1])
        since = now - hours * 3600
    elif window.endswith("d"):
        days = int(window[:-1])
        since = now - days * 86400
    else:
        since = now - 24 * 3600
    return jsonify(series_for(host, port, since))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=APP_PORT)
