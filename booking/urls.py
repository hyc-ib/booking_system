from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.login_page, name='login'),
    path('send_otp/', views.send_otp),
    path('verify_otp/', views.verify_otp),
    path('register/', views.register, name='register'),
    path("verify_email/", views.verify_email),
    path("check_email/", views.check_email_page),
    path('reserve/', views.reserve_step1, name='reserve_step1'),
    path('reserve/time/', views.reserve_step2, name='reserve_step2'),
    path("reserve/success/", views.reserve_success, name="reserve_success"),
]