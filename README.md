# 🚗 公務車預約系統（Booking System）

一套基於 Django 開發的公務車預約與管理系統，提供車輛預約、使用紀錄、風險控管（No-show / Overdue）與使用者管理功能。

---

## 📌 系統特色

- 車輛預約與管理
- 使用者登入與權限系統
- 預約時間區間管理（開始 / 結束時間）
- 未報到 / 逾期未還自動偵測
- 風險等級系統（Risk Engine）
- 使用行為分析（平均使用時間等）

---

## 🛠 技術架構

- Backend：Django
- Database：SQLite / PostgreSQL
- Frontend：Django Templates (HTML / CSS)
- Language：Python 3.x
- Version Control：Git

---

## 📂 專案結構
```bash
booking_system/
├── booking/
│   ├── views.py
│   ├── models.py
│   ├── urls.py
│   ├── services/
│   │   └── risk_engine.py
│   └── templates/
├── users/
├── manage.py
└── README.md
```
---

## ⚙️ 執行方式

### 1️⃣ 資料庫初始化
```bash
python manage.py migrate
```

### 2️⃣ 啟動伺服器
```bash
python manage.py runserver
```

--- 

## 🚙 核心功能說明
### 🚗 車輛預約

使用者可選擇車輛並設定借用時間：

- 開始時間 
- 結束時間

系統會自動檢查是否有時間衝突。

### ⚠️ 逾期未還（Overdue）

當：

- 狀態 = 使用中
- 結束時間 < 現在時間

即判定為逾期未還

### 🧠 風險評分系統（Risk Engine）

系統會依據以下指標計算風險：

- No-show 次數
- Overdue 次數
- 平均使用時間

風險等級：

- normal（正常）
- warning（警告）
- high risk（高風險）
