import random
import json
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
from django.db.models import Count, Avg, F, ExpressionWrapper, DurationField
from django.db.models.functions import TruncMonth
from booking.services.risk_engine import get_user_stats, get_user_risk, detect_user_risk
from booking.services.lock_engine import apply_user_risk_lock, is_user_locked


# 👉 用記憶體暫存（開發用）
otp_store = {}


def set_timezone(request):
    data = json.loads(request.body)
    request.session['django_timezone'] = data['timezone']
    return JsonResponse({'status': 'ok'})

# ======= login / register ======
def login_page(request):
    # 已登入 → 直接進借車頁
    if request.user.is_authenticated:
        return redirect("reserve_step1")

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
    now = timezone.localtime()

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
            is_email_verified=False,
            register_time=now
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
        "redirect": "/home/"
    })


def check_email_page(request):
    return render(request, "booking/check_email.html")


# ====== home page ======
def home(request):

    now = timezone.localtime()

    start_month = now.replace(
        day=1,
        hour=0,
        minute=0,
        second=0,
        microsecond=0
    )

    # ================= KPI =================
    total_bookings = Reservation.objects.exclude(
        status="cancelled"
    ).count()

    month_bookings = Reservation.objects.filter(
        start_time__gte=start_month
    ).exclude(
        status="cancelled"
    ).count()

    # ================= 使用中 reservations =================
    active_reservations = Reservation.objects.filter(
        status="on-going",
        start_time__lte=now,
        end_time__gte=now
    )

    active_bookings = active_reservations.count()

    # ================= 車輛 =================
    total_cars = Car.objects.count()

    busy_cars = Car.objects.filter(
        reservation__status="on-going",
    ).distinct().count()

    available_cars = total_cars - busy_cars

    # ================= 4人座 =================
    car4_total = Car.objects.filter(type="4人座").count()

    car4_busy = Car.objects.filter(
        type="4人座",
        reservation__status="on-going",
    ).distinct().count()

    car4_available = car4_total - car4_busy

    # ================= 10人座 =================
    car10_total = Car.objects.filter(type="10人座").count()

    car10_busy = Car.objects.filter(
        type="10人座",
        reservation__status="on-going",
    ).distinct().count()

    car10_available = car10_total - car10_busy

    # ================= Trend (ALL) =================
    trend_qs = (
        Reservation.objects
        .exclude(status="cancelled")
        .annotate(date=TruncMonth("start_time"))
        .values("date")
        .annotate(count=Count("id"))
        .order_by("date")
    )

    # ================= Trend (4 / 10 split) =================
    trend_4 = (
        Reservation.objects
        .filter(car__type="4人座")
        .exclude(status="cancelled")
        .annotate(date=TruncMonth("start_time"))
        .values("date")
        .annotate(count=Count("id"))
        .order_by("date")
    )

    trend_10 = (
        Reservation.objects
        .filter(car__type="10人座")
        .exclude(status="cancelled")
        .annotate(date=TruncMonth("start_time"))
        .values("date")
        .annotate(count=Count("id"))
        .order_by("date")
    )

    # ================= format =================
    trend_days = [x["date"].strftime("%Y-%m") for x in trend_qs]
    trend_all = [x["count"] for x in trend_qs]

    trend4 = [x["count"] for x in trend_4]
    trend10 = [x["count"] for x in trend_10]

    # ================= render =================
    return render(request, "booking/home.html", {

        # KPI
        "total_bookings": total_bookings,
        "month_bookings": month_bookings,
        "active_bookings": active_bookings,

        # 車輛
        "available_cars": available_cars,

        # 4人座
        "car4_available": car4_available,
        "car4_in_use": car4_busy,

        # 10人座
        "car10_available": car10_available,
        "car10_in_use": car10_busy,

        # charts
        "trend_days": json.dumps(trend_days),
        "trend_all": json.dumps(trend_all),
        "trend_4": json.dumps(trend4),
        "trend_10": json.dumps(trend10),
    })


# ====== booking page ======
def is_conflict(start1, end1, start2, end2):
    return not (end1 <= start2 or start1 >= end2)


@login_required(login_url='login')
def reserve_step1(request):
    profile = Profile.objects.get(user=request.user)
    profile.refresh_from_db()
    # 🔥 每次進來都重新算 risk
    stat = get_user_stats(request.user)
    risk = get_user_risk(request.user, profile)

    risk_level, _, _, _ = detect_user_risk(
        risk["no_show"],
        risk["overdue"],
        stat["credit_score"],
        0
    )

    # 🔥 統一入口更新 lock
    apply_user_risk_lock(profile, risk_level)
    # print("NO SHOW:", risk["no_show"])
    # print("OVERDUE:", risk["overdue"])
    # print("RISK LEVEL:", risk_level)
    # print("RESET AT:", profile.risk_reset_at)

    # 🔥 再檢查 lock
    if is_user_locked(profile):
        return render(request, "booking/reserve_step1.html", {
            "blocked": True,
            "unlock_time": profile.risk_locked_until
        })

    # ================= 車輛初始化 =================
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

    # ================= POST =================
    if request.method == "POST":
        car_type = request.POST.get("car_type")

        if not car_type:
            return render(request, "booking/reserve_step1.html", {
                "error": "請選擇車型",
                "blocked": False
            })

        request.session["car_type"] = car_type
        request.session.pop("car_id", None)
        request.session.pop("start_time", None)
        request.session.pop("end_time", None)

        return redirect("reserve_step2")

    return render(request, "booking/reserve_step1.html", {
        "blocked": False
    })


@login_required(login_url='login')
def reserve_step2(request):
    db_now = timezone.localtime()
    Reservation.objects.filter(
        status="pending",
        start_time__lt=db_now - timedelta(minutes=15)
    ).update(status="no-checkIn")

    car_type = request.session.get("car_type")

    if not car_type:
        return redirect("reserve_step1")

    car_prefix = "4Car" if car_type == "4人座" else "10Car"

    cars = Car.objects.filter(name__startswith=car_prefix).annotate(
        usage_count=Count("reservation")
    ).order_by("usage_count")

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

        if start_dt > now + timedelta(minutes=15):
            max_open_time = (now + timedelta(minutes=15)).strftime("%H:%M")
            return render(request, "booking/reserve_step2.html", {
                "car_type": car_type,
                "range_0_24": range(now.hour, 24),
                "minutes": [0, 15, 30, 45],
                "error": f"不符合借車規定：公務車僅開放使用前 15 分鐘內預約。目前最遠僅能預約至 {max_open_time} 之前的車輛。"
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
            unreturned = Reservation.objects.filter(
                car=car,
                status="on-going",
                end_time__lt=now
            ).exists()

            # 🚨 先檢查這台車這個時間能不能用（最重要🔥）
            conflict = Reservation.objects.filter(
                car=car,
                start_time__lt=end_dt,
                end_time__gt=start_dt
            ).exists()

            if conflict or unreturned:
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
                status="pending"
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


@login_required(login_url='login')
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
@login_required(login_url='login')
def checkin_list(request):
    db_now = timezone.localtime()
    Reservation.objects.filter(
        status="pending",
        start_time__lt=db_now - timedelta(minutes=15)
    ).update(status="no-checkIn")

    today = timezone.localdate()

    # 👉 抓「現在時間內」的預約
    reservations = Reservation.objects.filter(
        user=request.user,
        start_time__date=today,
        status="pending"
    )

    if request.method == "POST":
        selected_ids = request.POST.getlist("selected")

        Reservation.objects.filter(
            user=request.user,
            id__in=selected_ids,
            status="pending"
        ).update(status="on-going", checkIn_time=db_now)

        return redirect("checkin_list")

    return render(request, "booking/checkin.html", {
        "reservations": reservations
    })


# ====== return page ======
@login_required(login_url='login')
def return_list(request):

    now = timezone.localtime()

    reservations = Reservation.objects.filter(
        user=request.user,
        status="on-going"
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
            user=request.user,
            id__in=selected_ids,
            status="on-going"
        ).update(status="completed", return_time=now)

        return redirect("return_list")

    return render(request, "booking/return.html", {
        "reservations": enriched
    })


# ====== history page ======
@login_required(login_url='login')
def history_list(request):
    db_now = timezone.localtime()
    Reservation.objects.filter(
        status="pending",
        start_time__lt=db_now - timedelta(minutes=15)
    ).update(status="no-checkIn")

    reservations = Reservation.objects.filter(
        user=request.user).order_by("-start_time")

    return render(request, "booking/history.html", {
        "reservations": reservations
    })


@login_required(login_url='login')
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
        if start_dt < now - timedelta(minutes=1):
            return render(request, "booking/edit_reservation.html", {
                "r": reservation,
                "start_time": start_time,
                "end_time": end_time,
                "range_0_24": range(now.hour, 24),
                "minutes": minutes,
                "now": now,
                "error": "開始時間不能早於現在"
            })

        if start_dt > now + timedelta(minutes=15):
            max_open_time = (now + timedelta(minutes=15)).strftime("%H:%M")
            return render(request, "booking/edit_reservation.html", {
                "r": reservation,
                "start_time": start_time,
                "end_time": end_time,
                "range_0_24": range(now.hour, 24),
                "minutes": minutes,
                "now": now,
                "error": f"目前最遠僅能修改至 {max_open_time} 之前的時間"
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
@login_required(login_url='login')
def profile(request):

    user_profile, _ = Profile.objects.get_or_create(user=request.user)

    now = timezone.localtime()

    # =========================
    # 📊 使用統計（全部歷史）
    # =========================
    stats = get_user_stats(request.user)

    no_show_count = stats["no_show_count"]
    overdue_return_count = stats["overdue_return_count"]
    total_reservations = stats["total_reservations"]
    credit_score = stats["credit_score"]

    no_show_rate = (
        round(no_show_count / total_reservations * 100, 1)
        if total_reservations > 0 else 0
    )

    avg_duration_min = (
        round(stats["avg_duration_min"].total_seconds() / 60, 1)
        if stats["avg_duration_min"] else 0
    )

    favorite_car_type = (
        stats["favorite_car_type"]["car__type"]
        if stats["favorite_car_type"] else "-"
    )

    # =========================
    # 🔥 風險計算（重新計算）
    # =========================
    risk = get_user_risk(request.user, user_profile)

    risk_level, risk_flags, risk_reason, risk_score = detect_user_risk(
        risk["no_show"],
        risk["overdue"],
        credit_score,
        avg_duration_min
    )

    # =========================
    # 🔒 鎖定 / 解鎖
    # =========================
    user_profile.refresh_from_db()

    apply_user_risk_lock(user_profile, risk_level)
    is_locked = is_user_locked(user_profile)
    # =========================
    # POST
    # =========================
    if request.method == "POST":

        action = request.POST.get("action")
        new_email = request.POST.get("email")

        if action == "submit":
            # ======================
            # ① 儲存 email（寫 DB）
            # ======================
            if new_email and new_email != profile.email:
                profile.email = new_email
                profile.is_email_verified = False
                profile.save()

            # ======================
            # ② 驗證 email（寄信）
            # ======================
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

        # profile
        "profile": user_profile,

        # 📊 stats（歷史）
        "no_show_count": no_show_count,
        "overdue_return_count": overdue_return_count,
        "total_reservations": total_reservations,
        "no_show_rate": no_show_rate,
        "avg_duration_min": avg_duration_min,
        "favorite_car_type": favorite_car_type,

        # 🔥 risk
        "credit_score": credit_score,
        "risk_level": risk_level,
        "risk_flags": risk_flags,
        "risk_reason": risk_reason,
        "risk_score": risk_score,

        # lock state
        "is_locked": is_locked,
    })
