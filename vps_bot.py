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
# 获取脚本所在目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, 'config.json')

# 日志配置
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# 全局配置字典
config = {
    "bot_token": "",
    "admin_id": 0,
    "limit_gb": 0,
    "auto_shutdown": False,
    "vnstat_interface": ""
}

# ================= 功能函数 =================

def load_config():
    """加载配置文件"""
    global config
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                saved_config = json.load(f)
                config.update(saved_config)
            # 确保 admin_id 是整数
            config['admin_id'] = int(config['admin_id'])
            config['limit_gb'] = int(config['limit_gb'])
        except Exception as e:
            logger.error(f"加载配置失败: {e}")
            sys.exit(1)
    else:
        logger.error("配置文件不存在，请先运行 install.sh 安装脚本！")
        sys.exit(1)

def save_config():
    """保存配置文件"""
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=4)
    except Exception as e:
        logger.error(f"保存配置失败: {e}")

def admin_only(func):
    """权限检查装饰器"""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id != config['admin_id']:
            # 非管理员不回复，或者可以回复一条拒绝信息
            return
        return await func(update, context)
    return wrapper

def get_system_status():
    """获取 VPS 系统状态"""
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

def get_traffic_status():
    """获取流量信息 (vnstat)"""
    try:
        # 调用 vnstat JSON 接口
        cmd = "vnstat --json"
        result = subprocess.check_output(cmd, shell=True).decode('utf-8')
        data = json.loads(result)
        
        interface = None
        target_iface = config.get('vnstat_interface')
        
        # 1. 优先查找配置中指定的接口
        if target_iface:
            for iface in data['interfaces']:
                if iface['name'] == target_iface:
                    interface = iface
                    break
        
        # 2. 如果没找到，默认取第一个
        if not interface and data['interfaces']:
            interface = data['interfaces'][0]
            
        if not interface:
             return "⚠️ vnstat 未检测到接口数据 (请等待几分钟数据生成)。", 0

        name = interface['name']
        traffic_month = interface.get('traffic', {}).get('month', [])
        
        if not traffic_month:
             return f"⚠️ 接口 {name} 暂无本月流量记录。", 0
             
        # 获取当月数据 (列表最后一个通常是当前月)
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

# ================= Bot 交互逻辑 =================

@admin_only
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📊 系统状态", callback_data='status'), InlineKeyboardButton("📡 流量统计", callback_data='traffic')],
        [InlineKeyboardButton("⚙️ 设置流量阈值", callback_data='setup_limit')],
        [InlineKeyboardButton("🔄 重启 VPS", callback_data='reboot'), InlineKeyboardButton("🛑 关机 VPS", callback_data='shutdown')],
        [InlineKeyboardButton("❌ 关闭菜单", callback_data='close')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "🤖 **VPS 管理面板**\n请选择操作："
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    # 二次验证权限
    if query.from_user.id != config['admin_id']:
        return

    if query.data == 'status':
        msg = get_system_status()
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回菜单", callback_data='menu')]]), parse_mode='Markdown')
        
    elif query.data == 'traffic':
        msg, _ = get_traffic_status()
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回菜单", callback_data='menu')]]), parse_mode='Markdown')

    elif query.data == 'menu':
        await start(update, context)
        
    elif query.data == 'close':
        await query.delete_message()

    elif query.data in ['reboot', 'shutdown']:
        action = "重启" if query.data == 'reboot' else "关机"
        keyboard = [
            [InlineKeyboardButton(f"✅ 确认{action}", callback_data=f'confirm_{query.data}')],
            [InlineKeyboardButton("❌ 取消", callback_data='menu')]
        ]
        await query.edit_message_text(f"⚠️ **高风险操作**\n确定要 {action} 吗？\n(关机后无法通过机器人重新开机)", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    elif query.data == 'confirm_reboot':
        await query.edit_message_text("🔄 发送重启命令...", parse_mode='Markdown')
        os.system("reboot")
        
    elif query.data == 'confirm_shutdown':
        await query.edit_message_text("🛑 发送关机命令...", parse_mode='Markdown')
        os.system("shutdown -h now")

    elif query.data == 'setup_limit':
        keyboard = [
            [InlineKeyboardButton("180GB", callback_data='set_180'), InlineKeyboardButton("200GB", callback_data='set_200')],
            [InlineKeyboardButton("500GB", callback_data='set_500'), InlineKeyboardButton("关闭限制", callback_data='set_off')],
            [InlineKeyboardButton("🔙 返回菜单", callback_data='menu')]
        ]
        status = f"当前限制: {config['limit_gb']}GB\n自动关机: {'开启' if config['auto_shutdown'] else '关闭'}"
        await query.edit_message_text(f"⚙️ **流量阈值设置**\n{status}\n(达标后将自动执行关机)", reply_markup=InlineKeyboardMarkup(keyboard))

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

# ================= 定时任务 =================

async def check_traffic_job(context: ContextTypes.DEFAULT_TYPE):
    """定时检查流量是否超标"""
    if not config['auto_shutdown'] or config['limit_gb'] <= 0:
        return

    _, total_usage = get_traffic_status()
    
    if total_usage >= config['limit_gb']:
        # 发送警报
        try:
            await context.bot.send_message(
                chat_id=config['admin_id'], 
                text=f"🚨 **流量严重警告**\n\n已用流量: {total_usage}GB\n设定阈值: {config['limit_gb']}GB\n\n⚠️ **系统将于 10秒后 自动关机以防止扣费！**"
            )
        except Exception:
            pass
        
        # 给予一定缓冲时间让消息发出
        await asyncio.sleep(10)
        os.system("shutdown -h now")

# ================= 主程序 =================

def main():
    load_config()
    
    if not config['bot_token']:
        print("Error: Bot Token not configured.")
        return

    application = Application.builder().token(config['bot_token']).build()
    
    # 添加处理器
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # 添加定时任务 (每60秒检查一次)
    if application.job_queue:
        application.job_queue.run_repeating(check_traffic_job, interval=60, first=10)
    
    print("✅ Bot started polling...")
    application.run_polling()

if __name__ == '__main__':
    main()
