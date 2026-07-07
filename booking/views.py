import random
import json
from datetime import datetime, time, timedelta
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.contrib.auth import login
from django.contrib.auth.models import User
from django.shortcuts import render, redirect, get_object_or_404
from .models import Car, Reservation, Profile, EmailVerifyToken
from django.core.mail import send_mail
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.db import transaction
from django.db.models import Count
from django.db.models.functions import TruncMonth
from django.core.cache import cache
from django.views.decorators.http import require_POST
from booking.services.risk_engine import get_user_stats, get_user_risk, detect_user_risk
from booking.services.lock_engine import apply_user_risk_lock, is_user_locked

S = Reservation.Status


def _expire_pending(db_now):
    """逾時未報到的 pending 預約標記為 no-checkIn（各 view 共用）。"""
    Reservation.objects.filter(
        status=S.PENDING, start_time__lt=db_now - timedelta(minutes=15)
    ).update(status=S.NO_CHECK_IN)


def set_timezone(request):
    data = json.loads(request.body)
    request.session["django_timezone"] = data["timezone"]
    return JsonResponse({"status": "ok"})


# ====== 登入 / 註冊 ======
def login_page(request):
    if request.user.is_authenticated:
        return redirect("reserve_step1")

    return render(request, "registration/login.html")


@require_POST
def send_otp(request):
    phone = request.POST.get("phone", "").strip()
    if not phone:
        return JsonResponse({"status": "fail", "msg": "phone required"})

    # 同一支手機每分鐘只能請求一次
    if cache.get(f"otp_rate:{phone}"):
        return JsonResponse({"status": "rate_limit", "msg": "請稍候 60 秒後再重新發送"})

    otp = str(random.randint(100000, 999999))

    cache.set(f"otp:{phone}", otp, timeout=300)  # OTP 有效期五分鐘
    cache.set(f"otp_rate:{phone}", True, timeout=60)  # 速率限制一分鐘

    print(f"[OTP] {phone}: {otp}")

    return JsonResponse({"status": "ok"})


@ensure_csrf_cookie
def get_csrf_token(request):
    return JsonResponse({"message": "CSRF cookie set"})


def verify_otp(request):
    phone = request.POST.get("phone", "").strip()
    otp = request.POST.get("otp", "").strip()

    stored_otp = cache.get(f"otp:{phone}")

    if not stored_otp:
        return JsonResponse({"status": "fail", "msg": "OTP 已過期，請重新發送"})

    if stored_otp != otp:
        return JsonResponse({"status": "fail"})

    # 刪除 OTP 防止重複使用
    cache.delete(f"otp:{phone}")

    try:
        profile = Profile.objects.get(phone=phone)
        login(request, profile.user)
        return JsonResponse({"status": "login_success", "redirect": "/reserve/"})

    except Profile.DoesNotExist:
        request.session["register_phone"] = phone
        return JsonResponse({"status": "need_register"})


def register(request):
    phone = request.session.get("register_phone")
    now = timezone.localtime()

    if request.method == "POST":
        name = request.POST.get("name")
        email = request.POST.get("email")

        if Profile.objects.filter(email=email).exists():
            return render(
                request,
                "booking/register.html",
                {"phone": phone, "error": "這個 Email 已經被註冊過了"},
            )

        user = User.objects.create(username=name, email=email)

        Profile.objects.create(
            user=user,
            phone=phone,
            email=email,
            is_email_verified=False,
            register_time=now,
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

    if token_obj.is_used:
        return JsonResponse({"status": "fail", "msg": "already used"})

    if token_obj.is_expired():
        return JsonResponse({"status": "fail", "msg": "token expired"})

    token_obj.is_used = True
    token_obj.save()

    # 啟用帳號
    profile = Profile.objects.get(user=token_obj.user)
    profile.is_email_verified = True
    profile.save()

    login(request, token_obj.user)

    return JsonResponse({"status": "success", "redirect": "/home/"})


def check_email_page(request):
    return render(request, "booking/check_email.html")


# ====== home page ======
def home(request):

    now = timezone.localtime()

    start_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # ================= KPI =================
    total_bookings = Reservation.objects.exclude(status=S.CANCELLED).count()

    month_bookings = (
        Reservation.objects.filter(start_time__gte=start_month)
        .exclude(status=S.CANCELLED)
        .count()
    )

    # ================= 使用中 reservations =================
    active_reservations = Reservation.objects.filter(status=S.ON_GOING)

    active_bookings = active_reservations.count()

    # ================= 車輛 =================
    total_cars = Car.objects.count()

    busy_cars = (
        Car.objects.filter(
            reservation__status=S.ON_GOING,
        )
        .distinct()
        .count()
    )

    available_cars = total_cars - busy_cars

    # ================= 4人座 =================
    car4_total = Car.objects.filter(type="4人座").count()

    car4_busy = (
        Car.objects.filter(
            type="4人座",
            reservation__status=S.ON_GOING,
        )
        .distinct()
        .count()
    )

    car4_available = car4_total - car4_busy

    # ================= 10人座 =================
    car10_total = Car.objects.filter(type="10人座").count()

    car10_busy = (
        Car.objects.filter(
            type="10人座",
            reservation__status=S.ON_GOING,
        )
        .distinct()
        .count()
    )

    car10_available = car10_total - car10_busy

    # ================= Trend (ALL) =================
    trend_qs = (
        Reservation.objects.exclude(status=S.CANCELLED)
        .annotate(date=TruncMonth("start_time"))
        .values("date")
        .annotate(count=Count("id"))
        .order_by("date")
    )

    # ================= Trend (4 / 10 split) =================
    trend_4 = (
        Reservation.objects.filter(car__type="4人座")
        .exclude(status=S.CANCELLED)
        .annotate(date=TruncMonth("start_time"))
        .values("date")
        .annotate(count=Count("id"))
        .order_by("date")
    )

    trend_10 = (
        Reservation.objects.filter(car__type="10人座")
        .exclude(status=S.CANCELLED)
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
    return render(
        request,
        "booking/home.html",
        {
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
        },
    )


# ====== booking page ======
def is_conflict(start1, end1, start2, end2):
    return not (end1 <= start2 or start1 >= end2)


@login_required(login_url="login")
def reserve_step1(request):
    profile = Profile.objects.get(user=request.user)
    profile.refresh_from_db()
    stat = get_user_stats(request.user)
    risk = get_user_risk(request.user, profile)

    risk_level, _, _, _ = detect_user_risk(
        risk["no_show"], risk["overdue"], stat["credit_score"], 0
    )

    apply_user_risk_lock(profile, risk_level)

    if is_user_locked(profile):
        return render(
            request,
            "booking/reserve_step1.html",
            {"blocked": True, "unlock_time": profile.risk_locked_until},
        )

    # ================= POST =================
    if request.method == "POST":
        car_type = request.POST.get("car_type")

        if not car_type:
            return render(
                request,
                "booking/reserve_step1.html",
                {"error": "請選擇車型", "blocked": False},
            )

        request.session["car_type"] = car_type
        request.session.pop("car_id", None)
        request.session.pop("start_time", None)
        request.session.pop("end_time", None)

        return redirect("reserve_step2")

    return render(request, "booking/reserve_step1.html", {"blocked": False})


@login_required(login_url="login")
def reserve_step2(request):
    db_now = timezone.localtime()

    # =========================
    # 時間對齊（進位至最近 15 分鐘）
    # =========================
    def round_start_time(dt):
        minute = dt.minute

        if 0 <= minute <= 15:
            minute = 15
        elif 16 <= minute <= 30:
            minute = 30
        elif 31 <= minute <= 45:
            minute = 45
        else:
            dt = dt + timedelta(hours=1)
            minute = 0

        return dt.replace(minute=minute, second=0, microsecond=0)

    _expire_pending(db_now)

    car_type = request.session.get("car_type")

    if not car_type:
        return redirect("reserve_step1")

    car_prefix = "4Car" if car_type == "4人座" else "10Car"

    # 取得該車型所有車輛
    cars = (
        Car.objects.filter(name__startswith=car_prefix)
        .annotate(usage_count=Count("reservation"))
        .order_by("usage_count")
    )

    total_cars_count = cars.count()
    today = timezone.localdate()
    now = timezone.localtime()

    start_anchor = round_start_time(now)
    start_anchor = start_anchor.replace(
        year=today.year, month=today.month, day=today.day
    )
    end_anchor = start_anchor + timedelta(hours=4)

    day_start = timezone.make_aware(datetime.combine(today, time.min))

    # =========================
    # 96 slot 視覺化
    # =========================
    time_slots = []
    start_index = int((start_anchor - day_start).total_seconds() // 900)

    for i in range(start_index, start_index + 96):
        slot_start = day_start + timedelta(minutes=i * 15)
        slot_end = slot_start + timedelta(minutes=15)

        car_status_list = []
        for car in cars:
            # 精確檢查這台特定的實體車在此 15 分鐘內有沒有被預約
            is_using = Reservation.objects.filter(
                car=car,
                status=S.ON_GOING,
                return_time__isnull=True,
                start_time__lt=slot_end,
                end_time__gt=slot_start,
            ).exists()

            is_pending = Reservation.objects.filter(
                car=car,
                status=S.PENDING,
                start_time__lt=slot_end,
                end_time__gt=slot_start,
            ).exists()

            if is_using:
                state = "using"
            elif is_pending:
                state = "pending"
            else:
                state = "free"

            car_status_list.append({"state": state})

        time_slots.append(
            {
                "time_label": slot_start.strftime("%H:%M"),
                "hour": slot_start.hour,
                "car_status": car_status_list,
                "datetime": slot_start.isoformat(),
            }
        )

    # =========================
    # POST
    # =========================
    if request.method == "POST":
        raw_now = timezone.localtime()

        # start_time 固定為當下時間（取整至 15 分鐘）
        start_dt = round_start_time(raw_now)
        start_dt = start_dt.replace(year=today.year, month=today.month, day=today.day)

        end_hour = int(request.POST.get("end_hour", 0))
        end_minute = int(request.POST.get("end_minute", 0))

        end_dt = timezone.make_aware(
            datetime.combine(today, time(end_hour, end_minute))
        )
        # 時間規則驗證
        if end_dt <= start_dt:
            return render(
                request,
                "booking/reserve_step2.html",
                {
                    "car_type": car_type,
                    "time_slots": time_slots,
                    "total_cars_count": total_cars_count,
                    "minutes": [0, 15, 30, 45],
                    "range_0_24": range(now.hour, 24),
                    "error": "結束時間必須大於開始時間",
                },
            )

        duration = end_dt - start_dt

        # 當日結束時間（用於 gap 計算）
        day_end_gap = timezone.make_aware(datetime.combine(today, time(23, 59)))

        best_car = None
        best_score = None

        # Best Fit 車輛選擇
        for car in cars:
            unreturned = Reservation.objects.filter(
                car=car, status=S.ON_GOING, return_time__isnull=True
            ).exists()

            # 時段衝突檢查
            conflict = Reservation.objects.filter(
                car=car,
                status__in=[S.PENDING, S.ON_GOING],
                start_time__lt=end_dt,
                end_time__gt=start_dt,
            ).exists()

            if conflict or unreturned:
                continue

            reservations = Reservation.objects.filter(
                car=car, start_time__date=today
            ).order_by("start_time")

            # 找 gaps
            gaps = []
            prev_end = timezone.make_aware(datetime.combine(today, time(0, 0)))

            for r in reservations:
                if r.start_time > prev_end:
                    gaps.append((prev_end, r.start_time))
                prev_end = r.end_time

            if prev_end < day_end_gap:
                gaps.append((prev_end, day_end_gap))

            valid_gaps = [
                (g_start, g_end)
                for g_start, g_end in gaps
                if (g_end - g_start) >= duration
            ]

            if not valid_gaps:
                continue

            # Best Fit：選最小的可用 gap
            gap_size = min((g_end - g_start) for g_start, g_end in valid_gaps)

            # 使用次數懲罰，分散車輛使用
            usage_penalty = timedelta(minutes=5 * reservations.count())

            score = gap_size + usage_penalty

            if best_score is None or score < best_score:
                best_score = score
                best_car = car

        if not best_car:
            return render(
                request,
                "booking/reserve_step2.html",
                {
                    "car_type": car_type,
                    "time_slots": time_slots,
                    "total_cars_count": total_cars_count,
                    "minutes": [0, 15, 30, 45],
                    "range_0_24": range(now.hour, 24),
                    "error": "目前無可用車輛",
                },
            )

        # 建立預約（atomic transaction）
        with transaction.atomic():
            # 1. 鎖定車輛（select_for_update）
            car = Car.objects.select_for_update().get(id=best_car.id)

            # 2. 二次衝突確認（防止 race condition）
            conflict = Reservation.objects.filter(
                car=car,
                status__in=[S.PENDING, S.ON_GOING],
                start_time__lt=end_dt,
                end_time__gt=start_dt,
            ).exists()

            if conflict:
                return render(
                    request,
                    "booking/reserve_step2.html",
                    {
                        "car_type": car_type,
                        "time_slots": time_slots,
                        "total_cars_count": total_cars_count,
                        "minutes": [0, 15, 30, 45],
                        "range_0_24": range(now.hour, 24),
                        "error": "該時段已被預約",
                    },
                )

            # 3. 建立預約記錄
            Reservation.objects.create(
                user=request.user,
                car=car,
                start_time=start_dt,
                end_time=end_dt,
                status=S.PENDING,
            )

        request.session["car_id"] = best_car.id
        request.session["start_time"] = start_dt.strftime("%H:%M")
        request.session["end_time"] = end_dt.strftime("%H:%M")

        return redirect("reserve_success")

    # GET
    context = {
        "car_type": car_type,
        "time_slots": time_slots,
        "total_cars_count": total_cars_count,
        "minutes": [0, 15, 30, 45],
        "range_0_24": range(now.hour, 24),
        "start_anchor": start_anchor,
        "end_anchor": end_anchor,
    }
    return render(request, "booking/reserve_step2.html", context)


@login_required(login_url="login")
def reserve_success(request):

    car_id = request.session.get("car_id")
    start_time = request.session.get("start_time")
    end_time = request.session.get("end_time")

    car = Car.objects.filter(id=car_id).first() if car_id else None

    return render(
        request,
        "booking/reserve_success.html",
        {"car": car, "start_time": start_time, "end_time": end_time},
    )


# check-in page
@login_required(login_url="login")
def checkin_list(request):
    db_now = timezone.localtime()
    _expire_pending(db_now)

    today = timezone.localdate()

    reservations = Reservation.objects.filter(
        user=request.user, start_time__date=today, status=S.PENDING
    )

    if request.method == "POST":
        selected_ids = request.POST.getlist("selected")

        Reservation.objects.filter(
            user=request.user, id__in=selected_ids, status=S.PENDING
        ).update(status=S.ON_GOING, checkIn_time=db_now)

        return redirect("checkin_list")

    return render(request, "booking/checkin.html", {"reservations": reservations})


# return page
@login_required(login_url="login")
def return_list(request):

    now = timezone.localtime()

    reservations = Reservation.objects.filter(user=request.user, status=S.ON_GOING)

    enriched = []

    for r in reservations:
        if not r.end_time:
            continue

        delta = r.end_time - now
        minutes = int(delta.total_seconds() / 60)

        if minutes >= 0:
            enriched.append({"obj": r, "status_text": "剩餘", "time_value": minutes})
        else:
            enriched.append(
                {"obj": r, "status_text": "逾時", "time_value": abs(minutes)}
            )

    if request.method == "POST":
        selected_ids = request.POST.getlist("selected")

        Reservation.objects.filter(
            user=request.user, id__in=selected_ids, status=S.ON_GOING
        ).update(status=S.COMPLETED, return_time=now)

        return redirect("return_list")

    return render(request, "booking/return.html", {"reservations": enriched})


# history page
@login_required(login_url="login")
def history_list(request):
    db_now = timezone.localtime()
    _expire_pending(db_now)

    reservations = Reservation.objects.filter(user=request.user).order_by("-start_time")

    return render(request, "booking/history.html", {"reservations": reservations})


@login_required(login_url="login")
def edit_reservation(request, reservation_id):

    reservation = get_object_or_404(Reservation, id=reservation_id, user=request.user)

    # 僅允許 pending 狀態的預約修改
    if reservation.status != S.PENDING:
        return redirect("history_list")

    now = timezone.localtime()
    minutes = [0, 15, 30, 45]

    reservation.refresh_from_db()

    start_time = timezone.localtime(reservation.start_time)
    end_time = timezone.localtime(reservation.end_time)

    if request.method == "POST":
        if "delete" in request.POST:
            reservation.status = S.CANCELLED
            reservation.save()
            return redirect("history_list")

        # 修改時間
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
            return render(
                request,
                "booking/edit_reservation.html",
                {
                    "r": reservation,
                    "start_time": start_time,
                    "end_time": end_time,
                    "range_0_24": range(now.hour, 24),
                    "minutes": minutes,
                    "now": now,
                    "error": "開始時間不能早於現在",
                },
            )

        if start_dt > now + timedelta(minutes=15):
            max_open_time = (now + timedelta(minutes=15)).strftime("%H:%M")
            return render(
                request,
                "booking/edit_reservation.html",
                {
                    "r": reservation,
                    "start_time": start_time,
                    "end_time": end_time,
                    "range_0_24": range(now.hour, 24),
                    "minutes": minutes,
                    "now": now,
                    "error": f"目前最遠僅能修改至 {max_open_time} 之前的時間",
                },
            )

        if end_dt <= start_dt:
            return render(
                request,
                "booking/edit_reservation.html",
                {
                    "r": reservation,
                    "start_time": start_time,
                    "end_time": end_time,
                    "range_0_24": range(now.hour, 24),
                    "minutes": minutes,
                    "now": now,
                    "error": "結束時間必須大於開始時間",
                },
            )

        # 時段衝突檢查
        conflict = (
            Reservation.objects.filter(
                car=reservation.car,
                status__in=[S.PENDING, S.ON_GOING],
                start_time__lt=end_dt,
                end_time__gt=start_dt,
            )
            .exclude(id=reservation.id)
            .exists()
        )

        if conflict:
            return render(
                request,
                "booking/edit_reservation.html",
                {
                    "r": reservation,
                    "start_time": start_time,
                    "end_time": end_time,
                    "range_0_24": range(now.hour, 24),
                    "minutes": minutes,
                    "now": now,
                    "error": "該時段已有其他預約，請選擇其他時間",
                },
            )

        reservation.start_time = start_dt
        reservation.end_time = end_dt
        reservation.save()

        return redirect("history_list")

    return render(
        request,
        "booking/edit_reservation.html",
        {
            "r": reservation,
            "start_time": start_time,
            "end_time": end_time,
            "range_0_24": range(now.hour, 24),
            "minutes": minutes,
            "now": now,
        },
    )


# profile page
@login_required(login_url="login")
def profile(request):

    user_profile, _ = Profile.objects.get_or_create(user=request.user)

    # 使用統計
    stats = get_user_stats(request.user)

    no_show_count = stats["no_show_count"]
    overdue_return_count = stats["overdue_return_count"]
    total_reservations = stats["total_reservations"]
    credit_score = stats["credit_score"]

    no_show_rate = (
        round(no_show_count / total_reservations * 100, 1)
        if total_reservations > 0
        else 0
    )

    avg_duration_min = (
        round(stats["avg_duration_min"].total_seconds() / 60, 1)
        if stats["avg_duration_min"]
        else 0
    )

    favorite_car_type = (
        stats["favorite_car_type"]["car__type"] if stats["favorite_car_type"] else "-"
    )

    # 風險計算
    risk = get_user_risk(request.user, user_profile)

    risk_level, risk_flags, risk_reason, risk_score = detect_user_risk(
        risk["no_show"], risk["overdue"], credit_score, avg_duration_min
    )

    # 同步鎖定狀態
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
            # email 有變動才寫入
            if new_email and new_email != user_profile.email:
                user_profile.email = new_email
                user_profile.is_email_verified = False
                user_profile.save()

            # 用目前 DB email 或 input email
            target_email = new_email or user_profile.email

            if target_email:
                token_obj = EmailVerifyToken.objects.create(user=request.user)

                verify_link = (
                    f"http://127.0.0.1:8000/check_email/?token={token_obj.token}"
                )

                send_mail(
                    "請驗證你的信箱",
                    f"點擊以下連結完成驗證：\n{verify_link}",
                    None,
                    [target_email],
                )

            return redirect("profile")

    return render(
        request,
        "user/profile.html",
        {
            # 個人資訊
            "profile": user_profile,
            # 統計數據
            "no_show_count": no_show_count,
            "overdue_return_count": overdue_return_count,
            "total_reservations": total_reservations,
            "no_show_rate": no_show_rate,
            "avg_duration_min": avg_duration_min,
            "favorite_car_type": favorite_car_type,
            # 風險資訊
            "credit_score": credit_score,
            "risk_level": risk_level,
            "risk_flags": risk_flags,
            "risk_reason": risk_reason,
            "risk_score": risk_score,
            # 鎖定狀態
            "is_locked": is_locked,
        },
    )
