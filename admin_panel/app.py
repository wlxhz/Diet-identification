import os
import re
import secrets
import string
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from admin_database import ADMIN_DB_PATH, USER_DB_PATH, admin_db, init_admin_db, user_db


BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def load_secret():
    configured = os.environ.get("ADMIN_SECRET_KEY")
    if configured:
        return configured
    path = os.path.join(BASE_DIR, ".admin-session-secret")
    try:
        with open(path, "r", encoding="ascii") as file:
            value = file.read().strip()
            if len(value) >= 32:
                return value
    except OSError:
        pass
    value = secrets.token_hex(32)
    try:
        with open(path, "x", encoding="ascii") as file:
            file.write(value)
    except FileExistsError:
        with open(path, "r", encoding="ascii") as file:
            value = file.read().strip()
    return value


app = Flask(__name__)
app.secret_key = load_secret()
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Strict",
    MAX_CONTENT_LENGTH=2 * 1024 * 1024,
)
init_admin_db()


def adb():
    if "admin_db" not in g:
        g.admin_db = admin_db()
    return g.admin_db


def udb():
    if "user_db" not in g:
        g.user_db = user_db()
    return g.user_db


@app.teardown_appcontext
def close_connections(error=None):
    for key in ("admin_db", "user_db"):
        connection = g.pop(key, None)
        if connection is not None:
            connection.close()


def first_admin_exists():
    return adb().execute("SELECT 1 FROM admins LIMIT 1").fetchone() is not None


def current_admin():
    admin_id = session.get("admin_id")
    if not admin_id:
        return None
    return adb().execute("SELECT * FROM admins WHERE id=? AND active=1", (admin_id,)).fetchone()


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_admin():
            session.clear()
            flash("请先登录管理端", "warning")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


@app.before_request
def security_checks():
    if request.method == "POST":
        expected = session.get("csrf_token", "")
        supplied = request.form.get("csrf_token", "") or request.headers.get("X-CSRF-Token", "")
        if not expected or not supplied or not secrets.compare_digest(expected, supplied):
            abort(400, description="请求已失效，请刷新页面后重试")


@app.context_processor
def shared_context():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return {
        "admin": current_admin(),
        "csrf_token": session["csrf_token"],
        "user_db_path": USER_DB_PATH,
    }


def audit(action, target_type, target_id="", detail=""):
    admin = current_admin()
    connection = adb()
    connection.execute(
        "INSERT INTO audit_logs (admin_id,admin_name,action,target_type,target_id,detail,ip_address) "
        "VALUES (?,?,?,?,?,?,?)",
        (
            admin["id"] if admin else None,
            admin["display_name"] if admin else "系统",
            action,
            target_type,
            str(target_id or ""),
            detail,
            request.remote_addr or "",
        ),
    )
    connection.commit()


def validate_password(password):
    return (
        len(password) >= 10
        and any(char.isupper() for char in password)
        and any(char.islower() for char in password)
        and any(char.isdigit() for char in password)
    )


def generate_bind_code():
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(8))


@app.route("/")
def index():
    if not first_admin_exists():
        return redirect(url_for("setup"))
    return redirect(url_for("dashboard") if current_admin() else url_for("login"))


@app.route("/setup", methods=["GET", "POST"])
def setup():
    if first_admin_exists():
        return redirect(url_for("login"))
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        display_name = request.form.get("display_name", "").strip()
        password = request.form.get("password", "")
        if not re.fullmatch(r"[a-zA-Z0-9_]{4,30}", username):
            flash("账号须为 4–30 位字母、数字或下划线", "error")
        elif not display_name or len(display_name) > 30:
            flash("请输入 1–30 位管理员名称", "error")
        elif not validate_password(password):
            flash("密码至少 10 位，并包含大小写字母和数字", "error")
        else:
            connection = adb()
            connection.execute(
                "INSERT INTO admins (username,password_hash,display_name) VALUES (?,?,?)",
                (username, generate_password_hash(password), display_name),
            )
            connection.commit()
            flash("超级管理员创建成功，请登录", "success")
            return redirect(url_for("login"))
    return render_template("setup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if not first_admin_exists():
        return redirect(url_for("setup"))
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        connection = adb()
        failures = connection.execute(
            "SELECT COUNT(*) AS c FROM login_attempts WHERE username=? AND success=0 "
            "AND created_at >= datetime('now', '-15 minutes')",
            (username,),
        ).fetchone()["c"]
        if failures >= 5:
            flash("登录失败次数过多，请 15 分钟后再试", "error")
            return render_template("login.html")
        admin = connection.execute("SELECT * FROM admins WHERE username=? AND active=1", (username,)).fetchone()
        success = bool(admin and check_password_hash(admin["password_hash"], password))
        connection.execute("INSERT INTO login_attempts (username,success) VALUES (?,?)", (username, int(success)))
        connection.commit()
        if not success:
            flash("管理员账号或密码错误", "error")
            return render_template("login.html")
        session.clear()
        session["admin_id"] = admin["id"]
        session["csrf_token"] = secrets.token_urlsafe(32)
        connection.execute("UPDATE admins SET last_login_at=CURRENT_TIMESTAMP WHERE id=?", (admin["id"],))
        connection.commit()
        audit("登录管理端", "admin", admin["id"])
        return redirect(url_for("dashboard"))
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
@admin_required
def logout():
    audit("退出管理端", "admin", session.get("admin_id"))
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
@admin_required
def dashboard():
    connection = udb()
    stats = {
        "users": connection.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"],
        "supervisors": connection.execute("SELECT COUNT(*) AS c FROM users WHERE role='supervisor'").fetchone()["c"],
        "bound": connection.execute("SELECT COUNT(*) AS c FROM users WHERE role='supervisee' AND bound_to IS NOT NULL").fetchone()["c"],
        "today_records": connection.execute("SELECT COUNT(*) AS c FROM diet_records WHERE date(intake_time)=date('now','localtime')").fetchone()["c"],
    }
    goals = connection.execute(
        "SELECT health_goal,COUNT(*) AS count FROM users GROUP BY health_goal ORDER BY count DESC"
    ).fetchall()
    trend = connection.execute("""
        WITH RECURSIVE dates(day) AS (
            SELECT date('now','localtime','-6 days')
            UNION ALL SELECT date(day,'+1 day') FROM dates WHERE day < date('now','localtime')
        )
        SELECT dates.day,COUNT(dr.id) AS count,COALESCE(SUM(dr.calories),0) AS calories
        FROM dates LEFT JOIN diet_records dr ON date(dr.intake_time)=dates.day
        GROUP BY dates.day ORDER BY dates.day
    """).fetchall()
    recent = connection.execute(
        "SELECT dr.*,u.nickname FROM diet_records dr JOIN users u ON u.id=dr.user_id "
        "ORDER BY dr.created_at DESC LIMIT 8"
    ).fetchall()
    return render_template("dashboard.html", stats=stats, goals=goals, trend=trend, recent=recent)


@app.route("/users")
@admin_required
def users():
    query = request.args.get("q", "").strip()
    role = request.args.get("role", "").strip()
    sql = "SELECT u.*,s.nickname AS supervisor_name FROM users u LEFT JOIN users s ON s.id=u.bound_to WHERE 1=1"
    params = []
    if query:
        sql += " AND (u.nickname LIKE ? OR u.phone LIKE ? OR COALESCE(u.email,'') LIKE ?)"
        pattern = f"%{query}%"
        params.extend([pattern, pattern, pattern])
    if role in ("supervisor", "supervisee"):
        sql += " AND u.role=?"
        params.append(role)
    sql += " ORDER BY u.created_at DESC,u.id DESC"
    rows = udb().execute(sql, params).fetchall()
    return render_template("users.html", users=rows, query=query, role=role)


@app.route("/users/<int:user_id>")
@admin_required
def user_detail(user_id):
    connection = udb()
    user = connection.execute(
        "SELECT u.*,s.nickname AS supervisor_name FROM users u LEFT JOIN users s ON s.id=u.bound_to WHERE u.id=?",
        (user_id,),
    ).fetchone()
    if not user:
        abort(404)
    records = connection.execute(
        "SELECT * FROM diet_records WHERE user_id=? ORDER BY intake_time DESC LIMIT 50", (user_id,)
    ).fetchall()
    supervisees = connection.execute(
        "SELECT id,nickname,phone FROM users WHERE bound_to=? ORDER BY nickname", (user_id,)
    ).fetchall()
    return render_template("user_detail.html", user=user, records=records, supervisees=supervisees)


@app.route("/users/<int:user_id>/unbind", methods=["POST"])
@admin_required
def admin_unbind(user_id):
    connection = udb()
    user = connection.execute("SELECT id,nickname,bound_to FROM users WHERE id=?", (user_id,)).fetchone()
    if not user or not user["bound_to"]:
        flash("该用户当前没有监督关系", "warning")
    else:
        connection.execute("UPDATE users SET bound_to=NULL WHERE id=?", (user_id,))
        connection.commit()
        audit("解除监督关系", "user", user_id, f"用户：{user['nickname']}")
        flash("监督关系已解除", "success")
    return redirect(request.referrer or url_for("users"))


@app.route("/users/<int:user_id>/regenerate-code", methods=["POST"])
@admin_required
def regenerate_code(user_id):
    connection = udb()
    user = connection.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not user:
        abort(404)
    column = "supervisor_code" if user["role"] == "supervisor" else "supervisee_code"
    while True:
        code = generate_bind_code()
        if not connection.execute(f"SELECT 1 FROM users WHERE {column}=?", (code,)).fetchone():
            break
    connection.execute(f"UPDATE users SET {column}=? WHERE id=?", (code, user_id))
    connection.commit()
    audit("重置绑定码", "user", user_id, f"用户：{user['nickname']}")
    flash(f"新绑定码：{code}", "success")
    return redirect(url_for("user_detail", user_id=user_id))


@app.route("/bindings")
@admin_required
def bindings():
    rows = udb().execute("""
        SELECT sub.id,sub.nickname,sub.phone,sub.supervisee_code,sub.bound_to,
               sup.nickname AS supervisor_name,sup.phone AS supervisor_phone
        FROM users sub LEFT JOIN users sup ON sup.id=sub.bound_to
        WHERE sub.role='supervisee' ORDER BY sub.bound_to IS NULL DESC,sub.nickname
    """).fetchall()
    return render_template("bindings.html", bindings=rows)


@app.route("/diets")
@admin_required
def diets():
    query = request.args.get("q", "").strip()
    date = request.args.get("date", "").strip()
    sql = "SELECT dr.*,u.nickname,u.phone FROM diet_records dr JOIN users u ON u.id=dr.user_id WHERE 1=1"
    params = []
    if query:
        pattern = f"%{query}%"
        sql += " AND (u.nickname LIKE ? OR u.phone LIKE ? OR dr.food_name LIKE ?)"
        params.extend([pattern, pattern, pattern])
    if date:
        sql += " AND date(dr.intake_time)=?"
        params.append(date)
    sql += " ORDER BY dr.intake_time DESC LIMIT 500"
    rows = udb().execute(sql, params).fetchall()
    return render_template("diets.html", records=rows, query=query, date=date)


@app.route("/diets/<int:record_id>/delete", methods=["POST"])
@admin_required
def delete_diet(record_id):
    connection = udb()
    record = connection.execute("SELECT * FROM diet_records WHERE id=?", (record_id,)).fetchone()
    if not record:
        abort(404)
    connection.execute("DELETE FROM diet_records WHERE id=?", (record_id,))
    connection.commit()
    audit("删除饮食记录", "diet_record", record_id, f"{record['food_name']} / {record['calories']} kcal")
    flash("饮食记录已删除", "success")
    return redirect(request.referrer or url_for("diets"))


@app.route("/foods", methods=["GET", "POST"])
@admin_required
def foods():
    connection = udb()
    if request.method == "POST":
        food_id = request.form.get("food_id", "").strip()
        name = request.form.get("name", "").strip()
        category = request.form.get("category", "").strip()
        try:
            calories = float(request.form.get("calories", ""))
            sodium = float(request.form.get("sodium", "0") or 0)
            potassium = float(request.form.get("potassium", "0") or 0)
            calcium = float(request.form.get("calcium", "0") or 0)
            magnesium = float(request.form.get("magnesium", "0") or 0)
            iron = float(request.form.get("iron", "0") or 0)
        except ValueError:
            flash("营养数值格式不正确", "error")
            return redirect(url_for("foods"))
        if not name or not category or calories < 0 or any(v < 0 for v in (sodium, potassium, calcium, magnesium, iron)):
            flash("请填写有效的食物名称、分类和非负营养数值", "error")
            return redirect(url_for("foods"))
        values = (name, calories, category, sodium, potassium, calcium, magnesium, iron)
        try:
            if food_id:
                connection.execute(
                    "UPDATE food_library SET name=?,calories_per_100g=?,category=?,sodium_mg=?,potassium_mg=?,calcium_mg=?,magnesium_mg=?,iron_mg=? WHERE id=?",
                    values + (int(food_id),),
                )
                action = "修改食物"
            else:
                cursor = connection.execute(
                    "INSERT INTO food_library (name,calories_per_100g,category,sodium_mg,potassium_mg,calcium_mg,magnesium_mg,iron_mg) VALUES (?,?,?,?,?,?,?,?)",
                    values,
                )
                food_id = cursor.lastrowid
                action = "新增食物"
            connection.commit()
        except Exception as error:
            connection.rollback()
            flash(f"保存失败：{error}", "error")
            return redirect(url_for("foods"))
        audit(action, "food", food_id, name)
        flash("食物资料已保存", "success")
        return redirect(url_for("foods"))
    rows = [dict(row) for row in connection.execute("SELECT * FROM food_library ORDER BY category,name").fetchall()]
    return render_template("foods.html", foods=rows)


@app.route("/audit")
@admin_required
def audit_page():
    rows = adb().execute("SELECT * FROM audit_logs ORDER BY created_at DESC LIMIT 500").fetchall()
    return render_template("audit.html", logs=rows)


@app.errorhandler(FileNotFoundError)
def missing_user_database(error):
    return render_template("database_error.html", message=str(error)), 503


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5100, debug=False, use_reloader=False)
