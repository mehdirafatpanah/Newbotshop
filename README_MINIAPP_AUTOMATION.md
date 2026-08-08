# Newbotshop Mini App Automation

این patch برای ریپازیتوری فعلی `mehdirafatpanah/Newbotshop` است.

Commit کن:
- `manage.sh`
- `main.py`
- `requirements.txt`
- `webapp_server.py`
- `webapp/index.html`
- `webapp/app.js`
- `webapp/style.css`

`database.py` را تغییر نده.

بعد از commit:
```bash
bash <(curl -fsSL https://raw.githubusercontent.com/mehdirafatpanah/Newbotshop/main/manage.sh)
```

اگر بات قبلاً نصب است: گزینه 2 برای update، سپس گزینه 10 برای فعال‌سازی Mini App.

پیش‌نیاز فعال‌سازی: دامنه و DNS A به IP سرور، پورت‌های 80 و 443 باز.
