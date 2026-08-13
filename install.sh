#!/usr/bin/env bash
set -Eeuo pipefail

# ==============================
# VPS Telegram Bot 一键安装脚本
# ==============================

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

INSTALL_DIR="/opt/vpsbot"
CONFIG_FILE="$INSTALL_DIR/config.json"
SERVICE_FILE="/etc/systemd/system/vpsbot.service"
SHORTCUT_CMD="/usr/local/bin/vps-bb"

# 当前安全修复分支；合并到 main 后可改为 main，
# 更推荐后续固定为 release tag 或 commit SHA。
REPO_REF="fix/security-hardening"
GITHUB_VPS_BOT="https://raw.githubusercontent.com/alllike996/vps-bot-manager/${REPO_REF}/vps_bot.py"
GITHUB_VPS_BB="https://raw.githubusercontent.com/alllike996/vps-bot-manager/${REPO_REF}/vps_bb.py"

cleanup_on_error() {
    echo -e "\n${RED}❌ 安装失败，请根据上方错误信息检查。${NC}"
}

trap cleanup_on_error ERR

echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN}      VPS Telegram Bot 一键安装脚本      ${NC}"
echo -e "${GREEN}=========================================${NC}"

# 1. 检查 Root 权限
if [ "${EUID}" -ne 0 ]; then
    echo -e "${RED}❌ 请使用 root 用户运行此脚本：sudo bash install.sh${NC}"
    exit 1
fi

# 2. 防止覆盖不明的同名安装
if [ -e "$SERVICE_FILE" ] || [ -e "$SHORTCUT_CMD" ] || [ -d "$INSTALL_DIR" ]; then
    echo -e "${RED}❌ 检测到已有 vpsbot 文件或安装目录：${NC}"
    [ -e "$SERVICE_FILE" ] && echo -e "${YELLOW}- $SERVICE_FILE${NC}"
    [ -e "$SHORTCUT_CMD" ] && echo -e "${YELLOW}- $SHORTCUT_CMD${NC}"
    [ -d "$INSTALL_DIR" ] && echo -e "${YELLOW}- $INSTALL_DIR${NC}"
    echo -e "${YELLOW}请先确认旧安装状态；若确实要重装，请先通过 vps-bb 卸载或手动备份。${NC}"
    exit 1
fi

# 3. 收集并校验用户输入
echo -e "${YELLOW}请配置机器人信息：${NC}"

read -r -s -p "请输入 Telegram Bot Token: " INPUT_TOKEN
echo

if [[ -z "$INPUT_TOKEN" ]]; then
    echo -e "${RED}❌ Telegram Bot Token 不能为空。${NC}"
    exit 1
fi

# Telegram Bot Token 通常为“数字:字母数字_-”形式。
if [[ ! "$INPUT_TOKEN" =~ ^[0-9]+:[A-Za-z0-9_-]+$ ]]; then
    echo -e "${RED}❌ Telegram Bot Token 格式异常。${NC}"
    exit 1
fi

read -r -p "请输入 Admin ID (数字): " INPUT_ADMIN_ID
if [[ ! "$INPUT_ADMIN_ID" =~ ^[1-9][0-9]*$ ]]; then
    echo -e "${RED}❌ Admin ID 必须是正整数。${NC}"
    exit 1
fi

read -r -p "请输入流量限制阈值(GB，0 为不限制): " INPUT_LIMIT
if [[ ! "$INPUT_LIMIT" =~ ^[0-9]+$ ]]; then
    echo -e "${RED}❌ 流量阈值必须是非负整数。${NC}"
    exit 1
fi

read -r -p "是否开启超标自动关机? (y/n): " INPUT_AUTO_SHUTDOWN
if [[ "$INPUT_AUTO_SHUTDOWN" =~ ^[Yy]$ ]]; then
    AUTO_SHUTDOWN="true"
else
    AUTO_SHUTDOWN="false"
fi

# 4. 安装系统依赖
echo -e "${GREEN}⏳ 正在安装系统依赖...${NC}"

if [ -f /etc/debian_version ]; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq vnstat python3-pip python3-venv curl iproute2
elif [ -f /etc/redhat-release ]; then
    yum install -y vnstat python3-pip curl iproute
else
    echo -e "${RED}❌ 未识别的 Linux 发行版，仅支持 Debian/Ubuntu 与 RHEL/CentOS/Rocky/AlmaLinux。${NC}"
    exit 1
fi

# 5. 获取默认网络接口并初始化 vnStat
echo -e "${GREEN}⏳ 配置网络监控接口...${NC}"

DEFAULT_IFACE="$(ip route get 8.8.8.8 2>/dev/null | awk '{print $5; exit}')"

if [[ -z "$DEFAULT_IFACE" ]]; then
    echo -e "${RED}❌ 无法自动识别默认网络接口。${NC}"
    exit 1
fi

systemctl enable --now vnstat
vnstat -i "$DEFAULT_IFACE" --create 2>/dev/null || true
systemctl restart vnstat

# 6. 创建专用目录并下载脚本
echo -e "${GREEN}⏳ 正在下载脚本文件...${NC}"

install -d -o root -g root -m 700 "$INSTALL_DIR"

curl -fsSL "$GITHUB_VPS_BOT" -o "$INSTALL_DIR/vps_bot.py"
curl -fsSL "$GITHUB_VPS_BB" -o "$INSTALL_DIR/vps_bb.py"

if [ ! -s "$INSTALL_DIR/vps_bot.py" ] || [ ! -s "$INSTALL_DIR/vps_bb.py" ]; then
    echo -e "${RED}❌ 下载的脚本为空。${NC}"
    exit 1
fi

chown root:root "$INSTALL_DIR/vps_bot.py" "$INSTALL_DIR/vps_bb.py"
chmod 700 "$INSTALL_DIR/vps_bot.py" "$INSTALL_DIR/vps_bb.py"

# 7. 配置 Python 虚拟环境与依赖
echo -e "${GREEN}⏳ 安装 Python 依赖库...${NC}"

cd "$INSTALL_DIR"
python3 -m venv venv
"$INSTALL_DIR/venv/bin/python3" -m pip install --upgrade pip
"$INSTALL_DIR/venv/bin/python3" -m pip install "python-telegram-bot>=20.0,<21.0" psutil

chown -R root:root "$INSTALL_DIR/venv"
chmod -R go-rwx "$INSTALL_DIR/venv"

# 8. 安全生成配置文件
# 不直接用 heredoc 拼接 JSON，避免输入中的特殊字符破坏 JSON 格式。
printf '%s\n%s\n%s\n%s\n%s\n' \
    "$INPUT_TOKEN" \
    "$INPUT_ADMIN_ID" \
    "$INPUT_LIMIT" \
    "$AUTO_SHUTDOWN" \
    "$DEFAULT_IFACE" \
| python3 -c '
import json
import sys

token = sys.stdin.readline().rstrip("\n")
admin_id = int(sys.stdin.readline().strip())
limit_gb = int(sys.stdin.readline().strip())
auto_shutdown = sys.stdin.readline().strip().lower() == "true"
interface = sys.stdin.readline().rstrip("\n")

config = {
    "bot_token": token,
    "admin_id": admin_id,
    "limit_gb": limit_gb,
    "auto_shutdown": auto_shutdown,
    "vnstat_interface": interface
}

with open(sys.argv[1], "w", encoding="utf-8") as f:
    json.dump(config, f, indent=4, ensure_ascii=False)
    f.write("\n")
' "$CONFIG_FILE"

chown root:root "$CONFIG_FILE"
chmod 600 "$CONFIG_FILE"

# 尽量减少 Token 在脚本进程内存中的保留时间
unset INPUT_TOKEN

# 9. 创建快捷命令 vps-bb
cat > "$SHORTCUT_CMD" <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
exec "$INSTALL_DIR/venv/bin/python3" "$INSTALL_DIR/vps_bb.py"
EOF

chown root:root "$SHORTCUT_CMD"
chmod 700 "$SHORTCUT_CMD"

# 10. 创建 systemd 服务
echo -e "${GREEN}⏳ 创建后台服务...${NC}"

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

# 11. 启动服务
systemctl daemon-reload
systemctl enable vpsbot
systemctl restart vpsbot

if ! systemctl is-active --quiet vpsbot; then
    echo -e "${RED}❌ Bot 服务启动失败，请执行以下命令查看日志：${NC}"
    echo -e "${YELLOW}journalctl -u vpsbot -n 100 --no-pager${NC}"
    exit 1
fi

echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN}✅ 安装完成！${NC}"
echo -e "${GREEN}机器人状态: $(systemctl is-active vpsbot)${NC}"
echo -e "${YELLOW}快捷命令: sudo vps-bb${NC}"
echo -e "${YELLOW}安装目录: $INSTALL_DIR${NC}"
echo -e "${YELLOW}配置文件: $CONFIG_FILE（权限 600，仅 root 可读）${NC}"
echo -e "${GREEN}=========================================${NC}"
