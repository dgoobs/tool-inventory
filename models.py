import secrets
from datetime import datetime

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def generate_qr_token():
    return secrets.token_urlsafe(16)


class Tool(db.Model):
    """A single physical tool (e.g. 'Grinder #3')."""

    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(50), nullable=False)
    label = db.Column(db.String(80), nullable=False, unique=True)
    status = db.Column(db.String(20), nullable=False, default="in_shop")  # in_shop | checked_out
    current_employee = db.Column(db.String(120))
    current_van = db.Column(db.String(50))
    checked_out_at = db.Column(db.DateTime)
    # Random, unguessable -- printed as a QR code on the physical tool. This is the
    # only way to check a tool in or out, so checking one in requires having its tag.
    qr_token = db.Column(db.String(32), unique=True, default=generate_qr_token)

    def __repr__(self):
        return f"<Tool {self.label}>"


class CheckoutRecord(db.Model):
    """History of a single checkout/check-in cycle for a tool."""

    id = db.Column(db.Integer, primary_key=True)
    tool_id = db.Column(db.Integer, db.ForeignKey("tool.id"), nullable=False)
    tool = db.relationship("Tool", backref=db.backref("records", order_by="CheckoutRecord.checked_out_at.desc()"))
    employee_name = db.Column(db.String(120), nullable=False)
    van_number = db.Column(db.String(50), nullable=False)
    checked_out_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    checked_in_at = db.Column(db.DateTime)
