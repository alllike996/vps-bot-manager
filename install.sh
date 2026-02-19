#!/bin/bash

# 颜色定义
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

# 配置参数
INSTALL_DIR="/opt/vpsbot"
SERVICE_FILE="/etc/systemd/system/vpsbot.service"
GITHUB_REPO_URL="https://raw.githubusercontent.com/alllike996/vps-bot-manager/main/vps_bot.py"

echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN}      VPS Telegram Bot 一键安装脚本      ${NC}"
echo -e "${GREEN}=========================================${NC}"

# 1. 检查 Root 权限
if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}❌ 请使用 root 用户运行此脚本 (sudo bash install.sh)${NC}"
  exit 1
fi

# 2. 收集用户输入
echo -e "${YELLOW}请配置机器人信息：${NC}"
read -p "请输入 Telegram Bot Token: " INPUT_TOKEN
read -p "请输入 Admin ID (数字): " INPUT_ADMIN_ID
read -p "请输入流量限制阈值(GB, 0为不限制): " INPUT_LIMIT
read -p "是否开启超标自动关机? (y/n): " INPUT_AUTO_SHUTDOWN

if [[ "$INPUT_AUTO_SHUTDOWN" == "y" || "$INPUT_AUTO_SHUTDOWN" == "Y" ]]; then
    AUTO_SHUTDOWN="true"
else
    AUTO_SHUTDOWN="false"
fi

# 3. 安装系统依赖
echo -e "${GREEN}⏳ 正在安装系统依赖...${NC}"
if [ -f /etc/debian_version ]; then
    apt-get update -qq
    apt-get install -y vnstat python3-pip python3-venv curl -qq
elif [ -f /etc/redhat-release ]; then
    yum install -y vnstat python3-pip curl
fi

# 4. 初始化 vnstat
echo -e "${GREEN}⏳ 配置网络监控接口...${NC}"
systemctl enable vnstat
systemctl start vnstat
# 获取默认网卡
DEFAULT_IFACE=$(ip route get 8.8.8.8 | awk '{print $5; exit}')
# 强制创建接口数据库 (防止报错)
vnstat -i "$DEFAULT_IFACE" --create 2>/dev/null
systemctl restart vnstat

# 5. 创建目录并下载脚本
echo -e "${GREEN}⏳ 正在下载脚本文件...${NC}"
mkdir -p "$INSTALL_DIR"

# 从 GitHub 下载 vps_bot.py
curl -sL "$GITHUB_REPO_URL" -o "$INSTALL_DIR/vps_bot.py"

# 下载 vps_bb.py
curl -sL "https://raw.githubusercontent.com/alllike996/vps-bot-manager/tiga/vps_bb.py" -o "$INSTALL_DIR/vps_bb.py"

# 创建快捷命令
ln -sf $INSTALL_DIR/vps_bb.py /usr/local/bin/vps-bb
chmod +x $INSTALL_DIR/vps_bb.py

# 创建快捷命令使用虚拟环境 Python
cat > /usr/local/bin/vps-bb <<EOF
#!/bin/bash
source $INSTALL_DIR/venv/bin/activate
python $INSTALL_DIR/vps_bb.py
EOF
chmod +x /usr/local/bin/vps-bb

if [ ! -f "$INSTALL_DIR/vps_bot.py" ]; then
    echo -e "${RED}❌ 下载失败！请检查 GitHub 仓库地址是否正确。${NC}"
    exit 1
fi

# 6. 配置 Python 环境
echo -e "${GREEN}⏳ 安装 Python 依赖库...${NC}"
cd "$INSTALL_DIR"
python3 -m venv venv
source venv/bin/activate
# 指定版本以保证稳定性
pip install "python-telegram-bot>=20.0,<21.0" psutil --upgrade
deactivate

# 7. 生成配置文件
cat > "$INSTALL_DIR/config.json" <<EOF
{
    "bot_token": "$INPUT_TOKEN",
    "admin_id": $INPUT_ADMIN_ID,
    "limit_gb": $INPUT_LIMIT,
    "auto_shutdown": $AUTO_SHUTDOWN,
    "vnstat_interface": "$DEFAULT_IFACE"
}
EOF

# 8. 创建 Systemd 服务
echo -e "${GREEN}⏳ 创建后台服务...${NC}"
cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=VPS Telegram Manager Bot
After=network.target vnstat.service

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

# 9. 启动服务
systemctl daemon-reload
systemctl enable vpsbot
systemctl start vpsbot

echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN}✅ 安装完成！${NC}"
echo -e "${GREEN}机器人状态: $(systemctl is-active vpsbot)${NC}"
echo -e "${YELLOW}如需修改配置，请编辑: $INSTALL_DIR/config.json${NC}"
echo -e "${YELLOW}重启命令: systemctl restart vpsbot${NC}"
echo -e "${GREEN}=========================================${NC}"
