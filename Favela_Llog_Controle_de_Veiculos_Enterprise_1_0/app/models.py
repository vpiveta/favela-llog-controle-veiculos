from datetime import date, datetime
from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(160))
    phone = db.Column(db.String(30))
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='DRIVER')
    active = db.Column(db.Boolean, default=True, nullable=False)
    must_change_password = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    vehicle = db.relationship('Vehicle', back_populates='driver', uselist=False)

    def set_password(self, password): self.password_hash = generate_password_hash(password)
    def check_password(self, password): return check_password_hash(self.password_hash, password)
    @property
    def is_admin(self): return self.role == 'ADMIN'

class Vehicle(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    plate = db.Column(db.String(10), unique=True, nullable=False, index=True)
    brand = db.Column(db.String(80), nullable=False)
    model = db.Column(db.String(100), nullable=False)
    year = db.Column(db.Integer)
    current_km = db.Column(db.Integer, default=0)
    status = db.Column(db.String(30), default='AVAILABLE')
    photo = db.Column(db.String(255))
    driver_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True)
    driver = db.relationship('User', back_populates='vehicle')
    expenses = db.relationship('Expense', back_populates='vehicle', cascade='all, delete-orphan')
    oil_changes = db.relationship('OilChange', back_populates='vehicle', cascade='all, delete-orphan')

class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    expense_type = db.Column(db.String(20), nullable=False)  # FUEL / MAINTENANCE
    expense_date = db.Column(db.Date, nullable=False, default=date.today)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    odometer = db.Column(db.Integer)
    receipt_path = db.Column(db.String(255), nullable=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicle.id'), nullable=False)
    created_by = db.relationship('User')
    vehicle = db.relationship('Vehicle', back_populates='expenses')
    fuel = db.relationship('FuelDetail', back_populates='expense', uselist=False, cascade='all, delete-orphan')
    maintenance = db.relationship('MaintenanceDetail', back_populates='expense', uselist=False, cascade='all, delete-orphan')

class FuelDetail(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    liters = db.Column(db.Numeric(10, 2))
    fuel_type = db.Column(db.String(30), default='GASOLINE')
    station = db.Column(db.String(160))
    expense_id = db.Column(db.Integer, db.ForeignKey('expense.id'), unique=True, nullable=False)
    expense = db.relationship('Expense', back_populates='fuel')

class MaintenanceDetail(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    start_date = db.Column(db.Date, nullable=False)
    same_day = db.Column(db.Boolean, default=True)
    end_date = db.Column(db.Date)
    description = db.Column(db.Text, nullable=False)
    workshop = db.Column(db.String(160))
    status = db.Column(db.String(30), default='COMPLETED')
    expense_id = db.Column(db.Integer, db.ForeignKey('expense.id'), unique=True, nullable=False)
    expense = db.relationship('Expense', back_populates='maintenance')

class OilChange(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    change_date = db.Column(db.Date, nullable=False)
    odometer = db.Column(db.Integer, nullable=False)
    next_change_km = db.Column(db.Integer, nullable=False)
    next_change_date = db.Column(db.Date)
    oil_type = db.Column(db.String(100))
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicle.id'), nullable=False)
    expense_id = db.Column(db.Integer, db.ForeignKey('expense.id'))
    vehicle = db.relationship('Vehicle', back_populates='oil_changes')

class AlertRecipient(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(160), nullable=False)
    active = db.Column(db.Boolean, default=True)
