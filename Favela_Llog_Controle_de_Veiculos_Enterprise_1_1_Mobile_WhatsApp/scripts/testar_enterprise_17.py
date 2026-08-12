"""Homologação isolada da versão 1.7, sem tocar no banco operacional."""

import io
import os
import tempfile
from datetime import timedelta
from pathlib import Path

fd, database_path = tempfile.mkstemp(prefix="favela_fleet_17_", suffix=".db")
os.close(fd)
os.environ["DATABASE_URL"] = f"sqlite:///{Path(database_path).as_posix()}"
os.environ["SECRET_KEY"] = "homologacao-enterprise-17"
os.environ.pop("SUPABASE_URL", None)
os.environ.pop("SUPABASE_SERVICE_ROLE_KEY", None)

from app import create_app
from app.models import (
    AdminNotification,
    DailyChecklist,
    Expense,
    MaintenanceDetail,
    OilChange,
    StoredFile,
    User,
    Vehicle,
    db,
)
from app.routes import build_oil_statuses
from app.time_utils import local_today


def photo(name):
    return io.BytesIO(b"arquivo-de-homologacao"), name


app = create_app()
app.config.update(TESTING=True)

try:
    with app.app_context():
        admin = User(name="ADM Homologação", username="adm17", role="ADMIN", active=True)
        admin.set_password("123456")
        driver = User(name="Motorista Homologação", username="motorista17", role="DRIVER", active=True)
        driver.set_password("123456")
        db.session.add_all([admin, driver])
        db.session.flush()

        motorcycle = Vehicle(
            plate="MOT1A17", brand="Honda", model="CG", current_km=1000,
            vehicle_type="MOTORCYCLE", driver_id=driver.id,
        )
        car = Vehicle(
            plate="CAR1A17", brand="Fiat", model="Strada", current_km=5000,
            vehicle_type="CAR",
        )
        db.session.add_all([motorcycle, car])
        db.session.commit()
        admin_id, driver_id = admin.id, driver.id
        motorcycle_id, car_id = motorcycle.id, car.id

    client = app.test_client()
    login = client.post("/login", data={"username": "motorista17", "password": "123456"})
    assert login.status_code == 302

    today = local_today()
    missing_plate = client.post(
        "/fuel/new",
        data={
            "vehicle_type": "CAR",
            "car_vehicle_id": str(car_id),
            "authorized_by_id": str(admin_id),
            "expense_date": today.isoformat(),
            "odometer": "5050",
            "amount": "150,00",
            "receipt": photo("nota-sem-placa.jpg"),
        },
        content_type="multipart/form-data",
    )
    assert missing_plate.status_code == 200
    assert "foto da placa" in missing_plate.get_data(as_text=True).lower()
    with app.app_context():
        assert Expense.query.filter_by(asset_type="CAR").count() == 0

    car_fuel = client.post(
        "/fuel/new",
        data={
            "vehicle_type": "CAR",
            "car_vehicle_id": str(car_id),
            "authorized_by_id": str(admin_id),
            "expense_date": today.isoformat(),
            "odometer": "5050",
            "amount": "150,00",
            "liters": "20,00",
            "station": "Posto Teste",
            "receipt": photo("nota-carro.jpg"),
            "plate_photo": photo("placa-carro.jpg"),
        },
        content_type="multipart/form-data",
    )
    assert car_fuel.status_code == 302

    maintenance = client.post(
        "/maintenance/new",
        data={
            "start_date": today.isoformat(),
            "end_date": (today + timedelta(days=2)).isoformat(),
            "status": "IN_PROGRESS",
            "amount": "250,00",
            "odometer": "1000",
            "workshop": "Oficina Teste",
            "description": "Revisão e troca de óleo",
            "is_oil_change": "on",
            "oil_type": "10W30",
            "oil_amount": "80,00",
            "receipt": photo("nota-moto.jpg"),
        },
        content_type="multipart/form-data",
    )
    assert maintenance.status_code == 302

    with app.app_context():
        car_expense = Expense.query.filter_by(asset_type="CAR").one()
        car_expense_id = car_expense.id
        assert car_expense.amount == 150
        assert car_expense.authorized_by_id == admin_id
        assert car_expense.vehicle_id == car_id

        motorcycle_expense = Expense.query.filter_by(asset_type="MOTORCYCLE", expense_type="MAINTENANCE").one()
        assert motorcycle_expense.amount == 250
        assert motorcycle_expense.maintenance.is_oil_change is True
        assert motorcycle_expense.maintenance.oil_amount == 80
        assert motorcycle_expense.vehicle.status == "MAINTENANCE"

        car_file = StoredFile.query.filter_by(
            entity_type="CAR_EXPENSE", entity_id=car_expense.id,
            category="CAR_FUEL_RECEIPT",
        ).one()
        plate_file = StoredFile.query.filter_by(
            entity_type="CAR_EXPENSE", entity_id=car_expense.id,
            category="CAR_PLATE_PHOTO",
        ).one()
        motorcycle_file = StoredFile.query.filter_by(entity_type="MOTORCYCLE_EXPENSE", entity_id=motorcycle_expense.id).one()
        assert car_file.category == "CAR_FUEL_RECEIPT"
        assert plate_file.category == "CAR_PLATE_PHOTO"
        assert motorcycle_file.category == "MOTORCYCLE_RECEIPT"

        oil_change = OilChange.query.filter_by(expense_id=motorcycle_expense.id).one()
        checklist = DailyChecklist(
            checklist_date=today, checklist_type="RETIRADA", driver_id=driver_id,
            vehicle_id=motorcycle_id, owner_driver_id=driver_id, borrowed_vehicle=False,
            odometer=1205, tires_ok=True, brakes_ok=True, lights_ok=True,
            indicators_ok=True, mirrors_ok=True, horn_ok=True, chain_ok=True,
            charger_ok=True, phone_holder_ok=True, top_case_ok=True,
            saddlebags_ok=True, general_condition="GOOD", has_damage=False,
            status="COMPLETED", share_token="homologacao-enterprise-17",
        )
        db.session.add(checklist)
        db.session.commit()

        oil_status = build_oil_statuses(motorcycle_id)[0]
        assert oil_status["base_km"] == oil_change.odometer == 1000
        assert oil_status["traveled_km"] == 205
        assert oil_status["remaining_km"] == 785
        assert AdminNotification.query.filter_by(notification_type="CAR_FUEL").count() == 1

    client.get("/logout")
    client.post("/login", data={"username": "adm17", "password": "123456"})
    dashboard = client.get("/")
    history = client.get("/history")
    vehicles = client.get("/admin/vehicles")
    plate_photo = client.get(f"/expense/{car_expense_id}/plate-photo")
    assert dashboard.status_code == history.status_code == vehicles.status_code == 200
    assert plate_photo.status_code == 200
    assert b"150,00" in dashboard.data
    assert b"80,00" in dashboard.data
    assert b"ADM Homologa" in history.data
    assert b"Motos em manuten" in dashboard.data

    with app.app_context():
        maintenance_expense_id = Expense.query.filter_by(
            asset_type="MOTORCYCLE", expense_type="MAINTENANCE"
        ).one().id
    completed = client.post(
        f"/admin/maintenance/{maintenance_expense_id}/complete",
        data={"end_date": (today + timedelta(days=1)).isoformat()},
    )
    assert completed.status_code == 302
    with app.app_context():
        completed_expense = db.session.get(Expense, maintenance_expense_id)
        assert completed_expense.maintenance.status == "COMPLETED"
        assert completed_expense.vehicle.status == "AVAILABLE"

    print("OK: Enterprise 1.7 validada em banco temporario.")
finally:
    with app.app_context():
        db.session.remove()
        db.engine.dispose()
    Path(database_path).unlink(missing_ok=True)
