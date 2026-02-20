#!/bin/bash

# ==============================
# VPS Telegram Bot 一键安装脚本 (增强事务版)
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

VNSTAT_INSTALLED_NOW=false

rollback() {
  echo -e "${YELLOW}⚠ 是否删除本次已安装内容？(y/n)${NC}"
  read CLEAN_CONFIRM
  if [[ "$CLEAN_CONFIRM" =~ ^[Yy]$ ]]; then
    systemctl stop vpsbot 2>/dev/null || true
    systemctl disable vpsbot 2>/dev/null || true
    rm -f "$SERVICE_FILE"
    rm -rf "$INSTALL_DIR"
    rm -f /usr/local/bin/vps-bb

    if [ "$VNSTAT_INSTALLED_NOW" = true ]; then
      echo -e "${YELLOW}是否卸载本次安装的 vnstat？(y/n)${NC}"
      read REMOVE_VN
      if [[ "$REMOVE_VN" =~ ^[Yy]$ ]]; then
        if [ -f /etc/debian_version ]; then
          apt-get remove -y vnstat -qq
        elif [ -f /etc/redhat-release ]; then
          yum remove -y vnstat
        fi
      fi
    fi

    systemctl daemon-reload
    echo -e "${GREEN}✅ 已清理本次安装内容${NC}"
  fi
  exit 1
}

echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN}      VPS Telegram Bot 一键安装脚本      ${NC}"
echo -e "${GREEN}=========================================${NC}"

# Root 检测
if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}❌ 请使用 root 运行${NC}"
  exit 1
fi

# systemd 检测
if ! command -v systemctl >/dev/null 2>&1; then
  echo -e "${RED}❌ 当前系统不支持 systemd${NC}"
  exit 1
fi

# 重复安装检测
if [ -d "$INSTALL_DIR" ]; then
  echo -e "${YELLOW}⚠ 已存在安装目录，是否覆盖？(y/n)${NC}"
  read CONFIRM
  [[ ! "$CONFIRM" =~ ^[Yy]$ ]] && exit 0
  systemctl stop vpsbot 2>/dev/null || true
fi

# =============================
# 用户输入（循环校验）
# =============================

echo -e "${YELLOW}请配置机器人信息：${NC}"

while true; do
  read -p "请输入 Telegram Bot Token: " INPUT_TOKEN
  [ -n "$INPUT_TOKEN" ] && break
  echo -e "${RED}❌ Token 不能为空${NC}"
done

while true; do
  read -p "请输入 Admin ID (数字): " INPUT_ADMIN_ID
  [[ "$INPUT_ADMIN_ID" =~ ^[0-9]+$ ]] && break
  echo -e "${RED}❌ Admin ID 必须为数字${NC}"
done

while true; do
  read -p "请输入流量限制阈值(GB, 0为不限制): " INPUT_LIMIT
  [[ "$INPUT_LIMIT" =~ ^[0-9]+$ ]] && break
  echo -e "${RED}❌ 流量限制必须为数字${NC}"
done

while true; do
  read -p "是否开启超标自动关机? (y/n): " INPUT_AUTO_SHUTDOWN
  if [[ "$INPUT_AUTO_SHUTDOWN" =~ ^[Yy]$ ]]; then
    AUTO_SHUTDOWN="true"
    break
  elif [[ "$INPUT_AUTO_SHUTDOWN" =~ ^[Nn]$ ]]; then
    AUTO_SHUTDOWN="false"
    break
  else
    echo -e "${RED}❌ 请输入 y 或 n${NC}"
  fi
done

# =============================
# 安装依赖
# =============================

echo -e "${GREEN}⏳ 安装系统依赖...${NC}"

if [ -f /etc/debian_version ]; then
    if ! dpkg -l | grep -q vnstat; then
      VNSTAT_INSTALLED_NOW=true
    fi
    apt-get update -qq
    apt-get install -y vnstat python3-pip python3-venv curl -qq
elif [ -f /etc/redhat-release ]; then
    rpm -q vnstat >/dev/null 2>&1 || VNSTAT_INSTALLED_NOW=true
    yum install -y vnstat python3-pip curl
else
    echo -e "${RED}❌ 不支持的系统${NC}"
    rollback
fi

# =============================
# 初始化 vnstat
# =============================

systemctl enable vnstat
systemctl start vnstat

DEFAULT_IFACE=$(ip route get 8.8.8.8 2>/dev/null | awk '{print $5; exit}')

if [ -z "$DEFAULT_IFACE" ]; then
  echo -e "${RED}❌ 无法自动识别网络接口${NC}"
  rollback
fi

vnstat -i "$DEFAULT_IFACE" --create 2>/dev/null || true
systemctl restart vnstat

# =============================
# 下载程序
# =============================

mkdir -p "$INSTALL_DIR"

echo -e "${GREEN}⏳ 下载脚本...${NC}"

if ! curl -fL "$GITHUB_VPS_BOT" -o "$INSTALL_DIR/vps_bot.py"; then
  echo -e "${RED}❌ 主程序下载失败${NC}"
  rollback
fi

if ! curl -fL "$GITHUB_VPS_BB" -o "$INSTALL_DIR/vps_bb.py"; then
  echo -e "${RED}❌ 管理脚本下载失败${NC}"
  rollback
fi

chmod +x "$INSTALL_DIR/vps_bb.py"

# =============================
# Python 环境
# =============================

cd "$INSTALL_DIR"

if ! python3 -m venv venv; then
  echo -e "${RED}❌ venv 创建失败${NC}"
  rollback
fi

source venv/bin/activate

pip install --upgrade pip || rollback
pip install "python-telegram-bot>=20.0,<21.0" psutil || rollback

deactivate

# =============================
# 生成配置
# =============================

cat > "$INSTALL_DIR/config.json" <<EOF
{
    "bot_token": "$INPUT_TOKEN",
    "admin_id": $INPUT_ADMIN_ID,
    "limit_gb": $INPUT_LIMIT,
    "auto_shutdown": $AUTO_SHUTDOWN,
    "vnstat_interface": "$DEFAULT_IFACE"
}
EOF

# 快捷命令
cat > /usr/local/bin/vps-bb <<EOF
#!/bin/bash
source $INSTALL_DIR/venv/bin/activate
python $INSTALL_DIR/vps_bb.py
EOF

chmod +x /usr/local/bin/vps-bb

# =============================
# 创建服务
# =============================

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
  echo -e "${RED}❌ 服务启动失败${NC}"
  rollback
fi

echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN}✅ 安装完成！${NC}"
echo -e "${GREEN}机器人状态: $(systemctl is-active vpsbot)${NC}"
echo -e "${YELLOW}快捷命令: vps-bb${NC}"
echo -e "${YELLOW}配置文件: $INSTALL_DIR/config.json${NC}"
echo -e "${GREEN}=========================================${NC}"
