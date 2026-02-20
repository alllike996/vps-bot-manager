import logging
import os
import psutil
import subprocess
import json
import asyncio
import sys
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# ================= 基础配置 =================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, 'config.json')

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

config = {
    "bot_token": "",
    "admin_id": 0,
    "limit_gb": 0,
    "auto_shutdown": False,
    "vnstat_interface": ""
}

# ================= 配置读取 =================

def load_config():
    global config
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                saved_config = json.load(f)
                config.update(saved_config)
            config['admin_id'] = int(config['admin_id'])
            config['limit_gb'] = int(config['limit_gb'])
        except Exception as e:
            logger.error(f"加载配置失败: {e}")
            sys.exit(1)
    else:
        logger.error("配置文件不存在，请先运行 install.sh！")
        sys.exit(1)

def save_config():
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)

# ================= 权限控制 =================

def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != config['admin_id']:
            return
        return await func(update, context)
    return wrapper

# ================= 系统信息 =================

def get_system_status():
    cpu_usage = psutil.cpu_percent(interval=1)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    boot_time = datetime.fromtimestamp(psutil.boot_time()).strftime("%Y-%m-%d %H:%M:%S")

    return (
        f"🖥 **VPS 状态概览**\n"
        f"-------------------\n"
        f"⏱ 开机时间: {boot_time}\n"
        f"🧠 CPU 使用: {cpu_usage}%\n"
        f"🐏 内存: {round(mem.used / (1024**3), 2)}G / {round(mem.total / (1024**3), 2)}G ({mem.percent}%)\n"
        f"💾 硬盘: {round(disk.used / (1024**3), 2)}G / {round(disk.total / (1024**3), 2)}G ({disk.percent}%)\n"
    )

def get_traffic_status():
    try:
        result = subprocess.check_output("vnstat --json", shell=True).decode()
        data = json.loads(result)

        interface = None
        target_iface = config.get('vnstat_interface')

        if target_iface:
            for iface in data['interfaces']:
                if iface['name'] == target_iface:
                    interface = iface
                    break

        if not interface and data['interfaces']:
            interface = data['interfaces'][0]

        if not interface:
            return "⚠️ vnstat 未检测到接口数据。", 0

        name = interface['name']
        current_month = interface['traffic']['month'][-1]

        rx = round(current_month['rx'] / (1024**3), 2)
        tx = round(current_month['tx'] / (1024**3), 2)
        total = round((current_month['rx'] + current_month['tx']) / (1024**3), 2)

        msg = (
            f"📡 **流量统计 (本月)**\n"
            f"-------------------\n"
            f"🔌 接口: {name}\n"
            f"⬇️ 下载: {rx} GB\n"
            f"⬆️ 上传: {tx} GB\n"
            f"📊 总计: {total} GB\n"
        )
        return msg, total

    except Exception as e:
        return f"⚠️ 获取流量失败: {e}", 0

# ================= SSH 实时监听（新增） =================

async def monitor_ssh_login(app: Application):
    log_path = "/var/log/auth.log"
    if not os.path.exists(log_path):
        log_path = "/var/log/secure"

    process = await asyncio.create_subprocess_exec(
        "tail", "-Fn0", log_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL
    )

    while True:
        line = await process.stdout.readline()
        if not line:
            await asyncio.sleep(0.1)
            continue

        text = line.decode()

        if "Accepted password" in text or "Accepted publickey" in text:
            try:
                parts = text.split()
                user = parts[8]
                ip = parts[10]
                auth_type = "password" if "password" in text else "publickey"
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                msg = (
                    f"🚨 **SSH 登录提醒**\n\n"
                    f"👤 用户: {user}\n"
                    f"🌍 IP: {ip}\n"
                    f"🔐 方式: {auth_type}\n"
                    f"⏰ 时间: {now}"
                )

                if user == "root":
                    msg += "\n⚠️ **ROOT 登录**"

                await app.bot.send_message(
                    chat_id=config['admin_id'],
                    text=msg,
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"SSH monitor error: {e}")

# ================= Telegram 交互 =================

@admin_only
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📊 系统状态", callback_data='status'),
         InlineKeyboardButton("📡 流量统计", callback_data='traffic')],
        [InlineKeyboardButton("🔐 SSH 登录记录", callback_data='ssh_logs')],
        [InlineKeyboardButton("⚙️ 设置流量阈值", callback_data='setup_limit')],
        [InlineKeyboardButton("🔄 重启 VPS", callback_data='reboot'),
         InlineKeyboardButton("🛑 关机 VPS", callback_data='shutdown')],
        [InlineKeyboardButton("❌ 关闭菜单", callback_data='close')]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "🤖 **VPS 管理面板**\n请选择操作："

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.from_user.id != config['admin_id']:
        return

    if query.data == 'status':
        msg = get_system_status()

    elif query.data == 'traffic':
        msg, _ = get_traffic_status()

    elif query.data == 'ssh_logs':
        try:
            result = subprocess.check_output(
                "last -n 10 | grep -v reboot",
                shell=True
            ).decode()
            if not result.strip():
                result = "暂无 SSH 登录记录"

            msg = f"📜 **最近 10 次 SSH 登录**\n\n```\n{result}\n```"
        except Exception as e:
            msg = f"⚠️ 获取失败: {e}"

    elif query.data == 'menu':
        await start(update, context)
        return

    elif query.data == 'close':
        await query.delete_message()
        return

    else:
        return

    await query.edit_message_text(
        msg,
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 返回菜单", callback_data='menu')]]
        ),
        parse_mode='Markdown'
    )

# ================= 主程序 =================

async def on_startup(app: Application):
    app.create_task(monitor_ssh_login(app))

def main():
    load_config()

    application = Application.builder().token(config['bot_token']).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))

    application.post_init = on_startup

    print("✅ Bot started polling...")
    application.run_polling()

if __name__ == '__main__':
    main()
