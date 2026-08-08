#!/bin/bash
# ============================================================================
# Newbotshop Management Engine
# Install / Update / Mini App / Status / Logs / Uninstall
# ============================================================================

REPO_URL="https://github.com/mehdirafatpanah/Newbotshop.git"
INSTALL_DIR="$HOME/v2ray_bot"
SERVICE_NAME="v2raybot"
BRAND_NAME="VPN HUNTER"
VERSION="v1.1"

export DEBIAN_FRONTEND=noninteractive
export NEEDRESTART_MODE=a
export NEEDRESTART_SUSPEND=1

MINIAPP_NGINX_NAME="newbotshop-miniapp"
MINIAPP_NGINX_CONF="/etc/nginx/sites-available/${MINIAPP_NGINX_NAME}"
MINIAPP_NGINX_LINK="/etc/nginx/sites-enabled/${MINIAPP_NGINX_NAME}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; MAGENTA='\033[0;35m'; CYAN='\033[0;36m'
BOLD='\033[1m'; DIM='\033[2m'; RESET='\033[0m'

pause() { echo ""; read -rp "برای بازگشت به منو، Enter را بزن..." _; }

ensure_figlet() {
    if ! command -v figlet &>/dev/null; then
        sudo apt-get update -qq
        sudo apt-get install -y -qq figlet >/dev/null 2>&1 || true
    fi
}

print_banner() {
    clear
    echo -e "${MAGENTA}╔══════════════════════════════════════════════════════════╗${RESET}"
    if command -v figlet &>/dev/null; then
        echo -e "${CYAN}${BOLD}$(figlet -f standard "$BRAND_NAME" 2>/dev/null)${RESET}"
    else
        echo -e "${CYAN}${BOLD}                     $BRAND_NAME${RESET}"
    fi
    echo -e "${YELLOW}                 B O T   M A N A G E M E N T   $VERSION${RESET}"
    echo -e "${MAGENTA}╚══════════════════════════════════════════════════════════╝${RESET}"
    echo ""
}

env_get() {
    local key="$1"
    [ -f "$INSTALL_DIR/.env" ] || return 0
    grep -E "^${key}=" "$INSTALL_DIR/.env" 2>/dev/null | tail -n1 | cut -d'=' -f2-
}

env_set() {
    local key="$1" value="$2"
    touch "$INSTALL_DIR/.env"
    if grep -qE "^${key}=" "$INSTALL_DIR/.env"; then
        sed -i "s|^${key}=.*|${key}=${value}|" "$INSTALL_DIR/.env"
    else
        printf '%s=%s\n' "$key" "$value" >> "$INSTALL_DIR/.env"
    fi
}

ensure_miniapp_env_defaults() {
    [ -n "$(env_get MINIAPP_ENABLED)" ] || env_set MINIAPP_ENABLED "0"
    [ -n "$(env_get WEBAPP_HOST)" ] || env_set WEBAPP_HOST "127.0.0.1"
    [ -n "$(env_get WEBAPP_PORT)" ] || env_set WEBAPP_PORT "8080"
}

print_status_line() {
    if [ ! -d "$INSTALL_DIR" ]; then
        echo -e "System Status: ${YELLOW}نصب نشده${RESET}"
    elif systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
        echo -e "System Status: ${GREEN}${BOLD}Engine Ready ✅ (بات در حال اجراست)${RESET}"
    else
        echo -e "System Status: ${RED}${BOLD}متوقف ⛔️${RESET}"
    fi
    if [ -f "$INSTALL_DIR/.env" ]; then
        local enabled url
        enabled="$(env_get MINIAPP_ENABLED)"; url="$(env_get WEBAPP_URL)"
        if [ "$enabled" = "1" ]; then
            echo -e "Mini App: ${GREEN}فعال ✅${RESET} ${DIM}${url}${RESET}"
        else
            echo -e "Mini App: ${YELLOW}غیرفعال ⛔️${RESET}"
        fi
    fi
    echo -e "${CYAN}──────────────────────────────────────────────────────────────${RESET}"
}

ensure_project() {
    if [ ! -d "$INSTALL_DIR/.git" ]; then
        echo -e "${RED}⛔️ پروژه نصب نشده. ابتدا گزینه ۱ را اجرا کن.${RESET}"
        return 1
    fi
}

write_systemd_service() {
    local user
    user="$(whoami)"
    sudo bash -c "cat > /etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=Newbotshop Telegram Sales Bot + Mini App
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/python3 $INSTALL_DIR/main.py
Restart=always
RestartSec=5
User=$user
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF
    sudo systemctl daemon-reload
    sudo systemctl enable "$SERVICE_NAME" >/dev/null 2>&1
}

install_bot() {
    echo -e "${CYAN}📦 بررسی پیش‌نیازها...${RESET}"
    sudo apt-get update -qq
    sudo apt-get install -y -qq git python3 python3-pip python3-venv figlet curl >/dev/null

    if [ -d "$INSTALL_DIR/.git" ]; then
        cd "$INSTALL_DIR" || return
        git pull --ff-only || { echo -e "${RED}❌ git pull ناموفق بود.${RESET}"; return; }
    else
        git clone "$REPO_URL" "$INSTALL_DIR" || return
        cd "$INSTALL_DIR" || return
    fi

    [ -d venv ] || python3 -m venv venv
    source venv/bin/activate
    pip install --upgrade pip >/dev/null 2>&1
    pip install -r requirements.txt --quiet
    deactivate

    if [ ! -f "$INSTALL_DIR/.env" ]; then
        echo -e "${YELLOW}${BOLD}🔑 اطلاعات بات:${RESET}"
        read -rp "توکن بات: " BOT_TOKEN_INPUT
        read -rp "آیدی عددی ادمین: " OWNER_ID_INPUT
        cat > "$INSTALL_DIR/.env" <<EOF
BOT_TOKEN=$BOT_TOKEN_INPUT
OWNER_ID=$OWNER_ID_INPUT
MINIAPP_ENABLED=0
WEBAPP_HOST=127.0.0.1
WEBAPP_PORT=8080
EOF
    else
        ensure_miniapp_env_defaults
    fi

    write_systemd_service
    sudo systemctl restart "$SERVICE_NAME"
    sleep 2

    if systemctl is-active --quiet "$SERVICE_NAME"; then
        echo -e "${GREEN}${BOLD}✅ نصب کامل شد و بات در حال اجراست.${RESET}"
    else
        echo -e "${RED}⚠️ بات اجرا نشد:${RESET}"
        sudo journalctl -u "$SERVICE_NAME" -n 50 --no-pager
    fi
}

update_bot() {
    ensure_project || return
    cd "$INSTALL_DIR" || return
    echo -e "${CYAN}🔄 دریافت آخرین نسخه...${RESET}"
    git pull --ff-only || { echo -e "${RED}❌ git pull ناموفق بود.${RESET}"; return; }
    source venv/bin/activate
    pip install -r requirements.txt --quiet
    deactivate
    ensure_miniapp_env_defaults
    write_systemd_service
    sudo systemctl restart "$SERVICE_NAME"
    sleep 2
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        echo -e "${GREEN}✅ آپدیت انجام شد.${RESET}"
    else
        echo -e "${RED}⚠️ سرویس اجرا نشد.${RESET}"
        sudo journalctl -u "$SERVICE_NAME" -n 50 --no-pager
    fi
}

install_miniapp_web_stack() {
    sudo apt-get update -qq
    sudo apt-get install -y -qq nginx certbot python3-certbot-nginx curl >/dev/null || return 1
    sudo systemctl enable nginx >/dev/null 2>&1
    sudo systemctl start nginx
}

configure_miniapp_nginx() {
    local domain="$1"
    sudo bash -c "cat > '$MINIAPP_NGINX_CONF'" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name $domain;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        client_max_body_size 10M;
        proxy_read_timeout 60s;
        proxy_send_timeout 60s;
    }
}
EOF
    sudo ln -sf "$MINIAPP_NGINX_CONF" "$MINIAPP_NGINX_LINK"
    sudo nginx -t && sudo systemctl reload nginx
}

activate_miniapp() {
    ensure_project || return
    cd "$INSTALL_DIR" || return
    ensure_miniapp_env_defaults

    echo ""
    echo -e "${MAGENTA}${BOLD}🛍️ فعال‌سازی Telegram Mini App${RESET}"
    read -rp "دامنه Mini App (مثال: shop.example.com): " DOMAIN
    DOMAIN="$(echo "$DOMAIN" | sed 's#https\?://##; s#/$##; s/[[:space:]]//g')"

    if [ -z "$DOMAIN" ]; then
        echo -e "${RED}❌ دامنه خالی است.${RESET}"; return
    fi
    if ! [[ "$DOMAIN" =~ ^[A-Za-z0-9.-]+\.[A-Za-z]{2,}$ ]]; then
        echo -e "${RED}❌ فرمت دامنه معتبر نیست.${RESET}"; return
    fi

    echo -e "${YELLOW}⚠️ رکورد A دامنه باید به IP همین سرور اشاره کند و پورت‌های 80/443 باز باشند.${RESET}"
    read -rp "DNS آماده است؟ برای ادامه yes بنویس: " ok
    [ "$ok" = "yes" ] || { echo -e "${YELLOW}لغو شد.${RESET}"; return; }

    install_miniapp_web_stack || { echo -e "${RED}❌ نصب Nginx/Certbot ناموفق بود.${RESET}"; return; }
    configure_miniapp_nginx "$DOMAIN" || { echo -e "${RED}❌ تنظیم Nginx ناموفق بود.${RESET}"; return; }

    echo -e "${CYAN}🔐 دریافت SSL...${RESET}"
    sudo certbot --nginx --non-interactive --agree-tos \
        --register-unsafely-without-email -d "$DOMAIN" --redirect || {
        echo -e "${RED}❌ دریافت SSL ناموفق بود. DNS و پورت 80 را بررسی کن.${RESET}"
        return
    }

    env_set MINIAPP_ENABLED "1"
    env_set WEBAPP_URL "https://${DOMAIN}"
    env_set WEBAPP_HOST "127.0.0.1"
    env_set WEBAPP_PORT "8080"

    source venv/bin/activate
    pip install -r requirements.txt --quiet
    deactivate
    write_systemd_service
    sudo systemctl restart "$SERVICE_NAME"
    sleep 3

    local code
    code="$(curl -ks -o /dev/null -w '%{http_code}' --max-time 15 "https://${DOMAIN}/" || true)"
    if [ "$code" = "200" ]; then
        echo -e "${GREEN}${BOLD}✅ Mini App با موفقیت فعال شد.${RESET}"
        echo -e "🌐 URL: ${CYAN}https://${DOMAIN}${RESET}"
        echo -e "🔐 SSL: ${GREEN}Active ✅${RESET}"
        echo -e "⚡ API: ${GREEN}Running ✅${RESET}"
    else
        echo -e "${YELLOW}⚠️ Mini App فعال شد ولی تست HTTPS کد $code داد.${RESET}"
    fi
}

disable_miniapp() {
    ensure_project || return
    cd "$INSTALL_DIR" || return
    env_set MINIAPP_ENABLED "0"
    sudo systemctl restart "$SERVICE_NAME"
    echo -e "${GREEN}✅ Mini App غیرفعال شد.${RESET}"
}

manage_miniapp() {
    ensure_project || return
    while true; do
        clear
        echo -e "${MAGENTA}╔══════════════════════════════════════════════════════════╗${RESET}"
        echo -e "${CYAN}${BOLD}                    MINI APP MANAGER${RESET}"
        echo -e "${MAGENTA}╚══════════════════════════════════════════════════════════╝${RESET}"
        echo ""
        local enabled url
        enabled="$(env_get MINIAPP_ENABLED)"
        url="$(env_get WEBAPP_URL)"
        echo -e "Status: $([ "$enabled" = "1" ] && echo "${GREEN}فعال ✅${RESET}" || echo "${YELLOW}غیرفعال ⛔️${RESET}")"
        [ -n "$url" ] && echo -e "URL: ${CYAN}$url${RESET}"
        echo ""
        if [ "$enabled" = "1" ]; then
            echo -e "${BLUE}[1]${RESET} » تست Mini App"
            echo -e "${BLUE}[2]${RESET} » ری‌استارت"
            echo -e "${BLUE}[3]${RESET} » لاگ"
            echo -e "${BLUE}[4]${RESET} » غیرفعال‌سازی"
        else
            echo -e "${BLUE}[1]${RESET} » فعال‌سازی Mini App"
        fi
        echo -e "${BLUE}[0]${RESET} » بازگشت"
        read -rp "انتخاب: " c
        if [ "$enabled" = "1" ]; then
            case "$c" in
                1) code="$(curl -ks -o /dev/null -w '%{http_code}' --max-time 15 "${url%/}/" || true)"; echo "HTTP: $code"; pause ;;
                2) sudo systemctl restart "$SERVICE_NAME"; echo -e "${GREEN}✅ ری‌استارت شد.${RESET}"; pause ;;
                3) sudo journalctl -u "$SERVICE_NAME" -f ;;
                4) disable_miniapp; pause ;;
                0) return ;;
                *) sleep 1 ;;
            esac
        else
            case "$c" in
                1) activate_miniapp; pause ;;
                0) return ;;
                *) sleep 1 ;;
            esac
        fi
    done
}

uninstall_bot() {
    echo -e "${RED}${BOLD}⚠️ سرویس بات حذف می‌شود.${RESET}"
    read -rp "برای تایید yes بنویس: " confirm
    [ "$confirm" = "yes" ] || return

    sudo systemctl stop "$SERVICE_NAME" 2>/dev/null || true
    sudo systemctl disable "$SERVICE_NAME" 2>/dev/null || true
    sudo rm -f "/etc/systemd/system/${SERVICE_NAME}.service"
    sudo systemctl daemon-reload

    # Remove only this project's Nginx config.
    sudo rm -f "$MINIAPP_NGINX_LINK" "$MINIAPP_NGINX_CONF"
    sudo nginx -t >/dev/null 2>&1 && sudo systemctl reload nginx >/dev/null 2>&1 || true

    echo -e "${GREEN}✅ سرویس حذف شد.${RESET}"
    read -rp "فایل‌های پروژه و دیتابیس هم پاک شوند؟ (yes): " confirm2
    if [ "$confirm2" = "yes" ]; then
        rm -rf "$INSTALL_DIR"
        echo -e "${GREEN}✅ فایل‌های پروژه هم حذف شدند.${RESET}"
    fi
}

view_status() { sudo systemctl status "$SERVICE_NAME" --no-pager -l || true; }
view_logs() { echo -e "${CYAN}Ctrl+C برای خروج${RESET}"; sudo journalctl -u "$SERVICE_NAME" -f; }
restart_bot() { sudo systemctl restart "$SERVICE_NAME"; echo -e "${GREEN}✅ ری‌استارت شد.${RESET}"; }
stop_bot() { sudo systemctl stop "$SERVICE_NAME"; echo -e "${YELLOW}⛔️ متوقف شد.${RESET}"; }

show_stats() {
    if [ ! -f "$INSTALL_DIR/bot_database.db" ]; then echo -e "${RED}دیتابیسی پیدا نشد.${RESET}"; return; fi
    cd "$INSTALL_DIR" || return
    source venv/bin/activate
    python3 - <<'PYEOF'
import database as db
s = db.get_stats()
print(f"\n👥 تعداد کاربران: {s['users']}")
print(f"⏳ سفارش‌های در انتظار: {s['pending']}")
print(f"✅ سفارش‌های تایید شده: {s['approved']}")
print(f"❌ سفارش‌های رد شده: {s['rejected']}")
print(f"💰 مجموع فروش: {s['revenue']:,} تومان\n")
PYEOF
    deactivate
}

edit_env() {
    ensure_project || return
    read -rp "توکن جدید بات (Enter = بدون تغییر): " NEW_TOKEN
    read -rp "آیدی عددی جدید ادمین (Enter = بدون تغییر): " NEW_OWNER
    local cur_token cur_owner
    cur_token="$(env_get BOT_TOKEN)"; cur_owner="$(env_get OWNER_ID)"
    [ -n "$NEW_TOKEN" ] && cur_token="$NEW_TOKEN"
    [ -n "$NEW_OWNER" ] && cur_owner="$NEW_OWNER"
    env_set BOT_TOKEN "$cur_token"
    env_set OWNER_ID "$cur_owner"
    ensure_miniapp_env_defaults
    sudo systemctl restart "$SERVICE_NAME"
    echo -e "${GREEN}✅ ذخیره و ری‌استارت شد.${RESET}"
}

ensure_figlet
while true; do
    print_banner
    print_status_line
    echo ""
    echo -e "${BLUE}[1]${RESET} » ${GREEN}نصب کامل بات${RESET}"
    echo -e "${BLUE}[2]${RESET} » ${GREEN}آپدیت بات${RESET}"
    echo -e "${BLUE}[3]${RESET} » ${RED}حذف کامل بات${RESET}"
    echo -e "${CYAN}──────────────────────────────────────────────────────────────${RESET}"
    echo -e "${BLUE}[4]${RESET} » ${GREEN}مشاهده وضعیت بات${RESET}"
    echo -e "${BLUE}[5]${RESET} » ${GREEN}مشاهده لاگ زنده${RESET}"
    echo -e "${BLUE}[6]${RESET} » ${GREEN}ری‌استارت بات${RESET}"
    echo -e "${BLUE}[7]${RESET} » ${GREEN}توقف بات${RESET}"
    echo -e "${CYAN}──────────────────────────────────────────────────────────────${RESET}"
    echo -e "${YELLOW}[8]${RESET} » ${GREEN}مشاهده آمار فروش${RESET}"
    echo -e "${YELLOW}[9]${RESET} » ${GREEN}تغییر توکن یا آیدی ادمین${RESET}"
    echo -e "${CYAN}──────────────────────────────────────────────────────────────${RESET}"
    echo -e "${MAGENTA}[10]${RESET} » ${GREEN}🛍️ فعال‌سازی Mini App${RESET}"
    echo -e "${MAGENTA}[11]${RESET} » ${GREEN}⚙️ مدیریت Mini App${RESET}"
    echo -e "${CYAN}──────────────────────────────────────────────────────────────${RESET}"
    echo -e "${RED}[0]${RESET} » ${GREEN}خروج${RESET}"
    echo ""
    read -rp "Enter choice [0-11]: " choice
    case "$choice" in
        1) install_bot; pause ;;
        2) update_bot; pause ;;
        3) uninstall_bot; pause ;;
        4) view_status; pause ;;
        5) view_logs ;;
        6) restart_bot; pause ;;
        7) stop_bot; pause ;;
        8) show_stats; pause ;;
        9) edit_env; pause ;;
        10) activate_miniapp; pause ;;
        11) manage_miniapp; pause ;;
        0) echo -e "${CYAN}خدانگهدار 👋${RESET}"; exit 0 ;;
        *) echo -e "${RED}گزینه نامعتبر است.${RESET}"; sleep 1 ;;
    esac
done
