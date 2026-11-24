import os, sqlite3, secrets
from functools import wraps
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, session, flash, abort
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from PIL import Image, UnidentifiedImageError

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR / "data"))
UPLOAD_DIR = Path(os.environ.get("UPLOAD_FOLDER", DATA_DIR / "uploads"))
DB_PATH = Path(os.environ.get("DATABASE_PATH", DATA_DIR / "ruben_asador.db"))
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
MAX_IMAGE_SIZE = 8 * 1024 * 1024

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-only-change-this-before-deploying")
app.config["MAX_CONTENT_LENGTH"] = MAX_IMAGE_SIZE
DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS photos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                filename TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

init_db()

def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin_login"))
        return fn(*args, **kwargs)
    return wrapper

def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(32)
    return session["_csrf"]

@app.context_processor
def inject_csrf():
    return {"csrf_token": csrf_token}

@app.before_request
def protect_posts():
    if request.method == "POST":
        token = request.form.get("_csrf")
        if not token or not secrets.compare_digest(token, session.get("_csrf", "")):
            abort(400, "Solicitud no válida. Actualizá la página e intentá nuevamente.")

def valid_image(file):
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        return False
    try:
        image = Image.open(file.stream)
        image.verify()
        file.stream.seek(0)
        return image.format in {"JPEG", "PNG", "WEBP"}
    except (UnidentifiedImageError, OSError):
        return False

@app.route("/")
def home():
    with db() as conn:
        photos = conn.execute("SELECT * FROM photos ORDER BY id DESC").fetchall()
    return render_template("index.html", photos=photos)

@app.route("/admin")
@admin_required
def admin():
    with db() as conn:
        photos = conn.execute("SELECT * FROM photos ORDER BY id DESC").fetchall()
    return render_template("admin.html", photos=photos)

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = os.environ.get("ADMIN_USERNAME", "")
        password_hash = os.environ.get("ADMIN_PASSWORD_HASH", "")
        if not username or not password_hash:
            flash("Falta configurar ADMIN_USERNAME y ADMIN_PASSWORD_HASH en las variables de entorno.", "error")
        elif request.form.get("username", "").strip() == username and check_password_hash(password_hash, request.form.get("password", "")):
            session.clear()
            session["admin_logged_in"] = True
            session["_csrf"] = secrets.token_urlsafe(32)
            return redirect(url_for("admin"))
        else:
            flash("Usuario o contraseña incorrectos.", "error")
    return render_template("login.html")

@app.route("/admin/logout", methods=["POST"])
@admin_required
def admin_logout():
    session.clear()
    return redirect(url_for("home"))

@app.route("/admin/upload", methods=["POST"])
@admin_required
def upload_photo():
    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    photo = request.files.get("photo")
    if not title or not photo or not photo.filename:
        flash("Completá el título y elegí una fotografía.", "error")
        return redirect(url_for("admin"))
    if not valid_image(photo):
        flash("Archivo no válido. Usá JPG, PNG o WEBP.", "error")
        return redirect(url_for("admin"))
    safe_name = secure_filename(photo.filename)
    filename = f"{secrets.token_hex(12)}_{safe_name}"
    photo.stream.seek(0)
    photo.save(UPLOAD_DIR / filename)
    with db() as conn:
        conn.execute("INSERT INTO photos (title, description, filename) VALUES (?, ?, ?)", (title, description, filename))
    flash("Fotografía publicada en la galería.", "success")
    return redirect(url_for("admin"))

@app.route("/admin/edit/<int:photo_id>", methods=["POST"])
@admin_required
def edit_photo(photo_id):
    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    if not title:
        flash("El título no puede quedar vacío.", "error")
        return redirect(url_for("admin"))
    with db() as conn:
        conn.execute("UPDATE photos SET title=?, description=? WHERE id=?", (title, description, photo_id))
    flash("Publicación actualizada.", "success")
    return redirect(url_for("admin"))

@app.route("/admin/delete/<int:photo_id>", methods=["POST"])
@admin_required
def delete_photo(photo_id):
    with db() as conn:
        photo = conn.execute("SELECT filename FROM photos WHERE id=?", (photo_id,)).fetchone()
        if photo:
            conn.execute("DELETE FROM photos WHERE id=?", (photo_id,))
            try:
                (UPLOAD_DIR / photo["filename"]).unlink(missing_ok=True)
            except OSError:
                pass
    flash("Publicación eliminada.", "success")
    return redirect(url_for("admin"))

@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    from flask import send_from_directory
    return send_from_directory(UPLOAD_DIR, filename)

@app.errorhandler(413)
def too_large(_):
    flash("La imagen supera el límite de 8 MB.", "error")
    return redirect(url_for("admin"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
