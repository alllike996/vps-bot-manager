#!/usr/bin/env bash
set -Eeuo pipefail

# ==============================
# VPS Telegram Bot 一键安装脚本
# 流量超限仅告警，不自动关机
# ==============================

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

INSTALL_DIR="/opt/vpsbot"
CONFIG_FILE="$INSTALL_DIR/config.json"
SERVICE_FILE="/etc/systemd/system/vpsbot.service"
SHORTCUT_CMD="/usr/local/bin/vps-bb"

# 当前开发分支。
# 合并到 main 后可改为：REPO_REF="main"
# 后续发布正式版本时，建议固定为 Git tag 或 commit SHA。
REPO_REF="fix/security-hardening"

GITHUB_VPS_BOT="https://raw.githubusercontent.com/alllike996/vps-bot-manager/${REPO_REF}/vps_bot.py"
GITHUB_VPS_BB="https://raw.githubusercontent.com/alllike996/vps-bot-manager/${REPO_REF}/vps_bb.py"

cleanup_on_error() {
    echo
    echo -e "${RED}❌ 安装失败，请根据上方错误信息检查。${NC}"
}

trap cleanup_on_error ERR

echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN}      VPS Telegram Bot 一键安装脚本      ${NC}"
echo -e "${GREEN}=========================================${NC}"
echo -e "${YELLOW}提示：流量达到阈值后仅发送 Telegram 告警，不会自动关机。${NC}"
echo

# ==============================
# 1. 检查 Root 权限
# ==============================
if [ "${EUID}" -ne 0 ]; then
    echo -e "${RED}❌ 请使用 root 用户运行此脚本：sudo bash install.sh${NC}"
    exit 1
fi

# ==============================
# 2. 防止覆盖已有安装
# ==============================
if [ -e "$SERVICE_FILE" ] || [ -e "$SHORTCUT_CMD" ] || [ -d "$INSTALL_DIR" ]; then
    echo -e "${RED}❌ 检测到已有 vpsbot 文件或安装目录：${NC}"

    if [ -e "$SERVICE_FILE" ]; then
        echo -e "${YELLOW}- $SERVICE_FILE${NC}"
    fi

    if [ -e "$SHORTCUT_CMD" ]; then
        echo -e "${YELLOW}- $SHORTCUT_CMD${NC}"
    fi

    if [ -d "$INSTALL_DIR" ]; then
        echo -e "${YELLOW}- $INSTALL_DIR${NC}"
    fi

    echo
    echo -e "${YELLOW}请先确认旧安装状态。${NC}"
    echo -e "${YELLOW}若要重装，请先执行：sudo vps-bb${NC}"
    echo -e "${YELLOW}然后选择“卸载管理脚本与后台 Bot”。${NC}"
    exit 1
fi

# ==============================
# 3. 收集并校验配置
# ==============================
echo -e "${YELLOW}请配置机器人信息：${NC}"

read -r -s -p "请输入 Telegram Bot Token（输入不回显）: " INPUT_TOKEN
echo

if [[ -z "$INPUT_TOKEN" ]]; then
    echo -e "${RED}❌ Telegram Bot Token 不能为空。${NC}"
    exit 1
fi

if [[ ! "$INPUT_TOKEN" =~ ^[0-9]+:[A-Za-z0-9_-]+$ ]]; then
    echo -e "${RED}❌ Telegram Bot Token 格式异常。${NC}"
    exit 1
fi

read -r -p "请输入 Admin ID（数字）: " INPUT_ADMIN_ID

if [[ ! "$INPUT_ADMIN_ID" =~ ^[1-9][0-9]*$ ]]; then
    echo -e "${RED}❌ Admin ID 必须是正整数。${NC}"
    exit 1
fi

read -r -p "请输入流量告警阈值（GB，0 为关闭告警）: " INPUT_LIMIT

if [[ ! "$INPUT_LIMIT" =~ ^[0-9]+$ ]]; then
    echo -e "${RED}❌ 流量阈值必须是非负整数。${NC}"
    exit 1
fi

# ==============================
# 4. 安装系统依赖
# ==============================
echo -e "${GREEN}⏳ 正在安装系统依赖...${NC}"

if [ -f /etc/debian_version ]; then
    export DEBIAN_FRONTEND=noninteractive

    apt-get update -qq
    apt-get install -y -qq \
        vnstat \
        python3-pip \
        python3-venv \
        curl \
        iproute2

elif [ -f /etc/redhat-release ]; then
    yum install -y \
        vnstat \
        python3-pip \
        curl \
        iproute

else
    echo -e "${RED}❌ 未识别的 Linux 发行版。${NC}"
    echo -e "${YELLOW}目前仅支持 Debian/Ubuntu 和 RHEL/CentOS/Rocky/AlmaLinux。${NC}"
    exit 1
fi

# ==============================
# 5. 初始化 vnStat
# ==============================
echo -e "${GREEN}⏳ 配置网络监控接口...${NC}"

DEFAULT_IFACE="$(ip route get 8.8.8.8 2>/dev/null | awk '{print $5; exit}')"

if [[ -z "$DEFAULT_IFACE" ]]; then
    echo -e "${RED}❌ 无法自动识别默认网络接口。${NC}"
    exit 1
fi

systemctl enable --now vnstat
vnstat -i "$DEFAULT_IFACE" --create 2>/dev/null || true
systemctl restart vnstat

echo -e "${GREEN}✅ 检测到默认网络接口: ${DEFAULT_IFACE}${NC}"

# ==============================
# 6. 创建专用目录并下载脚本
# ==============================
echo -e "${GREEN}⏳ 正在下载脚本文件...${NC}"

install -d -o root -g root -m 700 "$INSTALL_DIR"

curl -fsSL "$GITHUB_VPS_BOT" -o "$INSTALL_DIR/vps_bot.py"
curl -fsSL "$GITHUB_VPS_BB" -o "$INSTALL_DIR/vps_bb.py"

if [ ! -s "$INSTALL_DIR/vps_bot.py" ]; then
    echo -e "${RED}❌ 主程序下载失败或文件为空。${NC}"
    exit 1
fi

if [ ! -s "$INSTALL_DIR/vps_bb.py" ]; then
    echo -e "${RED}❌ 管理面板下载失败或文件为空。${NC}"
    exit 1
fi

chown root:root "$INSTALL_DIR/vps_bot.py" "$INSTALL_DIR/vps_bb.py"
chmod 700 "$INSTALL_DIR/vps_bot.py" "$INSTALL_DIR/vps_bb.py"

# ==============================
# 7. 创建 Python 虚拟环境并安装依赖
# ==============================
echo -e "${GREEN}⏳ 正在安装 Python 依赖库...${NC}"

cd "$INSTALL_DIR"

python3 -m venv venv

"$INSTALL_DIR/venv/bin/python3" -m pip install --upgrade pip

"$INSTALL_DIR/venv/bin/python3" -m pip install \
    "python-telegram-bot[job-queue]>=20.0,<21.0" \
    psutil

chown -R root:root "$INSTALL_DIR/venv"
chmod -R go-rwx "$INSTALL_DIR/venv"

# ==============================
# 8. 安全生成配置文件
# ==============================
echo -e "${GREEN}⏳ 正在生成配置文件...${NC}"

# 使用 Python 生成 JSON，避免 Token 中的特殊字符破坏 JSON 结构。
# auto_shutdown 固定为 false，仅保留该字段以兼容旧版本配置。
printf '%s\n%s\n%s\n%s\n' \
    "$INPUT_TOKEN" \
    "$INPUT_ADMIN_ID" \
    "$INPUT_LIMIT" \
    "$DEFAULT_IFACE" \
| python3 -c '
import json
import sys

token = sys.stdin.readline().rstrip("\n")
admin_id = int(sys.stdin.readline().strip())
limit_gb = int(sys.stdin.readline().strip())
interface = sys.stdin.readline().rstrip("\n")

config = {
    "bot_token": token,
    "admin_id": admin_id,
    "limit_gb": limit_gb,
    "auto_shutdown": False,
    "vnstat_interface": interface
}

with open(sys.argv[1], "w", encoding="utf-8") as f:
    json.dump(config, f, indent=4, ensure_ascii=False)
    f.write("\n")
' "$CONFIG_FILE"

chown root:root "$CONFIG_FILE"
chmod 600 "$CONFIG_FILE"

# 尽量缩短 Token 在安装脚本进程内存中的保留时间。
unset INPUT_TOKEN

# ==============================
# 9. 创建快捷管理命令
# ==============================
echo -e "${GREEN}⏳ 正在创建快捷管理命令...${NC}"

cat > "$SHORTCUT_CMD" <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
exec "$INSTALL_DIR/venv/bin/python3" "$INSTALL_DIR/vps_bb.py"
EOF

chown root:root "$SHORTCUT_CMD"
chmod 700 "$SHORTCUT_CMD"

# ==============================
# 10. 创建 systemd 服务
# ==============================
echo -e "${GREEN}⏳ 正在创建后台服务...${NC}"

cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=VPS Telegram Manager Bot
Wants=network-online.target
After=network-online.target vnstat.service

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/python3 $INSTALL_DIR/vps_bot.py
Restart=always
RestartSec=10
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true

[Install]
WantedBy=multi-user.target
EOF

chown root:root "$SERVICE_FILE"
chmod 644 "$SERVICE_FILE"

# ==============================
# 11. 启动 Bot 服务
# ==============================
echo -e "${GREEN}⏳ 正在启动 Bot 服务...${NC}"

systemctl daemon-reload
systemctl enable vpsbot
systemctl restart vpsbot

if ! systemctl is-active --quiet vpsbot; then
    echo -e "${RED}❌ Bot 服务启动失败。${NC}"
    echo -e "${YELLOW}请执行以下命令查看错误日志：${NC}"
    echo -e "${YELLOW}journalctl -u vpsbot -n 100 --no-pager${NC}"
    exit 1
fi

echo
echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN}✅ 安装完成！${NC}"
echo -e "${GREEN}机器人状态: $(systemctl is-active vpsbot)${NC}"
echo -e "${YELLOW}快捷命令: sudo vps-bb${NC}"
echo -e "${YELLOW}安装目录: $INSTALL_DIR${NC}"
echo -e "${YELLOW}配置文件: $CONFIG_FILE${NC}"
echo -e "${YELLOW}流量阈值: ${INPUT_LIMIT} GB（仅告警，不自动关机）${NC}"
echo -e "${GREEN}=========================================${NC}"
