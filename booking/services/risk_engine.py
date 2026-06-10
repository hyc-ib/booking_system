def detect_user_risk(no_show_count, overdue_count, credit_score, avg_duration_min):

    risk_score = 0
    risk_flags = []
    risk_reasons = []

    # 🔴 未報到
    if no_show_count > 0:
        risk_score += no_show_count * 3
        risk_flags.append("no_show")
        risk_reasons.append(f"未報到 {no_show_count} 次")

    # 🔴 逾期未還
    if overdue_count > 0:
        risk_score += overdue_count * 2
        risk_flags.append("overdue")
        risk_reasons.append(f"逾期未還 {overdue_count} 次")

    # 🔴 信用分數
    if credit_score < 60:
        risk_score += 4
        risk_flags.append("low_credit")
        risk_reasons.append("信用分數過低")

    # 🟡 使用時間異常（短）
    if avg_duration_min < 5 & avg_duration_min != 0:
        risk_score += 2
        risk_flags.append("short_usage")
        risk_reasons.append("使用時間過短（<5分鐘）")

    # 🟡 使用時間異常（長）
    if avg_duration_min > 300:
        risk_score += 2
        risk_flags.append("long_usage")
        risk_reasons.append("使用時間過長（>5小時）")

    # 🔥 分級（重點升級）
    if risk_score >= 7:
        risk_level = "high_risk"
    elif risk_score >= 3:
        risk_level = "warning"
    else:
        risk_level = "normal"

    risk_reason = "；".join(risk_reasons) if risk_reasons else "無異常"

    return risk_level, risk_flags, risk_reason, risk_score