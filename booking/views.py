import random
from datetime import datetime, time, timedelta
from django.core.cache import cache
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.http import JsonResponse, HttpResponse
from django.contrib.auth import login
from django.contrib.auth.models import User
from django.shortcuts import render, redirect, get_object_or_404
from .models import Car, Reservation, Profile, EmailVerifyToken
from django.core.mail import send_mail
from django.utils.crypto import get_random_string
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.db import transaction
from django.db.models import Count


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


@ensure_csrf_cookie
def get_csrf_token(request):
    return JsonResponse({"message": "CSRF cookie set"})

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

    # 🔥 自動建立車輛（如果不存在）
    for i in range(1, 7):
        Car.objects.get_or_create(
            name=f"4Car_{i}",
            defaults={"plate": f"4-{i}"}
        )

    for i in range(1, 5):
        Car.objects.get_or_create(
            name=f"10Car_{i}",
            defaults={"plate": f"10-{i}"}
        )

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

    # ✅ 加入使用次數（避免一直選同一台🔥）
    cars = Car.objects.filter(name__startswith=car_prefix).annotate(
        usage_count=Count("reservation")
    ).order_by("usage_count")

    now = timezone.localtime()

    if request.method == "POST":

        start_hour = int(request.POST.get("start_hour"))
        start_minute = int(request.POST.get("start_minute"))
        end_hour = int(request.POST.get("end_hour"))
        end_minute = int(request.POST.get("end_minute"))

        today = timezone.localdate()

        start_dt = datetime.combine(today, time()).replace(
            hour=start_hour, minute=start_minute
        )
        end_dt = datetime.combine(today, time()).replace(
            hour=end_hour, minute=end_minute
        )

        start_dt = timezone.make_aware(start_dt)
        end_dt = timezone.make_aware(end_dt)

        if start_dt < now - timedelta(minutes=2):
            return render(request, "booking/reserve_step2.html", {
                "car_type": car_type,
                "range_0_24": range(now.hour, 24),
                "error": "不能預約過去的時間"
            })

        if start_dt > now + timedelta(minutes=15):
            max_open_time = (now + timedelta(minutes=15)).strftime("%H:%M")
            return render(request, "booking/reserve_step2.html", {
                "car_type": car_type,
                "range_0_24": range(now.hour, 24),
                "error": f"公務車僅開放使用前 15 分鐘預約。目前僅能預約至 {max_open_time} 之前的車輛。"
            })

        if end_dt <= start_dt:
            return render(request, "booking/reserve_step2.html", {
                "car_type": car_type,
                "range_0_24": range(now.hour, 24),
                "error": "結束時間必須大於開始時間"
            })

        duration = end_dt - start_dt

        best_car = None
        best_score = None

        # ====== 找最佳車（Best Fit + 使用率）======
        for car in cars:
            # 🚨 先檢查這台車這個時間能不能用（最重要🔥）
            conflict = Reservation.objects.filter(
                car=car,
                start_time__lt=end_dt,
                end_time__gt=start_dt
            ).exists()

            if conflict:
                continue

            reservations = Reservation.objects.filter(
                car=car,
                start_time__date=today
            ).order_by("start_time")

            # ===== 找 gaps =====
            gaps = []
            prev_end = datetime.combine(today, time(0, 0))
            prev_end = timezone.make_aware(prev_end)

            for r in reservations:
                if r.start_time > prev_end:
                    gaps.append((prev_end, r.start_time))
                prev_end = r.end_time

            day_end = datetime.combine(today, time(23, 59))
            day_end = timezone.make_aware(day_end)

            if prev_end < day_end:
                gaps.append((prev_end, day_end))

            # ===== 找可用 gap =====
            valid_gaps = []
            for g_start, g_end in gaps:
                if (g_end - g_start) >= duration:
                    valid_gaps.append((g_start, g_end))

            if not valid_gaps:
                continue

            # 👉 最小 gap（Best Fit）
            gap_size = min((g_end - g_start) for g_start, g_end in valid_gaps)

            # 👉 加入使用次數懲罰（避免一直選同一台🔥）
            usage_penalty = timedelta(minutes=5 * reservations.count())

            score = gap_size + usage_penalty

            if best_score is None or score < best_score:
                best_score = score
                best_car = car

        if not best_car:
            return render(request, "booking/reserve_step2.html", {
                "car_type": car_type,
                "range_0_24": range(now.hour, 24),
                "error": "目前無可用車輛"
            })

        with transaction.atomic():

            # 🔥 1. 鎖車（關鍵）
            car = Car.objects.select_for_update().get(id=best_car.id)

            # 🔥 2. 再檢查衝突
            conflict = Reservation.objects.filter(
                car=car,
                start_time__lt=end_dt,
                end_time__gt=start_dt
            ).exists()

            if conflict:
                return render(request, "booking/reserve_step2.html", {
                    "car_type": car_type,
                    "range_0_24": range(now.hour, 24),
                    "error": "該時段剛被預約，請重新選擇"
                })

            # 🔥 3. 安全寫入
            Reservation.objects.create(
                user=request.user,
                car=car,
                start_time=start_dt,
                end_time=end_dt,
            )

        request.session["car_id"] = best_car.id
        request.session["start_time"] = start_dt.strftime("%H:%M")
        request.session["end_time"] = end_dt.strftime("%H:%M")

        return redirect("reserve_success")

    context = {
        "car_type": car_type,
        "range_0_24": range(now.hour, 24),
        "minutes": [0, 15, 30, 45]
    }
    return render(request, "booking/reserve_step2.html", context)


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
    now = timezone.now()
    today = timezone.now().date()

    Reservation.objects.filter(
        status="pending",
        start_time__lt=now - timedelta(minutes=15)
    ).update(status="cancelled")

    # 👉 抓「現在時間內」的預約
    reservations = Reservation.objects.filter(
        start_time__date=today,
        status="pending"
    )

    if request.method == "POST":
        selected_ids = request.POST.getlist("selected")

        Reservation.objects.filter(
            id__in=selected_ids).update(status="on-going")

        return redirect("checkin_list")

    return render(request, "booking/checkin.html", {
        "reservations": reservations
    })


# ====== return page ======
@login_required
def return_list(request):
    now = timezone.now()

    Reservation.objects.filter(
        status="on-going",
        end_time__lt=now
    ).update(status="overtime")

    reservations = Reservation.objects.filter(
        status__in=["on-going", "overtime"]
    )

    enriched = []

    for r in reservations:
        if not r.end_time:
            continue

        delta = r.end_time - now
        minutes = int(delta.total_seconds() / 60)

        # 👉 未到時間（剩餘）
        if minutes >= 0:
            enriched.append({
                "obj": r,
                "status_text": "剩餘",
                "time_value": minutes
            })

        # 👉 已逾時
        else:
            enriched.append({
                "obj": r,
                "status_text": "逾時",
                "time_value": abs(minutes)
            })

    if request.method == "POST":
        selected_ids = request.POST.getlist("selected")

        Reservation.objects.filter(
            id__in=selected_ids
        ).update(status="completed")
        return redirect("return_list")

    return render(request, "booking/return.html", {
        "reservations": enriched
    })


# ====== histiry page ======
@login_required
def history_list(request):

    reservations = Reservation.objects.filter(
        user=request.user).order_by("-start_time")

    return render(request, "booking/history.html", {
        "reservations": reservations
    })


@login_required
def edit_reservation(request, reservation_id):

    reservation = get_object_or_404(
        Reservation, id=reservation_id, user=request.user
    )

    # ❗只允許未報到修改
    if reservation.status != "pending":
        return redirect("history_list")

    now = timezone.localtime()

    hour_range = range(0, 24)
    minutes = [0, 15, 30, 45]

    # 🔥 每次進來都從 DB 重新 normalize（關鍵）
    reservation.refresh_from_db()

    start_time = timezone.localtime(reservation.start_time)
    end_time = timezone.localtime(reservation.end_time)

    if request.method == "POST":

        # 🔴 刪除功能
        if "delete" in request.POST:
            reservation.status = "cancelled"
            reservation.save()
            return redirect("history_list")

        # 🟢 修改時間
        start_hour = int(request.POST.get("start_hour"))
        start_minute = int(request.POST.get("start_minute"))
        end_hour = int(request.POST.get("end_hour"))
        end_minute = int(request.POST.get("end_minute"))

        today = timezone.localdate()

        start_dt = datetime.combine(today, datetime.min.time()).replace(
            hour=start_hour, minute=start_minute
        )
        end_dt = datetime.combine(today, datetime.min.time()).replace(
            hour=end_hour, minute=end_minute
        )

        start_dt = timezone.make_aware(start_dt)
        end_dt = timezone.make_aware(end_dt)

        # 不可早於現在時間
        if start_dt < now:
            return render(request, "booking/edit_reservation.html", {
                "r": reservation,
                "start_time": start_time,
                "end_time": end_time,
                "range_0_24": range(now.hour, 24),
                "minutes": minutes,
                "now": now,
                "error": "開始時間不能早於現在"
            })

        if end_dt <= start_dt:
            return render(request, "booking/edit_reservation.html", {
                "r": reservation,
                "start_time": start_time,
                "end_time": end_time,
                "range_0_24": range(now.hour, 24),
                "minutes": minutes,
                "now": now,
                "error": "結束時間必須大於開始時間"
            })

        # ✅ 更新 DB（保持原本）
        reservation.start_time = start_dt
        reservation.end_time = end_dt
        reservation.save()

        return redirect("history_list")

    return render(request, "booking/edit_reservation.html", {
        "r": reservation,
        "start_time": start_time,
        "end_time": end_time,
        "range_0_24": range(now.hour, 24),
        "minutes": minutes,
        "now": now
    })


# ====== profile page ======
@login_required
def profile(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)

    if request.method == "POST":

        action = request.POST.get("action")
        new_email = request.POST.get("email")

        # ======================
        # ① 儲存 email（寫 DB）
        # ======================
        if action == "save":

            if new_email and new_email != profile.email:
                profile.email = new_email
                profile.is_email_verified = False
                profile.save()

            return redirect("profile")

        # ======================
        # ② 驗證 email（寄信）
        # ======================
        if action == "verify_email":

            # 用目前 DB email 或 input email
            target_email = new_email or profile.email

            if target_email:

                token_obj = EmailVerifyToken.objects.create(user=request.user)

                verify_link = f"http://127.0.0.1:8000/check_email/?token={token_obj.token}"

                send_mail(
                    "請驗證你的信箱",
                    f"點擊以下連結完成驗證：\n{verify_link}",
                    None,
                    [target_email],
                )

            return redirect("profile")

    return render(request, "user/profile.html", {
        "profile": profile
    })
