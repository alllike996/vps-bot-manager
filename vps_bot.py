# vps_bot.py
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

# ================= 路径配置 =================
# 获取脚本所在的绝对路径
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, 'config.json')

# ================= 日志设置 =================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ================= 配置加载 =================
config = {
    "bot_token": "",
    "admin_id": 0,
    "limit_gb": 0,
    "auto_shutdown": False,
    "vnstat_interface": ""  # 自动检测或指定
}

def load_config():
    global config
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                saved_config = json.load(f)
                config.update(saved_config)
        except Exception as e:
            logger.error(f"加载配置失败: {e}")
    else:
        logger.error("配置文件不存在，请先运行安装脚本！")
        sys.exit(1)

def save_config():
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=4)
    except Exception as e:
        logger.error(f"保存配置失败: {e}")

# --- 权限检查装饰器 ---
def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        # 确保 admin_id 是整数进行比较
        if user_id != int(config['admin_id']):
            # 默默忽略或者回复无权限
            return
        return await func(update, context)
    return wrapper

# --- 获取系统状态 ---
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
        f"🐏 内存: {round(mem.used / (1024**3), 2)}G / {round(mem.total / (1024**3), 2)}G ({mem.percent}%)\n"
        f"💾 硬盘: {round(disk.used / (1024**3), 2)}G / {round(disk.total / (1024**3), 2)}G ({disk.percent}%)\n"
    )
    return msg

# --- 获取流量 (使用 vnstat) ---
def get_traffic_status():
    try:
        # 使用 vnstat JSON 输出
        cmd = "vnstat --json"
        result = subprocess.check_output(cmd, shell=True).decode('utf-8')
        data = json.loads(result)
        
        # 尝试寻找活跃接口
        interface = None
        # 如果配置里指定了接口，优先用指定的
        target_iface = config.get('vnstat_interface')
        
        if target_iface:
            for iface in data['interfaces']:
                if iface['name'] == target_iface:
                    interface = iface
                    break
        
        # 如果没找到，默认取第一个有数据的
        if not interface and data['interfaces']:
            interface = data['interfaces'][0]
            
        if not interface:
             return "⚠️ vnstat 未检测到接口数据。", 0

        name = interface['name']
        traffic = interface.get('traffic', {}).get('month', [])
        
        if not traffic:
             return f"⚠️ 接口 {name} 暂无本月流量记录。", 0
             
        current_month = traffic[-1]
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
            f"🚫 阈值: {limit_msg}\n"
            f"⚡️ 自动关机: {auto_off_msg}"
        )
        return msg, total
    except Exception as e:
        logger.error(f"Traffic check error: {e}")
        return f"⚠️ 获取流量失败: {str(e)}", 0

# --- 主菜单 ---
@admin_only
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📊 状态", callback_data='status'), InlineKeyboardButton("📡 流量", callback_data='traffic')],
        [InlineKeyboardButton("⚙️ 设置阈值", callback_data='setup_limit')],
        [InlineKeyboardButton("🔄 重启", callback_data='reboot'), InlineKeyboardButton("🛑 关机", callback_data='shutdown')],
        [InlineKeyboardButton("❌ 关闭菜单", callback_data='close')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "🤖 **VPS 管理面板**\n请选择操作："
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')

# --- 按钮回调 ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    # 再次检查权限（防止转发消息后别人点击）
    if query.from_user.id != int(config['admin_id']):
        await query.answer("无权操作", show_alert=True)
        return

    if query.data == 'status':
        msg = get_system_status()
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data='menu')]]), parse_mode='Markdown')
        
    elif query.data == 'traffic':
        msg, _ = get_traffic_status()
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data='menu')]]), parse_mode='Markdown')

    elif query.data == 'menu':
        await start(update, context)
        
    elif query.data == 'close':
        await query.delete_message()

    elif query.data in ['reboot', 'shutdown']:
        action_name = "重启" if query.data == 'reboot' else "关机"
        keyboard = [
            [InlineKeyboardButton(f"✅ 确认{action_name}", callback_data=f'confirm_{query.data}')],
            [InlineKeyboardButton("❌ 取消", callback_data='menu')]
        ]
        await query.edit_message_text(f"⚠️ **高风险操作**\n确定要 {action_name} 吗？", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    elif query.data == 'confirm_reboot':
        await query.edit_message_text("🔄 系统正在重启...")
        os.system("reboot")
        
    elif query.data == 'confirm_shutdown':
        await query.edit_message_text("🛑 系统正在关机...")
        os.system("shutdown -h now")

    elif query.data == 'setup_limit':
        keyboard = [
            [InlineKeyboardButton("500GB", callback_data='set_500'), InlineKeyboardButton("1024GB", callback_data='set_1024')],
            [InlineKeyboardButton("2048GB", callback_data='set_2048'), InlineKeyboardButton("关闭限制", callback_data='set_off')],
            [InlineKeyboardButton("🔙 返回", callback_data='menu')]
        ]
        status = f"当前限制: {config['limit_gb']}GB\n自动关机: {'开启' if config['auto_shutdown'] else '关闭'}"
        await query.edit_message_text(f"⚙️ **流量阈值设置**\n{status}\n(达标后自动关机)", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data.startswith('set_'):
        val = query.data.split('_')[1]
        if val == 'off':
            config['limit_gb'] = 0
            config['auto_shutdown'] = False
            res = "已关闭流量限制。"
        else:
            config['limit_gb'] = int(val)
            config['auto_shutdown'] = True
            res = f"已设置上限为 {val}GB。"
        
        save_config()
        await query.answer(res, show_alert=True)
        await start(update, context)

# --- 定时任务 ---
async def check_traffic_job(context: ContextTypes.DEFAULT_TYPE):
    if not config['auto_shutdown'] or config['limit_gb'] <= 0:
        return

    _, total_usage = get_traffic_status()
    
    if total_usage >= config['limit_gb']:
        try:
            await context.bot.send_message(
                chat_id=config['admin_id'], 
                text=f"🚨 **流量严重警告**\n已用 {total_usage}GB / 限制 {config['limit_gb']}GB\n系统将于 5秒后 自动关机！"
            )
        except:
            pass
        
        await asyncio.sleep(5)
        os.system("shutdown -h now")

def main():
    load_config()
    
    if not config['bot_token']:
        print("Error: Bot Token not found in config.json")
        return

    application = Application.builder().token(config['bot_token']).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # 60秒检查一次
    application.job_queue.run_repeating(check_traffic_job, interval=60, first=10)
    
    print("✅ Bot is running...")
    application.run_polling()

if __name__ == '__main__':
    main()
