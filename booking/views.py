import random
import re
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

@login_required
def reserve_step1(request):
    if request.method == "POST":
        car_type = request.POST.get("car_type")
        request.session["car_type"] = car_type
        return redirect("reserve_step2")

    return render(request, "booking/reserve_step1.html")

@login_required
def reserve_step2(request):
    car_type = request.session.get("car_type")

    if not car_type:
        return redirect("reserve_step1")

    cars = Car.objects.filter(type=car_type)

    if request.method == "POST":
        car_id = request.POST.get("car")
        start_time = request.POST.get("start_time")
        end_time = request.POST.get("end_time")

        request.session["car_id"] = car_id
        request.session["start_time"] = start_time
        request.session["end_time"] = end_time

        return redirect("reserve_success")

    return render(request, "booking/reserve_step2.html", {
        "cars": cars,
        "car_type": car_type,
        "range_0_24": range(24)
    })

@login_required
def reserve_success(request):

    car_id = request.session.get("car_id")
    start_time = request.session.get("start_time")
    end_time = request.session.get("end_time")

    car = None
    if car_id:
        from .models import Car
        car = Car.objects.filter(id=car_id).first()

    return render(request, "booking/reserve_success.html", {
        "car": car,
        "start_time": start_time,
        "end_time": end_time
    })