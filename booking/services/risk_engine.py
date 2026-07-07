from django.utils import timezone
from booking.models import Reservation
from django.db.models import Count, Avg, F, ExpressionWrapper, DurationField

S = Reservation.Status


def get_user_stats(user):
    now = timezone.localtime()

    # 未報到
    no_show_cnt = Reservation.objects.filter(user=user, status=S.NO_CHECK_IN).count()

    # 逾期未還
    overdue_return_cnt = Reservation.objects.filter(
        user=user, status=S.ON_GOING, end_time__lt=now
    ).count()

    # 信用分數
    credit_score = 100 - no_show_cnt * 3 - overdue_return_cnt * 2
    credit_score = max(0, min(100, credit_score))

    return {
        "total_reservations": Reservation.objects.filter(user=user).count(),
        "no_show_count": no_show_cnt,
        "overdue_return_count": overdue_return_cnt,
        "credit_score": credit_score,
        "avg_duration_min": (
            Reservation.objects.filter(user=user, status=S.COMPLETED)
            .annotate(
                duration=ExpressionWrapper(
                    F("return_time") - F("checkIn_time"), output_field=DurationField()
                )
            )
            .aggregate(avg=Avg("duration"))["avg"]
        ),
        "favorite_car_type": (
            Reservation.objects.filter(user=user)
            .values("car__type")
            .annotate(c=Count("id"))
            .order_by("-c")
            .first()
        ),
    }


def get_risk_window_start(profile):
    # 風險計算起點，解鎖後才重新開始算
    if profile.risk_reset_at:
        return profile.risk_reset_at
    return profile.register_time


def get_user_risk(user, profile):
    now = timezone.localtime()
    start = get_risk_window_start(profile)

    # 未報到
    no_show = Reservation.objects.filter(
        user=user, status=S.NO_CHECK_IN, start_time__gte=start, start_time__lt=now
    ).count()

    # 逾期未還
    overdue = Reservation.objects.filter(
        user=user, status=S.ON_GOING, end_time__lt=now, start_time__gte=start
    ).count()

    return {
        "no_show": no_show,
        "overdue": overdue,
    }


def detect_user_risk(no_show_count, overdue_count, credit_score, avg_duration_min):

    risk_score = 0
    risk_flags = []
    risk_reasons = []

    # 未報到
    if no_show_count > 0:
        risk_score += no_show_count * 3
        risk_flags.append("no_show")
        risk_reasons.append(f"未報到 {no_show_count} 次")

    # 逾期未還
    if overdue_count > 0:
        risk_score += overdue_count * 2
        risk_flags.append("overdue")
        risk_reasons.append(f"逾期未還 {overdue_count} 次")

    # 信用分數過低
    if credit_score < 60:
        risk_score += 4
        risk_flags.append("low_credit")
        risk_reasons.append("信用分數過低")

    # 使用時間過短
    if avg_duration_min < 5 and avg_duration_min != 0:
        risk_score += 1
        risk_flags.append("short_usage")
        risk_reasons.append("使用時間過短（<5分鐘）")

    # 使用時間過長
    if avg_duration_min > 300:
        risk_score += 1
        risk_flags.append("long_usage")
        risk_reasons.append("使用時間過長（>5小時）")

    # 風險分級
    if risk_score >= 7:
        risk_level = "high_risk"
    elif risk_score >= 3:
        risk_level = "warning"
    else:
        risk_level = "normal"

    risk_reason = "；".join(risk_reasons) if risk_reasons else "無異常"

    return risk_level, risk_flags, risk_reason, risk_score
