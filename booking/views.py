import random
from datetime import datetime, timedelta
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
from django.utils import timezone


# 👉 用記憶體暫存（開發用）
otp_store = {}

# ======= login / register ======
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

# ====== home page ======
def home(request):
    return render(request, "booking/home.html")

# ====== booking page ======
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

        # ✅ 今天日期（台灣時間）
        today = timezone.localdate()

        # ✅ 組合完整 datetime（含日期）
        start_dt = datetime.combine(today, datetime.min.time()).replace(
            hour=start_hour, minute=start_minute
        )
        end_dt = datetime.combine(today, datetime.min.time()).replace(
            hour=end_hour, minute=end_minute
        )

        # ✅ 加上時區（非常重要🔥）
        start_dt = timezone.make_aware(start_dt)
        end_dt = timezone.make_aware(end_dt)

        # 🚨 防呆：結束時間要大於開始時間
        if end_dt <= start_dt:
            return render(request, "booking/reserve_step2.html", {
                "car_type": car_type,
                "range_0_24": range(24),
                "error": "結束時間必須大於開始時間"
            })

        selected_car = None

        for car in cars:

            # ✅ 只抓「同一天」的預約（避免跨天干擾）
            reservations = Reservation.objects.filter(
                car=car,
                start_time__date=today
            )

            conflict = False

            for r in reservations:
                if not (end_dt <= r.start_time or start_dt >= r.end_time):
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

        # ✅ 建立預約（正確時間🔥）
        Reservation.objects.create(
            user=request.user,
            car=selected_car,
            start_time=start_dt,
            end_time=end_dt,
        )

        request.session["car_id"] = selected_car.id
        request.session["start_time"] = start_dt.strftime("%H:%M")
        request.session["end_time"] = end_dt.strftime("%H:%M")

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

# ====== check-in page ======
@login_required
def checkin_list(request):
    today = timezone.now().date()
    print("123", today)

    # 👉 抓「現在時間內」的預約
    reservations = Reservation.objects.filter(
        start_time__date=today,
        is_checked_in=False
    )

    if request.method == "POST":
        selected_ids = request.POST.getlist("selected")

        Reservation.objects.filter(id__in=selected_ids).update(is_checked_in=True)

        return redirect("checkin_list")

    return render(request, "booking/checkin.html", {
        "reservations": reservations
    })

# ====== return page ======
@login_required
def return_list(request):
    now = timezone.now()

    # 👉 已報到但還沒還車
    reservations = Reservation.objects.filter(
        is_checked_in=True,
        is_returned=False
    )

    if request.method == "POST":
        selected_ids = request.POST.getlist("selected")

        Reservation.objects.filter(id__in=selected_ids).update(is_returned=True)

        return redirect("return_list")

    return render(request, "booking/return.html", {
        "reservations": reservations
    })