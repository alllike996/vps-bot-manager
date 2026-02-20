#!/bin/bash

# ==============================
# VPS Telegram Bot 一键安装脚本 (增强版)
# ==============================

set -e

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

INSTALL_DIR="/opt/vpsbot"
SERVICE_FILE="/etc/systemd/system/vpsbot.service"
GITHUB_VPS_BOT="https://raw.githubusercontent.com/alllike996/vps-bot-manager/tiga/vps_bot.py"
GITHUB_VPS_BB="https://raw.githubusercontent.com/alllike996/vps-bot-manager/tiga/vps_bb.py"

echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN}      VPS Telegram Bot 一键安装脚本      ${NC}"
echo -e "${GREEN}=========================================${NC}"

# 1. Root 权限检测
if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}❌ 请使用 root 用户运行此脚本 (sudo bash install.sh)${NC}"
  exit 1
fi

# 2. systemd 检测
if ! command -v systemctl >/dev/null 2>&1; then
  echo -e "${RED}❌ 当前系统不支持 systemd，无法创建服务${NC}"
  exit 1
fi

# 3. 重复安装检测
if [ -d "$INSTALL_DIR" ]; then
  echo -e "${YELLOW}⚠ 检测到已安装版本，是否覆盖安装？(y/n)${NC}"
  read CONFIRM
  if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
    echo "已取消安装。"
    exit 0
  fi
  systemctl stop vpsbot 2>/dev/null || true
fi

# 4. 用户输入
echo -e "${YELLOW}请配置机器人信息：${NC}"
read -p "请输入 Telegram Bot Token: " INPUT_TOKEN
read -p "请输入 Admin ID (数字): " INPUT_ADMIN_ID
read -p "请输入流量限制阈值(GB, 0为不限制): " INPUT_LIMIT
read -p "是否开启超标自动关机? (y/n): " INPUT_AUTO_SHUTDOWN

# 输入校验
if [ -z "$INPUT_TOKEN" ]; then
  echo -e "${RED}❌ Token 不能为空${NC}"
  exit 1
fi

if ! [[ "$INPUT_ADMIN_ID" =~ ^[0-9]+$ ]]; then
  echo -e "${RED}❌ Admin ID 必须为数字${NC}"
  exit 1
fi

if ! [[ "$INPUT_LIMIT" =~ ^[0-9]+$ ]]; then
  echo -e "${RED}❌ 流量限制必须为数字${NC}"
  exit 1
fi

if [[ "$INPUT_AUTO_SHUTDOWN" =~ ^[Yy]$ ]]; then
  AUTO_SHUTDOWN="true"
else
  AUTO_SHUTDOWN="false"
fi

# 5. 安装系统依赖
echo -e "${GREEN}⏳ 正在安装系统依赖...${NC}"
if [ -f /etc/debian_version ]; then
    apt-get update -qq
    apt-get install -y vnstat python3-pip python3-venv curl -qq
elif [ -f /etc/redhat-release ]; then
    yum install -y vnstat python3-pip curl
else
    echo -e "${RED}❌ 不支持的 Linux 发行版${NC}"
    exit 1
fi

# 6. 初始化 vnstat
echo -e "${GREEN}⏳ 配置网络监控接口...${NC}"
systemctl enable vnstat
systemctl start vnstat

DEFAULT_IFACE=$(ip route get 8.8.8.8 2>/dev/null | awk '{print $5; exit}')

if [ -z "$DEFAULT_IFACE" ]; then
  echo -e "${RED}❌ 无法自动识别网络接口${NC}"
  exit 1
fi

vnstat -i "$DEFAULT_IFACE" --create 2>/dev/null || true
systemctl restart vnstat

# 7. 创建目录
mkdir -p "$INSTALL_DIR"

# 8. 下载脚本（带校验）
echo -e "${GREEN}⏳ 正在下载脚本文件...${NC}"

curl -fL "$GITHUB_VPS_BOT" -o "$INSTALL_DIR/vps_bot.py" || {
  echo -e "${RED}❌ 主程序下载失败${NC}"
  exit 1
}

curl -fL "$GITHUB_VPS_BB" -o "$INSTALL_DIR/vps_bb.py" || {
  echo -e "${RED}❌ 管理脚本下载失败${NC}"
  exit 1
}

chmod +x "$INSTALL_DIR/vps_bb.py"

if [ ! -s "$INSTALL_DIR/vps_bot.py" ]; then
  echo -e "${RED}❌ 主程序文件为空${NC}"
  exit 1
fi

# 9. Python 虚拟环境
echo -e "${GREEN}⏳ 创建 Python 虚拟环境...${NC}"
cd "$INSTALL_DIR"

python3 -m venv venv || {
  echo -e "${RED}❌ venv 创建失败${NC}"
  exit 1
}

source venv/bin/activate

pip install --upgrade pip || {
  echo -e "${RED}❌ pip 升级失败${NC}"
  exit 1
}

pip install "python-telegram-bot>=20.0,<21.0" psutil || {
  echo -e "${RED}❌ Python 依赖安装失败${NC}"
  exit 1
}

deactivate

# 10. 生成配置文件
cat > "$INSTALL_DIR/config.json" <<EOF
{
    "bot_token": "$INPUT_TOKEN",
    "admin_id": $INPUT_ADMIN_ID,
    "limit_gb": $INPUT_LIMIT,
    "auto_shutdown": $AUTO_SHUTDOWN,
    "vnstat_interface": "$DEFAULT_IFACE"
}
EOF

# 11. 创建快捷命令
cat > /usr/local/bin/vps-bb <<EOF
#!/bin/bash
source $INSTALL_DIR/venv/bin/activate
python $INSTALL_DIR/vps_bb.py
EOF

chmod +x /usr/local/bin/vps-bb

# 12. 创建 systemd 服务（优化网络等待）
echo -e "${GREEN}⏳ 创建后台服务...${NC}"

cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=VPS Telegram Manager Bot
After=network-online.target vnstat.service
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/python3 $INSTALL_DIR/vps_bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable vpsbot
systemctl restart vpsbot

sleep 2

if ! systemctl is-active --quiet vpsbot; then
  echo -e "${RED}❌ 服务启动失败，请检查日志：journalctl -u vpsbot -f${NC}"
  exit 1
fi

echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN}✅ 安装完成！${NC}"
echo -e "${GREEN}机器人状态: $(systemctl is-active vpsbot)${NC}"
echo -e "${YELLOW}快捷命令: vps-bb${NC}"
echo -e "${YELLOW}配置文件: $INSTALL_DIR/config.json${NC}"
echo -e "${GREEN}=========================================${NC}"
