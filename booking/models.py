from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
import uuid


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    phone = models.CharField(max_length=20, unique=True)
    email = models.EmailField(unique=True, null=True, blank=True)
    is_email_verified = models.BooleanField(default=False)
    register_time = models.DateTimeField(null=True, blank=True)
    risk_locked_until = models.DateTimeField(null=True, blank=True)
    risk_reset_at = models.DateTimeField(null=True, blank=True)


class EmailVerifyToken(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    token = models.UUIDField(default=uuid.uuid4, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_used = models.BooleanField(default=False)

    def is_expired(self):
        return timezone.now() > self.created_at + timedelta(minutes=10)


class Car(models.Model):
    TYPE_CHOICES = (
        ("4人座", "4人座"),
        ("10人座", "10人座"),
    )

    name = models.CharField(max_length=50)
    plate = models.CharField(max_length=20)
    type = models.CharField(
        max_length=10,
        choices=TYPE_CHOICES,
        null=True,      # 👈 加這個
        blank=True      # 👈 加這個
    )

    def __str__(self):
        return f"{self.name} ({self.plate})"


class Reservation(models.Model):
    user = models.ForeignKey("auth.User", on_delete=models.CASCADE)
    car = models.ForeignKey(Car, on_delete=models.CASCADE)

    created_at = models.DateTimeField(auto_now_add=True)
    start_time = models.DateTimeField(null=True, blank=True)
    end_time = models.DateTimeField(null=True, blank=True)

    checkIn_time = models.DateTimeField(null=True, blank=True)
    return_time = models.DateTimeField(null=True, blank=True)

    status = models.CharField(
        max_length=10,
        choices=[
            ("on-going", "尚未還車"),
            ("completed", "已完成"),
            ("cancelled", "已取消"),
            ("no-checkIn", "未報到取消"),
            ("pending", "未報到"),
        ],
        default="pending"
    )

    def __str__(self):
        return f"{self.user} - {self.car}"
