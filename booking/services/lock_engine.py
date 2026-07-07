from datetime import timedelta
from django.utils import timezone


def apply_user_risk_lock(profile, risk_level):
    now = timezone.localtime()

    # =========================
    # 🔒 上鎖
    # =========================
    if risk_level == "high_risk":
        if not profile.risk_locked_until:
            profile.risk_locked_until = now + timedelta(days=30)
            profile.save(update_fields=["risk_locked_until"])

    # =========================
    # 🔓 解鎖（重設 risk 起點）
    # =========================
    if profile.risk_locked_until and profile.risk_locked_until <= now:
        profile.risk_locked_until = None
        profile.risk_reset_at = now + timedelta(seconds=10)
        profile.save(update_fields=["risk_locked_until", "risk_reset_at"])


def is_user_locked(profile):
    now = timezone.localtime()

    if not profile.risk_locked_until:
        return False

    if profile.risk_locked_until <= now:
        return False

    return True
