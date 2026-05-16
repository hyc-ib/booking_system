# booking/migrations/0001_initial.py

from django.db import migrations, models
import django.db.models.deletion
import uuid
from django.conf import settings

class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [

        # =======================
        # Car
        # =======================
        migrations.CreateModel(
            name='Car',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=50)),
                ('plate', models.CharField(max_length=20)),
                ('type', models.CharField(
                    max_length=10,
                    choices=[('4人座', '4人座'), ('10人座', '10人座')],
                    default='4人座'
                )),
            ],
        ),

        # =======================
        # Profile
        # =======================
        migrations.CreateModel(
            name='Profile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('phone', models.CharField(max_length=20, unique=True)),
                ('email', models.EmailField(blank=True, null=True, unique=True)),
                ('is_email_verified', models.BooleanField(default=False)),
                ('user', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    to=settings.AUTH_USER_MODEL
                )),
            ],
        ),

        # =======================
        # EmailVerifyToken
        # =======================
        migrations.CreateModel(
            name='EmailVerifyToken',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('token', models.UUIDField(default=uuid.uuid4, unique=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('is_used', models.BooleanField(default=False)),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    to=settings.AUTH_USER_MODEL
                )),
            ],
        ),

        # =======================
        # Reservation
        # =======================
        migrations.CreateModel(
            name='Reservation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('start_time', models.DateTimeField()),
                ('end_time', models.DateTimeField()),
                ('status', models.CharField(
                    max_length=10,
                    choices=[
                        ('on-going', '尚未還車'),
                        ('completed', '已完成'),
                        ('cancelled', '已取消'),
                        ('pending', '未報到'),
                    ],
                    default='pending'
                )),
                ('car', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    to='booking.Car'
                )),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    to=settings.AUTH_USER_MODEL
                )),
            ],
        ),
    ]