import random
import re
from datetime import datetime
from django.core.cache import cache
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.http import JsonResponse, HttpResponse
from django.contrib.auth import login
from django.contrib.auth.models import User
from django.shortcuts import render, redirect
from .models import Car, Reservation, Profile, EmailVerifyToken
from django.core.mail import send_mail
from django.utils.crypto import get_random_string
from django.db.models import Q


# 👉 用記憶體暫存（開發用）
otp_store = {}

def login_page(request):
    return render(request, "registration/login.html")

# 📩 發送 OTP
def send_otp(request):
    phone = request.POST.get("phone").strip()

    otp = str(random.randint(100000, 999999))
    otp_store[phone] = otp

    print(f"[OTP] {phone}: {otp}")

    return JsonResponse({"status": "ok"})

# 🔐 驗證 OTP
def verify_otp(request):
    phone = request.POST.get("phone").strip()
    otp = request.POST.get("otp").strip()

    if otp_store.get(phone) != otp:
        return JsonResponse({"status": "fail"})

    try:
        profile = Profile.objects.get(phone=phone)

        # ✔ 已註冊 → 直接登入 + 去 reserve
        login(request, profile.user)

        return JsonResponse({
            "status": "login_success",
            "redirect": "/reserve/"
        })

    except Profile.DoesNotExist:
        request.session["register_phone"] = phone
        return JsonResponse({"status": "need_register"})
    
    
# 📝 註冊頁
def register(request):
    phone = request.session.get("register_phone")

    if request.method == "POST":
        name = request.POST.get("name")
        email = request.POST.get("email")

        if Profile.objects.filter(email=email).exists():
            return render(request, "booking/register.html", {
                "phone": phone,
                "error": "這個 Email 已經被註冊過了"
            })

        user = User.objects.create(username=name, email=email)

        token = get_random_string(32)

        Profile.objects.create(
            user=user,
            phone=phone,
            email=email,
            is_email_verified=False
        )

        token_obj = EmailVerifyToken.objects.create(user=user)
        request.session["verify_user_id"] = user.id

        # 發送驗證信
        verify_link = f"http://127.0.0.1:8000/check_email/?token={token_obj.token}"

        send_mail(
            "請驗證你的信箱",
            f"點擊以下連結完成驗證：\n{verify_link}",
            None,
            [email],
        )

        return render(request, "booking/check_email.html")

    return render(request, "booking/register.html", {"phone": phone})


def verify_email(request):
    token = request.GET.get("token")

    try:
        token_obj = EmailVerifyToken.objects.get(token=token)
    except EmailVerifyToken.DoesNotExist:
        return JsonResponse({"status": "fail", "msg": "token invalid"})

    # ❌ 已使用
    if token_obj.is_used:
        return JsonResponse({"status": "fail", "msg": "already used"})

    # ❌ 過期
    if token_obj.is_expired():
        return JsonResponse({"status": "fail", "msg": "token expired"})

    # ✅ 標記使用
    token_obj.is_used = True
    token_obj.save()

    # 啟用帳號
    profile = Profile.objects.get(user=token_obj.user)
    profile.is_email_verified = True
    profile.save()

    login(request, token_obj.user)

    return JsonResponse({
        "status": "success",
        "redirect": "/reserve/"
    })

def check_email_page(request):
    return render(request, "booking/check_email.html")

def home(request):
    return render(request, "booking/home.html")

def is_conflict(start1, end1, start2, end2):
    return not (end1 <= start2 or start1 >= end2)


@login_required
def reserve_step1(request):

    if request.method == "POST":
        car_type = request.POST.get("car_type")

        if not car_type:
            return render(request, "booking/reserve_step1.html", {
                "error": "請選擇車型"
            })

        request.session["car_type"] = car_type

        request.session.pop("car_id", None)
        request.session.pop("start_time", None)
        request.session.pop("end_time", None)

        return redirect("reserve_step2")

    return render(request, "booking/reserve_step1.html")


@login_required
def reserve_step2(request):

    car_type = request.session.get("car_type")

    if not car_type:
        return redirect("reserve_step1")

    car_prefix = "4Car" if car_type == "4人座" else "10Car"
    cars = Car.objects.filter(name__startswith=car_prefix)

    if request.method == "POST":

        start_hour = int(request.POST.get("start_hour"))
        start_minute = int(request.POST.get("start_minute"))
        end_hour = int(request.POST.get("end_hour"))
        end_minute = int(request.POST.get("end_minute"))

        start_time = start_hour * 60 + start_minute
        end_time = end_hour * 60 + end_minute

        selected_car = None

        for car in cars:

            reservations = Reservation.objects.filter(car=car)

            conflict = False

            for r in reservations:
                r_start = r.start_time.hour * 60 + r.start_time.minute
                r_end = r.end_time.hour * 60 + r.end_time.minute

                if is_conflict(start_time, end_time, r_start, r_end):
                    conflict = True
                    break

            if not conflict:
                selected_car = car
                break

        if not selected_car:
            return render(request, "booking/reserve_step2.html", {
                "car_type": car_type,
                "range_0_24": range(24),
                "error": "目前無可用車輛"
            })

        # ✅ 建立 reservation
        Reservation.objects.create(
            user=request.user,
            car=selected_car,
            start_time=datetime(2026, 1, 1, start_hour, start_minute),
            end_time=datetime(2026, 1, 1, end_hour, end_minute),
        )

        request.session["car_id"] = selected_car.id
        request.session["start_time"] = f"{start_hour:02d}:{start_minute:02d}"
        request.session["end_time"] = f"{end_hour:02d}:{end_minute:02d}"

        return redirect("reserve_success")

    return render(request, "booking/reserve_step2.html", {
        "car_type": car_type,
        "range_0_24": range(24)
    })


@login_required
def reserve_success(request):

    car_id = request.session.get("car_id")
    start_time = request.session.get("start_time")
    end_time = request.session.get("end_time")

    car = Car.objects.filter(id=car_id).first() if car_id else None

    return render(request, "booking/reserve_success.html", {
        "car": car,
        "start_time": start_time,
        "end_time": end_time
    })