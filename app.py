import os, sqlite3, json, secrets, zipfile, io, hashlib
from datetime import datetime, timezone
from functools import wraps
from flask import Flask, render_template, request, jsonify, session
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("STORYVERSE_DATA_DIR", os.path.join(APP_DIR, "data"))
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "storyverse.db")
UPLOAD_DIR = os.path.join(DATA_DIR, "updates")
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config.update(MAX_CONTENT_LENGTH=8 * 1024 * 1024, SESSION_COOKIE_HTTPONLY=True,
                  SESSION_COOKIE_SAMESITE="Lax",
                  SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "false").lower() == "true")
VERSION = "1.0.0"

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS projects(
            id TEXT PRIMARY KEY, title TEXT NOT NULL, kind TEXT NOT NULL,
            content TEXT NOT NULL, updated_at TEXT NOT NULL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS updates(
            id INTEGER PRIMARY KEY AUTOINCREMENT, filename TEXT NOT NULL,
            stored_name TEXT NOT NULL, sha256 TEXT NOT NULL, status TEXT NOT NULL,
            notes TEXT, created_at TEXT NOT NULL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS prompts(
            id INTEGER PRIMARY KEY AUTOINCREMENT, prompt TEXT NOT NULL,
            status TEXT NOT NULL, created_at TEXT NOT NULL)""")

init_db()

def admin_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("is_admin"):
            return jsonify({"error": "No autorizado"}), 401
        return fn(*args, **kwargs)
    return wrapped

@app.after_request
def security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return resp

@app.route("/")
def index():
    return render_template("index.html", version=VERSION)

@app.get("/api/projects")
def get_projects():
    with db() as c:
        rows = c.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()
    return jsonify([{"id": r["id"], "title": r["title"], "kind": r["kind"],
                     "content": json.loads(r["content"]), "updated_at": r["updated_at"]} for r in rows])

@app.post("/api/projects")
def save_project():
    data = request.get_json(silent=True) or {}
    pid = data.get("id")
    title = str(data.get("title", "Proyecto sin título"))[:100]
    kind = str(data.get("kind", "historia"))[:30]
    content = data.get("content", {})
    if not isinstance(content, dict) or not pid:
        return jsonify({"error": "Datos de proyecto inválidos"}), 400
    serialized = json.dumps(content, ensure_ascii=False)
    if len(serialized) > 2_000_000:
        return jsonify({"error": "El proyecto supera el tamaño permitido"}), 413
    now = datetime.now(timezone.utc).isoformat()
    with db() as c:
        c.execute("""INSERT INTO projects(id,title,kind,content,updated_at) VALUES(?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET title=excluded.title, kind=excluded.kind,
        content=excluded.content, updated_at=excluded.updated_at""",
        (pid, title, kind, serialized, now))
    return jsonify({"ok": True, "updated_at": now})

@app.delete("/api/projects/<pid>")
def delete_project(pid):
    with db() as c:
        c.execute("DELETE FROM projects WHERE id=?", (pid,))
    return jsonify({"ok": True})

@app.get("/admin")
def admin_page():
    if not session.get("is_admin"):
        return render_template("login.html")
    return render_template("admin.html", version=VERSION)

@app.post("/admin/login")
def admin_login():
    data = request.get_json(silent=True) or {}
    password = os.environ.get("ADMIN_PASSWORD", "")
    password_hash = os.environ.get("ADMIN_PASSWORD_HASH", "")
    supplied = str(data.get("password", ""))
    valid = bool(password and secrets.compare_digest(supplied, password))
    if password_hash:
        try:
            valid = check_password_hash(password_hash, supplied)
        except ValueError:
            valid = False
    if not (password or password_hash):
        return jsonify({"error": "El administrador aún no configuró ADMIN_PASSWORD o ADMIN_PASSWORD_HASH en Render."}), 503
    if not valid:
        return jsonify({"error": "Contraseña incorrecta"}), 401
    session.clear()
    session["is_admin"] = True
    session.permanent = True
    return jsonify({"ok": True})

@app.post("/admin/logout")
@admin_required
def admin_logout():
    session.clear()
    return jsonify({"ok": True})

@app.get("/admin/api/updates")
@admin_required
def list_updates():
    with db() as c:
        rows = c.execute("SELECT id,filename,sha256,status,notes,created_at FROM updates ORDER BY id DESC").fetchall()
    return jsonify([dict(r) for r in rows])

@app.post("/admin/api/updates")
@admin_required
def upload_update():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "Seleccioná un archivo ZIP"}), 400
    if not f.filename.lower().endswith(".zip"):
        return jsonify({"error": "Solo se admiten paquetes .zip"}), 400
    raw = f.read()
    if len(raw) > 8 * 1024 * 1024:
        return jsonify({"error": "El archivo supera 8 MB"}), 413
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            names = zf.namelist()
            if len(names) > 100 or any(n.startswith(("/", "\\\\")) or ".." in n.split("/") for n in names):
                raise ValueError("Rutas o cantidad de archivos no permitidas")
            allowed = (".png", ".jpg", ".jpeg", ".webp", ".svg", ".txt", ".md", ".json")
            if any(not n.lower().endswith(allowed) for n in names if not n.endswith("/")):
                raise ValueError("El ZIP contiene tipos de archivo no permitidos")
            if sum(i.file_size for i in zf.infolist()) > 20 * 1024 * 1024:
                raise ValueError("El contenido descomprimido supera 20 MB")
            if not names:
                raise ValueError("El ZIP está vacío")
    except (zipfile.BadZipFile, ValueError, OSError) as e:
        return jsonify({"error": f"Paquete no válido: {str(e)}"}), 400
    digest = hashlib.sha256(raw).hexdigest()
    stored = secrets.token_hex(12) + ".zip"
    with open(os.path.join(UPLOAD_DIR, stored), "wb") as out:
        out.write(raw)
    with db() as c:
        cur = c.execute("INSERT INTO updates(filename,stored_name,sha256,status,notes,created_at) VALUES(?,?,?,?,?,?)",
            (secure_filename(f.filename), stored, digest, "Pendiente de revisión",
             "Paquete validado y guardado. No se ejecutó ni se aplicó automáticamente.",
             datetime.now(timezone.utc).isoformat()))
    return jsonify({"ok": True, "id": cur.lastrowid, "sha256": digest,
                    "message": "Archivo validado y guardado para revisión."})

@app.post("/admin/api/prompts")
@admin_required
def save_prompt():
    data = request.get_json(silent=True) or {}
    prompt = str(data.get("prompt", "")).strip()
    if not prompt or len(prompt) > 10000:
        return jsonify({"error": "Escribí una instrucción de hasta 10.000 caracteres"}), 400
    with db() as c:
        cur = c.execute("INSERT INTO prompts(prompt,status,created_at) VALUES(?,?,?)",
            (prompt, "Borrador para revisión manual", datetime.now(timezone.utc).isoformat()))
    return jsonify({"ok": True, "id": cur.lastrowid,
                    "status": "Borrador guardado. No se ejecutó ningún cambio."})

@app.get("/admin/api/prompts")
@admin_required
def list_prompts():
    with db() as c:
        rows = c.execute("SELECT id,prompt,status,created_at FROM prompts ORDER BY id DESC").fetchall()
    return jsonify([dict(r) for r in rows])

@app.errorhandler(413)
def too_large(_):
    return jsonify({"error": "El archivo es demasiado grande (máximo 8 MB)."}), 413

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
