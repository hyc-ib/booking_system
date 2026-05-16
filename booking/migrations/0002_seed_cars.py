# booking/migrations/0002_seed_cars.py

from django.db import migrations

def seed_cars(apps, schema_editor):
    Car = apps.get_model("booking", "Car")

    # 防止重複建立
    if Car.objects.exists():
        return

    cars = []

    # ======================
    # 4人座
    # ======================
    for i in range(1, 7):
        cars.append(Car(
            name=f"4Car_{i}",
            plate=f"4CAR-{i:03d}",
            type="4人座"
        ))

    # ======================
    # 10人座
    # ======================
    for i in range(1, 5):
        cars.append(Car(
            name=f"10Car_{i}",
            plate=f"10CAR-{i:03d}",
            type="10人座"
        ))

    Car.objects.bulk_create(cars)


def unseed_cars(apps, schema_editor):
    Car = apps.get_model("booking", "Car")
    Car.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('booking', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_cars, reverse_code=unseed_cars),
    ]