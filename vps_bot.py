import logging
import os
import psutil
import subprocess
import json
import asyncio
import sys
import re
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

VERSION = "v3.8.0"

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
            config['admin_id'] = int(config['admin_id'])
            config['limit_gb'] = int(config['limit_gb'])
        except Exception as e:
            logger.error(f"加载配置失败: {e}")
            sys.exit(1)
    else:
        logger.info("配置文件不存在，将首次运行提示输入 Token 和管理员 ID")
        config['bot_token'] = input("请输入 Telegram Bot Token: ").strip()
        config['admin_id'] = int(input("请输入管理员 Telegram ID: ").strip())
        save_config()

def save_config():
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=4)
    except Exception as e:
        logger.error(f"保存配置失败: {e}")

# ================= 权限装饰器 =================
def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != config['admin_id']:
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

# ================= 流量状态 =================
def get_traffic_status():
    try:
        cmd = "vnstat --json"
        result = subprocess.check_output(cmd, shell=True).decode('utf-8')
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
        traffic_month = interface.get('traffic', {}).get('month', [])
        if not traffic_month:
            return f"⚠️ 接口 {name} 暂无本月流量记录。", 0
        current_month = traffic_month[-1]
        rx = round(current_month['rx'] / (1024**3), 2)
        tx = round(current_month['tx'] / (1024**3), 2)
        total = round((current_month['rx'] + current_month['tx']) / (1024**3), 2)
        limit_msg = f"{config['limit_gb']} GB" if config['limit_gb'] > 0 else "无限制"
        auto_off_msg = "✅ 开启" if config['auto_shutdown'] else "❌ 关闭"
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
    pattern = re.compile(r'Accepted (password|publickey) for (\S+) from (\S+)')
    while True:
        line = await process.stdout.readline()
        if not line:
            await asyncio.sleep(0.1)
            continue
        text = line.decode()
        match = pattern.search(text)
        if match:
            auth_type, user, ip = match.groups()
            now = datetime.now()
            last_time = ip_lock.get(ip)
            if last_time and (now - last_time).total_seconds() < 60:
                continue
            ip_lock[ip] = now
            msg = (
                f"🚨 **SSH 登录提醒**\n\n"
                f"👤 用户: {user}\n"
                f"🌍 IP: {ip}\n"
                f"🔐 方式: {auth_type}\n"
                f"⏰ 时间: {now.strftime('%Y-%m-%d %H:%M:%S')}"
            )
            if user == "root":
                msg += "\n⚠️ **ROOT 登录**"
            try:
                await app.bot.send_message(chat_id=config['admin_id'], text=msg, parse_mode="Markdown")
            except Exception as e:
                logger.error(f"SSH monitor error: {e}")

# ================= Fail2Ban 状态 =================
def get_fail2ban_stats():
    try:
        curr_banned = 0
        jail_name = "sshd"
        try:
            output = subprocess.check_output(f"sudo fail2ban-client status {jail_name}", shell=True).decode()
            for l in output.splitlines():
                if "Currently banned" in l:
                    curr_banned = int(l.strip().split()[-1])
        except Exception:
            pass
        log_path = "/var/log/fail2ban.log"
        banned_ips = set()
        if os.path.exists(log_path):
            with open(log_path) as f:
                for line in f:
                    if "Ban" in line:
                        banned_ips.add(line.strip().split()[-1])
        total_banned = len(banned_ips)
        return f"⛔ **Fail2Ban 封禁统计**\n🔹 当前封禁 IP 数量: {curr_banned}\n🔹 累计封禁 IP 数量: {total_banned}"
    except Exception as e:
        return f"⚠️ 获取 Fail2Ban 统计失败: {e}"

# ================= Telegram 面板 =================
@admin_only
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📊 系统状态", callback_data='status'),
         InlineKeyboardButton("📡 流量统计", callback_data='traffic')],
        [InlineKeyboardButton("🔐 SSH 登录记录", callback_data='ssh_logs'),
         InlineKeyboardButton("❌ SSH 失败记录", callback_data='ssh_fail_logs')],
        [InlineKeyboardButton("⛔ Fail2Ban 封禁统计", callback_data='fail2ban')],
        [InlineKeyboardButton("⚙️ 设置流量阈值", callback_data='setup_limit')],
        [InlineKeyboardButton("🧹 清理缓存日志", callback_data='clean_logs')],
        [InlineKeyboardButton("🔄 重启 VPS", callback_data='reboot'),
         InlineKeyboardButton("🛑 立即关机", callback_data='shutdown')],
        [InlineKeyboardButton("❌ 关闭菜单", callback_data='close')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = f"🤖 **VPS 管理面板 ({VERSION})**\n请选择操作："
    if update.callback_query:
        await update.callback_query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')

# ================= 清理缓存日志功能 =================
@admin_only
async def clean_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    msg = await query.edit_message_text("🧹 系统清理任务开始...\n")
    
    # 清理前磁盘占用
    disk_before = psutil.disk_usage('/')
    used_before_gb = round(disk_before.used / (1024**3), 3)
    total_gb = round(disk_before.total / (1024**3), 3)

    commands = [
        ("归档 systemd 日志", "sudo journalctl --rotate"),
        ("清理 APT 缓存", "sudo apt clean -y"),
        ("压缩 systemd 日志至 50MB", "sudo journalctl --vacuum-size=50M")
    ]
    
    output_text = (
        "🧹 系统清理任务开始...\n\n"
        f"💽 清理前占用: {used_before_gb} GB / {total_gb} GB\n\n"
    )
    await msg.edit_text(output_text)
    start_time = time.time()
    
    for index, (desc, cmd) in enumerate(commands, start=1):
        output_text += f"{index}️⃣ {desc}...\n"
        await msg.edit_text(output_text)
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                output_text += "   ✅ 成功\n\n"
            else:
                output_text += f"   ❌ 失败\n   错误：{result.stderr.strip()}\n\n"
        except subprocess.TimeoutExpired:
            output_text += "   ❌ 超时\n\n"
        await msg.edit_text(output_text)

    # 清理后磁盘占用
    disk_after = psutil.disk_usage('/')
    used_after_gb = round(disk_after.used / (1024**3), 3)
    freed_gb = round(used_before_gb - used_after_gb, 3)
    freed_percent = round((freed_gb / used_before_gb) * 100, 2) if used_before_gb > 0 else 0

    total_time = round(time.time() - start_time, 2)

    # 专业报告风格输出
    output_text += (
        "📊 **清理完成报告**\n"
        "---------------------------\n"
        f"💽 清理前占用: {used_before_gb} GB / {total_gb} GB\n"
        f"💾 清理后占用: {used_after_gb} GB / {total_gb} GB\n"
        f"🗑 释放空间: {freed_gb} GB\n"
        f"📈 释放百分比: {freed_percent}%\n"
        f"⏱ 总耗时: {total_time} 秒\n"
        "---------------------------"
    )

    await msg.edit_text(output_text, parse_mode='Markdown')

# ================= 按钮处理 =================
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
        keyboard = [
            [InlineKeyboardButton("180GB", callback_data='set_180'),
             InlineKeyboardButton("200GB", callback_data='set_200')],
            [InlineKeyboardButton("500GB", callback_data='set_500'),
             InlineKeyboardButton("关闭限制", callback_data='set_off')],
            [InlineKeyboardButton("🔙 返回菜单", callback_data='menu')]
        ]
        status = f"当前限制: {config['limit_gb']}GB\n自动关机: {'开启' if config['auto_shutdown'] else '关闭'}"
        await query.edit_message_text(f"⚙️ **流量阈值设置**\n{status}\n(达标后将自动执行关机)",
                                      reply_markup=InlineKeyboardMarkup(keyboard))
        return
    elif query.data.startswith('set_'):
        val = query.data.split('_')[1]
        if val == 'off':
            config['limit_gb'] = 0
            config['auto_shutdown'] = False
            res = "✅ 已关闭流量限制。"
        else:
            config['limit_gb'] = int(val)
            config['auto_shutdown'] = True
            res = f"✅ 已设置上限为 {val}GB，达标自动关机。"
        save_config()
        await query.answer(res, show_alert=True)
        await start(update, context)
        return
    elif query.data == 'clean_logs':
        await clean_logs(update, context)
        return
    elif query.data == 'reboot':
        keyboard = [[InlineKeyboardButton("✅ 确认重启", callback_data='confirm_reboot')],
                    [InlineKeyboardButton("❌ 取消", callback_data='menu')]]
        await query.edit_message_text("⚠️ **高风险操作**\n确定要重启 VPS 吗？",
                                      reply_markup=InlineKeyboardMarkup(keyboard))
        return
    elif query.data == 'confirm_reboot':
        await query.edit_message_text("🔄 发送重启命令...", parse_mode='Markdown')
        os.system("reboot")
        return
    elif query.data == 'shutdown':
        keyboard = [[InlineKeyboardButton("🛑 确认关机", callback_data='confirm_shutdown')],
                    [InlineKeyboardButton("❌ 取消", callback_data='menu')]]
        await query.edit_message_text("⚠️ **高风险操作**\n确定要立即关机 VPS 吗？",
                                      reply_markup=InlineKeyboardMarkup(keyboard),
                                      parse_mode='Markdown')
        return
    elif query.data == 'confirm_shutdown':
        await query.edit_message_text("🛑 正在执行关机命令...", parse_mode='Markdown')
        os.system("shutdown -h now")
        return
    elif query.data == 'close':
        await query.delete_message()
        return
    elif query.data == 'menu':
        await start(update, context)
        return

    await query.edit_message_text(msg,
                                  reply_markup=InlineKeyboardMarkup(
                                      [[InlineKeyboardButton("🔙 返回菜单", callback_data='menu')]]
                                  ),
                                  parse_mode='Markdown')

# ================= 定时任务 =================
async def check_traffic_job(context: ContextTypes.DEFAULT_TYPE):
    if not config['auto_shutdown'] or config['limit_gb'] <= 0:
        return
    _, total_usage = get_traffic_status()
    if total_usage >= config['limit_gb']:
        try:
            await context.bot.send_message(chat_id=config['admin_id'],
                                           text=f"🚨 **流量严重警告**\n\n已用流量: {total_usage}GB\n设定阈值: {config['limit_gb']}GB\n\n⚠️ **系统将于 10秒后 自动关机！**")
        except Exception:
            pass
        await asyncio.sleep(10)
        os.system("shutdown -h now")

# ================= 启动 SSH 监听 =================
async def on_startup(app: Application):
    app.create_task(monitor_ssh_login(app))

# ================= 主程序 =================
def main():
    load_config()
    if not config['bot_token']:
        print("Error: Bot Token not configured.")
        return
    application = Application.builder().token(config['bot_token']).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.post_init = on_startup
    if application.job_queue:
        application.job_queue.run_repeating(check_traffic_job, interval=60, first=10)
    print(f"✅ Bot started polling... (版本 {VERSION})")
    application.run_polling()

if __name__ == '__main__':
    main()
