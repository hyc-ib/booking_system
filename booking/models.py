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

    start_time = models.DateTimeField()
    end_time = models.DateTimeField()

    is_checked_in = models.BooleanField(default=False)
    is_returned = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.user} - {self.car}"