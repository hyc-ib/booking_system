def detect_user_risk(no_show_count, overdue_count, credit_score, avg_duration_min):

    risk_level = "normal"
    risk_flags = []

    # 🔴 高風險未報到
    if no_show_count >= 3:
        risk_flags.append("high_no_show")
        risk_reason = "短期內多次未報到"

    # 🔴 逾期過多
    if overdue_count >= 2:
        risk_flags.append("frequent_overdue")
        risk_reason = "短期內多次逾期還車"

    # 🔴 信用過低
    if credit_score < 60:
        risk_flags.append("low_credit")
        # risk_reason = "信用過低"

    # 🟡 使用異常（太短或太長）
    if avg_duration_min < 5:
        risk_flags.append("suspicious_short_usage")
        risk_reason = "短期內多次使用時間小於5分鐘"

    if avg_duration_min > 300:
        risk_flags.append("suspicious_long_usage")
        risk_reason = "短期內多次使用時間超過5小時"

    # 🔥 判斷等級
    if len(risk_flags) >= 3:
        risk_level = "high_risk"
    elif len(risk_flags) >= 1:
        risk_level = "warning"

    return risk_level, risk_flags, risk_reason