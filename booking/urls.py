from django.urls import path
from . import views

urlpatterns = [
    path('set-timezone/', views.set_timezone),
    path('home/', views.home, name='home'),
    path('login/', views.login_page, name='login'),
    path('send_otp/', views.send_otp),
    path('get-csrf-token/', views.get_csrf_token),
    path('verify_otp/', views.verify_otp),
    path('register/', views.register, name='register'),
    path("verify_email/", views.verify_email),
    path("check_email/", views.check_email_page),
    path('reserve/', views.reserve_step1, name='reserve_step1'),
    path('reserve/time/', views.reserve_step2, name='reserve_step2'),
    path("reserve/success/", views.reserve_success, name="reserve_success"),
    path('checkin/', views.checkin_list, name='checkin_list'),
    path('return/', views.return_list, name='return_list'),
    path('history/', views.history_list, name='history_list'),
    path('edit/<int:reservation_id>/', views.edit_reservation, name='edit_reservation'),
    path("profile/", views.profile, name="profile"),
]