import os
from datetime import datetime
from functools import wraps

from flask import Flask, flash, redirect, render_template, request, session, url_for

from models import CheckoutRecord, Tool, db

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

DEFAULT_TOOLS = [
    ("Grinder", 10),
    ("Sawzall", 5),
    ("Zoom Lock", 2),
]


def create_app():
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{os.path.join(BASE_DIR, 'inventory.db')}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")
    app.config["SHOP_PASSWORD"] = os.environ.get("SHOP_PASSWORD")  # None disables the login gate

    db.init_app(app)

    with app.app_context():
        db.create_all()
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


def register_routes(app):
    @app.before_request
    def require_login():
        if not app.config["SHOP_PASSWORD"]:
            return  # no password configured (e.g. local dev) -- gate disabled
        if request.endpoint in ("login", "static"):
            return
        if not session.get("authed"):
            return redirect(url_for("login", next=request.path))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        error = None
        if request.method == "POST":
            if request.form.get("password") == app.config["SHOP_PASSWORD"]:
                session["authed"] = True
                return redirect(request.args.get("next") or url_for("dashboard"))
            error = "Incorrect password."
        return render_template("login.html", error=error)

    @app.route("/logout")
    def logout():
        session.pop("authed", None)
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

    @app.route("/checkout/<int:tool_id>", methods=["GET", "POST"])
    def checkout(tool_id):
        tool = Tool.query.get_or_404(tool_id)
        if tool.status == "checked_out":
            flash(f"{tool.label} is already checked out.", "error")
            return redirect(url_for("dashboard"))

        if request.method == "POST":
            employee = request.form.get("employee_name", "").strip()
            van = request.form.get("van_number", "").strip()
            if not employee or not van:
                flash("Employee name and van number are both required.", "error")
                return render_template("checkout.html", tool=tool, **pick_lists())

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
                )
            )
            db.session.commit()
            flash(f"{tool.label} checked out to {employee} (Van {van}).", "success")
            return redirect(url_for("dashboard"))

        return render_template("checkout.html", tool=tool, **pick_lists())

    @app.route("/checkin/<int:tool_id>", methods=["POST"])
    def checkin(tool_id):
        tool = Tool.query.get_or_404(tool_id)
        if tool.status == "in_shop":
            flash(f"{tool.label} is already in the shop.", "error")
            return redirect(url_for("dashboard"))

        open_record = (
            CheckoutRecord.query.filter_by(tool_id=tool.id, checked_in_at=None)
            .order_by(CheckoutRecord.checked_out_at.desc())
            .first()
        )
        if open_record:
            open_record.checked_in_at = datetime.utcnow()

        tool.status = "in_shop"
        tool.current_employee = None
        tool.current_van = None
        tool.checked_out_at = None
        db.session.commit()
        flash(f"{tool.label} checked back in.", "success")
        return redirect(url_for("dashboard"))

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

        categories = sorted({t.category for t, in db.session.query(Tool.category).distinct()})
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


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
