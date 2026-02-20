import logging
import os
import psutil
import subprocess
import json
import asyncio
import sys
import threading
import time
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

VERSION = "v3.3.1"

config = {
    "bot_token": "",
    "admin_id": 0,
    "limit_gb": 0,
    "auto_shutdown": False,
    "vnstat_interface": ""
}

# ================= 配置文件操作 =================
def load_config():
    global config
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                saved_config = json.load(f)
                config.update(saved_config)
            config = int(config)
            config = int(config)
        except Exception as e:
            logger.error(f"加载配置失败: {e}")
            sys.exit(1)
    else:
        logger.error("配置文件不存在，请先运行 install.sh 安装脚本！")
        sys.exit(1)

def save_config():
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=4)
    except Exception as e:
        logger.error(f"保存配置失败: {e}")

# ================= 权限装饰器 =================
def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != config:
            return
        return await func(update, context)
    return wrapper

# ================= 系统状态 =================
def get_system_status():
    cpu_usage = psutil.cpu_percent(interval=1)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    boot_time = datetime.fromtimestamp(psutil.boot_time()).strftime("%Y-%m-%d %H:%M:%S")
    msg = (
        f"🖥 **VPS 状态概览**\n"
        f"-------------------\n"
        f"⏱ 开机时间: {boot_time}\n"
        f"🧠 CPU 使用: {cpu_usage}%\n"
        f"🐏 内存: {round(mem.used / (1024**3),2)}G / {round(mem.total / (1024**3),2)}G ({mem.percent}%)\n"
        f"💾 硬盘: {round(disk.used / (1024**3),2)}G / {round(disk.total / (1024**3),2)}G ({disk.percent}%)\n"
    )
    return msg

def get_traffic_status():
    try:
        cmd = "vnstat --json"
        result = subprocess.check_output(cmd, shell=True).decode('utf-8')
        data = json.loads(result)
        interface = None
        target_iface = config.get('vnstat_interface')
        if target_iface:
            for iface in data:
                if iface == target_iface:
                    interface = iface
                    break
        if not interface and data:
            interface = data
        if not interface:
            return "⚠️ vnstat 未检测到接口数据。", 0
        name = interface
        traffic_month = interface.get('traffic', {}).get('month',[])
        if not traffic_month:
            return f"⚠️ 接口 {name} 暂无本月流量记录。", 0
        current_month = traffic_month
        rx = round(current_month / (1024**3), 2)
        tx = round(current_month / (1024**3), 2)
        total = round((current_month + current_month) / (1024**3), 2)
        limit_msg = f"{config} GB" if config > 0 else "无限制"
        auto_off_msg = "✅ 开启" if config else "❌ 关闭"
        msg = (
            f"📡 **流量统计 (本月)**\n"
            f"-------------------\n"
            f"🔌 接口: {name}\n"
            f"⬇️ 下载: {rx} GB\n"
            f"⬆️ 上传: {tx} GB\n"
            f"📊 总计: {total} GB\n"
            f"-------------------\n"
            f"🚫 关机阈值: {limit_msg}\n"
            f"⚡️ 自动关机: {auto_off_msg}"
        )
        return msg, total
    except Exception as e:
        logger.error(f"Traffic check error: {e}")
        return f"⚠️ 获取流量失败: {str(e)}", 0

# ================= SSH 登录监听 =================
async def monitor_ssh_login(app: Application):
    log_path = "/var/log/auth.log" if os.path.exists("/var/log/auth.log") else "/var/log/secure"
    process = await asyncio.create_subprocess_exec(
        "tail", "-Fn0", log_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL
    )
    ip_lock = {}
    while True:
        line = await process.stdout.readline()
        if not line:
            await asyncio.sleep(0.1)
            continue
        text = line.decode()
        if "Accepted password" in text or "Accepted publickey" in text:
            try:
                parts = text.split()
                user = parts
                ip = parts
                now = datetime.now()
                # 防抖: 60秒内同IP不重复通知
                last_time = ip_lock.get(ip)
                if last_time and (now - last_time).total_seconds() < 60:
                    continue
                ip_lock = now
                auth_type = "password" if "password" in text else "publickey"
                msg = (
                    f"🚨 **SSH 登录提醒**\n\n"
                    f"👤 用户: {user}\n"
                    f"🌍 IP: {ip}\n"
                    f"🔐 方式: {auth_type}\n"
                    f"⏰ 时间: {now.strftime('%Y-%m-%d %H:%M:%S')}"
                )
                if user == "root":
                    msg += "\n⚠️ **ROOT 登录**"
                await app.bot.send_message(chat_id=config, text=msg, parse_mode="Markdown")
            except Exception as e:
                logger.error(f"SSH monitor error: {e}")

# ================= Fail2Ban 状态（精准修复版） =================
def get_fail2ban_stats():
    curr_banned = total_banned = 0
    jail_name = "sshd"
    try:
        output = subprocess.check_output(
            f"sudo fail2ban-client status {jail_name}",
            shell=True,
            stderr=subprocess.DEVNULL
        ).decode()

        for line in output.splitlines():
            # 使用 in 判断是否包含关键字
            if "Currently banned:" in line:
                try:
                    # 用冒号分割，取最后一部分，并且去掉空格
                    curr_banned = int(line.split(":").strip())
                except ValueError:
                    curr_banned = 0
            elif "Total banned:" in line:
                try:
                    total_banned = int(line.split(":").strip())
                except ValueError:
                    total_banned = 0

        msg = (
            f"⛔ **Fail2Ban 封禁统计**\n"
            f"🔹 当前封禁 IP 数量: {curr_banned}\n"
            f"🔹 累计封禁 IP 数量: {total_banned}"
        )
        return msg
    except subprocess.CalledProcessError:
        return "⚠️ Fail2Ban 未运行或权限不足"
    except FileNotFoundError:
        return "⚠️ 系统未安装 Fail2Ban"
    except Exception as e:
        return f"⚠️ 获取 Fail2Ban 统计失败: {e}"

# ================= Telegram 面板 =================
@admin_only
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [,,,,
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = f"🤖 **VPS 管理面板 ({VERSION})**\n请选择操作："
    if update.callback_query:
        await update.callback_query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()  # 必须应答，否则客户端会一直转圈
    if query.from_user.id != config:
        return

    if query.data == 'status':
        msg = get_system_status()
    elif query.data == 'traffic':
        msg, _ = get_traffic_status()
    elif query.data == 'ssh_logs':
        try:
            result = subprocess.check_output("last -n 10 | grep -v reboot", shell=True).decode()
            result = result if result.strip() else "暂无 SSH 登录记录"
            msg = f"📜 **最近 10 次 SSH 登录**\n\n```\n{result}\n```"
        except Exception as e:
            msg = f"⚠️ 获取失败: {e}"
    elif query.data == 'ssh_fail_logs':
        try:
            log_path = "/var/log/auth.log" if os.path.exists("/var/log/auth.log") else "/var/log/secure"
            result = subprocess.check_output(f"grep 'Failed password' {log_path} | tail -n 10", shell=True).decode()
            result = result if result.strip() else "暂无 SSH 失败登录记录"
            msg = f"❌ **最近 10 次 SSH 失败登录**\n\n```\n{result}\n```"
        except Exception as e:
            msg = f"⚠️ 获取失败: {e}"
    elif query.data == 'fail2ban':
        msg = get_fail2ban_stats()
    elif query.data == 'setup_limit':
        keyboard = [,,
        ]
        status = f"当前限制: {config}GB\n自动关机: {'开启' if config else '关闭'}"
        await query.edit_message_text(
            f"⚙️ **流量阈值设置**\n{status}\n(达标后将自动执行关机)",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    elif query.data.startswith('set_'):
        val = query.data.split('_')
        if val == 'off':
            config = 0
            config = False
            res = "✅ 已关闭流量限制。"
        else:
            config = int(val)
            config = True
            res = f"✅ 已设置上限为 {val}GB，达标自动关机。"
        save_config()
        await query.answer(res, show_alert=True)
        await start(update, context)
        return
    elif query.data == 'reboot':
        keyboard = [,]
        await query.edit_message_text("⚠️ **高风险操作**\n确定要重启 VPS 吗？", reply_markup=InlineKeyboardMarkup(keyboard))
        return
    elif query.data == 'confirm_reboot':
        await query.edit_message_text("🔄 发送重启命令...", parse_mode='Markdown')
        os.system("reboot")
        return
    elif query.data == 'close':
        await query.delete_message()
        return
    elif query.data == 'menu':
        await start(update, context)
        return

    await query.edit_message_text(
        msg,
        reply_markup=InlineKeyboardMarkup([]),
        parse_mode='Markdown'
    )

# ================= 定时任务 =================
async def check_traffic_job(context: ContextTypes.DEFAULT_TYPE):
    if not config or config <= 0:
        return
    _, total_usage = get_traffic_status()
    if total_usage >= config:
        try:
            await context.bot.send_message(
                chat_id=config,
                text=f"🚨 **流量严重警告**\n\n已用流量: {total_usage}GB\n设定阈值: {config}GB\n\n⚠️ **系统将于 10秒后 自动关机！**"
            )
        except Exception:
            pass
        await asyncio.sleep(10)
        os.system("shutdown -h now")

# ================= 主程序 =================
async def on_startup(app: Application):
    app.create_task(monitor_ssh_login(app))

def main():
    load_config()
    if not config:
        print("Error: Bot Token not configured.")
        return
    application = Application.builder().token(config).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.post_init = on_startup
    if application.job_queue:
        application.job_queue.run_repeating(check_traffic_job, interval=60, first=10)
    print(f"✅ Bot started polling... (版本 {VERSION})")
    application.run_polling()

if __name__ == '__main__':
    main()
