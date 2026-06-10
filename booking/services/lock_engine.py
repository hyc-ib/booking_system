from datetime import datetime, timedelta
from django.utils import timezone
from booking.models import Reservation

def get_risk_window_start(profile):
    """
    🔥 風險計算起點
    解鎖後才重新開始算
    """
    if profile.risk_reset_at:
        return profile.risk_reset_at
    return timezone.now() - timedelta(days=3650)  # 10年

def get_user_risk(user, profile):
    now = timezone.localtime()
    start = get_risk_window_start(profile)

    # =========================
    # 未報到
    # =========================
    no_show = Reservation.objects.filter(
        user=user,
        status="no-checkIn",
        start_time__gte=start,
        start_time__lt=now
    ).count()

    # =========================
    # 逾期未還
    # =========================
    overdue = Reservation.objects.filter(
        user=user,
        status="on-going",
        end_time__lt=now,
        start_time__gte=start
    ).count()

    # =========================
    # credit score
    # =========================
    credit_score = 100 - no_show * 3 - overdue * 2
    credit_score = max(0, min(100, credit_score))

    return {
        "no_show": no_show,
        "overdue": overdue,
        "credit_score": credit_score,
    }

def apply_user_risk_lock(profile, risk_level):
    now = timezone.localtime()

    # =========================
    # 🔓 解鎖（重設 risk 起點）
    # =========================
    if profile.risk_locked_until and profile.risk_locked_until <= now:
        profile.risk_locked_until = None
        profile.risk_reset_at = now   # 🔥 關鍵：重設風險起點
        profile.save(update_fields=["risk_locked_until", "risk_reset_at"])

    # =========================
    # 🔒 上鎖
    # =========================
    if risk_level == "high_risk":
        if not profile.risk_locked_until:
            profile.risk_locked_until = now + timedelta(days=30)
            profile.save(update_fields=["risk_locked_until"])


def is_user_locked(profile):
    now = timezone.localtime()

    if not profile.risk_locked_until:
        return False

    if profile.risk_locked_until <= now:
        profile.risk_locked_until = None
        profile.risk_reset_at = now   # 🔥 同步 reset
        profile.save(update_fields=["risk_locked_until", "risk_reset_at"])
        return False

    return True