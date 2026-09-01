import io
import os
import re
from datetime import datetime

import qrcode
import qrcode.image.svg
from flask import Flask, Response, flash, redirect, render_template, request, session, url_for
from sqlalchemy import inspect, text

from models import CheckoutRecord, Tool, db, generate_qr_token

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

DEFAULT_TOOLS = [
    ("Grinder", 10),
    ("Sawzall", 5),
    ("Zoom Lock", 2),
]

EMPLOYEE_NAME_MAX_LEN = 10
VAN_NUMBER_MAX_LEN = 3
VAN_NUMBER_RE = re.compile(r"^[0-9]+$")


def create_app():
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{os.path.join(BASE_DIR, 'inventory.db')}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")
    app.config["SHOP_PASSWORD"] = os.environ.get("SHOP_PASSWORD")  # None disables the login gate
    app.config["ADMIN_PASSWORD"] = os.environ.get("ADMIN_PASSWORD")  # unlocks manual overrides

    db.init_app(app)

    with app.app_context():
        db.create_all()
        ensure_qr_tokens()
        ensure_manual_column()
        seed_tools()

    register_routes(app)
    return app


def seed_tools():
    """Populate the shop's starting tool list the first time the app runs."""
    if Tool.query.count() > 0:
        return
    for category, count in DEFAULT_TOOLS:
        for i in range(1, count + 1):
            db.session.add(Tool(category=category, label=f"{category} #{i}"))
    db.session.commit()


def ensure_qr_tokens():
    """Add the qr_token column/index and backfill tokens if this DB predates QR codes."""
    inspector = inspect(db.engine)
    if "tool" not in inspector.get_table_names():
        return  # fresh DB -- db.create_all() above already made the column

    columns = [c["name"] for c in inspector.get_columns("tool")]
    if "qr_token" not in columns:
        db.session.execute(text("ALTER TABLE tool ADD COLUMN qr_token VARCHAR(32)"))
        db.session.commit()

    for tool in Tool.query.filter(Tool.qr_token.is_(None)).all():
        tool.qr_token = generate_qr_token()
    db.session.commit()

    db.session.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_tool_qr_token ON tool (qr_token)"))
    db.session.commit()


def ensure_manual_column():
    """Add checkout_record.is_manual if this DB predates admin overrides."""
    inspector = inspect(db.engine)
    if "checkout_record" not in inspector.get_table_names():
        return  # fresh DB -- db.create_all() above already made the column

    columns = [c["name"] for c in inspector.get_columns("checkout_record")]
    if "is_manual" not in columns:
        db.session.execute(
            text("ALTER TABLE checkout_record ADD COLUMN is_manual BOOLEAN NOT NULL DEFAULT 0")
        )
        db.session.commit()


def register_routes(app):
    def is_admin():
        if not app.config["SHOP_PASSWORD"]:
            return True  # no password configured (e.g. local dev) -- everything's open
        return session.get("role") == "admin"

    @app.context_processor
    def inject_is_admin():
        return {"is_admin": is_admin()}

    @app.before_request
    def require_login():
        if not app.config["SHOP_PASSWORD"]:
            return  # no password configured (e.g. local dev) -- gate disabled
        if request.endpoint in ("login", "static"):
            return
        if not session.get("authed"):
            return redirect(url_for("login", next=request.path))

    def require_admin():
        if not is_admin():
            flash("That action needs the admin password.", "error")
            return redirect(url_for("dashboard"))
        return None

    @app.route("/login", methods=["GET", "POST"])
    def login():
        error = None
        if request.method == "POST":
            submitted = request.form.get("password")
            admin_password = app.config["ADMIN_PASSWORD"]
            if admin_password and submitted == admin_password:
                session["authed"] = True
                session["role"] = "admin"
                return redirect(request.args.get("next") or url_for("dashboard"))
            elif submitted == app.config["SHOP_PASSWORD"]:
                session["authed"] = True
                session["role"] = "staff"
                return redirect(request.args.get("next") or url_for("dashboard"))
            error = "Incorrect password."
        return render_template("login.html", error=error)

    @app.route("/logout")
    def logout():
        session.pop("authed", None)
        session.pop("role", None)
        return redirect(url_for("login"))

    @app.route("/")
    def dashboard():
        status_filter = request.args.get("status")  # None | in_shop | checked_out
        tools = Tool.query.order_by(Tool.category, Tool.label).all()

        categories = {}
        for t in tools:
            categories.setdefault(t.category, []).append(t)

        summary = {
            cat: {
                "total": len(items),
                "in_shop": sum(1 for t in items if t.status == "in_shop"),
                "checked_out": sum(1 for t in items if t.status == "checked_out"),
            }
            for cat, items in categories.items()
        }

        if status_filter in ("in_shop", "checked_out"):
            categories = {
                cat: [t for t in items if t.status == status_filter]
                for cat, items in categories.items()
            }
            categories = {cat: items for cat, items in categories.items() if items}

        totals = {
            "total": len(tools),
            "in_shop": sum(1 for t in tools if t.status == "in_shop"),
            "checked_out": sum(1 for t in tools if t.status == "checked_out"),
        }

        return render_template(
            "dashboard.html",
            categories=categories,
            summary=summary,
            totals=totals,
            status_filter=status_filter,
        )

    @app.route("/t/<token>", methods=["GET", "POST"])
    def scan(token):
        """The only place a tool's status can change -- reached by scanning its
        physical QR tag. There's no dashboard button that does this, so a tool
        can't be marked checked in (or out) without whoever's doing it actually
        having the tag in hand."""
        tool = Tool.query.filter_by(qr_token=token).first_or_404()

        if request.method == "POST":
            if tool.status == "in_shop":
                employee = request.form.get("employee_name", "").strip()
                van = request.form.get("van_number", "").strip()

                error = validate_checkout_fields(employee, van)
                if error:
                    flash(error, "error")
                    return render_template("scan.html", tool=tool, **pick_lists())

                perform_checkout(tool, employee, van)
                flash(f"{tool.label} checked out to {employee} (Van {van}).", "success")
            else:
                perform_checkin(tool)
                flash(f"{tool.label} checked back in.", "success")

            return redirect(url_for("scan", token=token))

        return render_template("scan.html", tool=tool, **pick_lists())

    @app.route("/tools/<int:tool_id>/manual-checkout", methods=["GET", "POST"])
    def manual_checkout(tool_id):
        """Admin-only override for when a tool's QR tag is lost/damaged."""
        redirect_response = require_admin()
        if redirect_response:
            return redirect_response

        tool = Tool.query.get_or_404(tool_id)
        if tool.status == "checked_out":
            flash(f"{tool.label} is already checked out.", "error")
            return redirect(url_for("dashboard"))

        if request.method == "POST":
            employee = request.form.get("employee_name", "").strip()
            van = request.form.get("van_number", "").strip()

            error = validate_checkout_fields(employee, van)
            if error:
                flash(error, "error")
                return render_template("scan.html", tool=tool, manual=True, **pick_lists())

            perform_checkout(tool, employee, van, manual=True)
            flash(f"{tool.label} manually checked out to {employee} (Van {van}).", "success")
            return redirect(url_for("dashboard"))

        return render_template("scan.html", tool=tool, manual=True, **pick_lists())

    @app.route("/tools/<int:tool_id>/manual-checkin", methods=["POST"])
    def manual_checkin(tool_id):
        """Admin-only override for when a tool's QR tag is lost/damaged."""
        redirect_response = require_admin()
        if redirect_response:
            return redirect_response

        tool = Tool.query.get_or_404(tool_id)
        if tool.status == "in_shop":
            flash(f"{tool.label} is already in the shop.", "error")
        else:
            perform_checkin(tool, manual=True)
            flash(f"{tool.label} manually checked back in.", "success")
        return redirect(url_for("dashboard"))

    @app.route("/tools/<int:tool_id>/edit", methods=["GET", "POST"])
    def edit_checkout(tool_id):
        """Admin-only: fix a typo'd employee name or van number on a tool
        that's currently checked out, without a full check-in/out cycle."""
        redirect_response = require_admin()
        if redirect_response:
            return redirect_response

        tool = Tool.query.get_or_404(tool_id)
        if tool.status == "in_shop":
            flash(f"{tool.label} is in the shop -- nothing to edit.", "error")
            return redirect(url_for("dashboard"))

        if request.method == "POST":
            employee = request.form.get("employee_name", "").strip()
            van = request.form.get("van_number", "").strip()

            error = validate_checkout_fields(employee, van)
            if error:
                flash(error, "error")
                return render_template("edit_checkout.html", tool=tool, **pick_lists())

            tool.current_employee = employee
            tool.current_van = van
            open_record = (
                CheckoutRecord.query.filter_by(tool_id=tool.id, checked_in_at=None)
                .order_by(CheckoutRecord.checked_out_at.desc())
                .first()
            )
            if open_record:
                open_record.employee_name = employee
                open_record.van_number = van
                open_record.is_manual = True
            db.session.commit()
            flash(f"{tool.label}'s checkout details were updated.", "success")
            return redirect(url_for("dashboard"))

        return render_template("edit_checkout.html", tool=tool, **pick_lists())

    @app.route("/tools/<int:tool_id>/qr")
    def tool_qr(tool_id):
        tool = Tool.query.get_or_404(tool_id)
        scan_url = url_for("scan", token=tool.qr_token, _external=True)
        return render_template("tool_qr.html", tool=tool, scan_url=scan_url)

    @app.route("/tools/<int:tool_id>/qr.svg")
    def tool_qr_svg(tool_id):
        tool = Tool.query.get_or_404(tool_id)
        scan_url = url_for("scan", token=tool.qr_token, _external=True)
        svg = render_qr_svg(scan_url)
        return Response(svg, mimetype="image/svg+xml")

    @app.route("/qr")
    def qr_codes():
        tools = Tool.query.order_by(Tool.category, Tool.label).all()
        return render_template("qr_codes.html", tools=tools)

    @app.route("/tools/new", methods=["GET", "POST"])
    def new_tool():
        if request.method == "POST":
            category = request.form.get("category", "").strip()
            label = request.form.get("label", "").strip()
            if not category or not label:
                flash("Category and tool name are both required.", "error")
            elif Tool.query.filter_by(label=label).first():
                flash(f"A tool named '{label}' already exists.", "error")
            else:
                db.session.add(Tool(category=category, label=label))
                db.session.commit()
                flash(f"Added {label}.", "success")
                return redirect(url_for("dashboard"))

        categories = sorted({row[0] for row in db.session.query(Tool.category).distinct()})
        return render_template("new_tool.html", categories=categories)

    @app.route("/history")
    def history():
        records = (
            CheckoutRecord.query.order_by(CheckoutRecord.checked_out_at.desc()).limit(200).all()
        )
        return render_template("history.html", records=records)

    def pick_lists():
        """Recent employee names / van numbers, for autocomplete on the checkout form."""
        employees = [
            r[0]
            for r in db.session.query(CheckoutRecord.employee_name)
            .distinct()
            .order_by(CheckoutRecord.employee_name)
            .all()
        ]
        vans = [
            r[0]
            for r in db.session.query(CheckoutRecord.van_number)
            .distinct()
            .order_by(CheckoutRecord.van_number)
            .all()
        ]
        return {"employees": employees, "vans": vans}


def validate_checkout_fields(employee, van):
    """Returns an error string, or None if the fields are OK to save."""
    if not employee or not van:
        return "Employee name and van number are both required."
    if len(employee) > EMPLOYEE_NAME_MAX_LEN:
        return f"Employee name must be {EMPLOYEE_NAME_MAX_LEN} characters or fewer."
    if not VAN_NUMBER_RE.match(van):
        return "Van number must contain only numbers."
    if len(van) > VAN_NUMBER_MAX_LEN:
        return f"Van number must be {VAN_NUMBER_MAX_LEN} digits or fewer."
    return None


def perform_checkout(tool, employee, van, manual=False):
    now = datetime.utcnow()
    tool.status = "checked_out"
    tool.current_employee = employee
    tool.current_van = van
    tool.checked_out_at = now
    db.session.add(
        CheckoutRecord(
            tool_id=tool.id,
            employee_name=employee,
            van_number=van,
            checked_out_at=now,
            is_manual=manual,
        )
    )
    db.session.commit()


def perform_checkin(tool, manual=False):
    open_record = (
        CheckoutRecord.query.filter_by(tool_id=tool.id, checked_in_at=None)
        .order_by(CheckoutRecord.checked_out_at.desc())
        .first()
    )
    if open_record:
        open_record.checked_in_at = datetime.utcnow()
        if manual:
            open_record.is_manual = True

    tool.status = "in_shop"
    tool.current_employee = None
    tool.current_van = None
    tool.checked_out_at = None
    db.session.commit()


def render_qr_svg(data):
    img = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode("utf-8")


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
