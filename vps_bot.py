#!/usr/bin/env python3
import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from collections import deque
from datetime import datetime
from functools import wraps
from getpass import getpass
from pathlib import Path

import psutil
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)
from telegram.helpers import escape_markdown

# ================= 基础配置 =================
BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.json"

VERSION = "v3.8.4"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

config = {
    "bot_token": "",
    "admin_id": 0,
    "limit_gb": 0,
    "auto_shutdown": False,  # 仅为兼容旧 config.json 保留，程序不再自动关机
    "vnstat_interface": "",
}

# 流量超过阈值时，避免每分钟重复刷屏。
TRAFFIC_ALERT_INTERVAL = 6 * 60 * 60
last_traffic_alert_time = 0.0


# ================= 工具函数 =================
def markdown_escape(value):
    return escape_markdown(str(value), version=1)


def safe_code_block(value, max_length=3000):
    text = str(value).strip()

    if not text:
        return "暂无记录"

    text = text.replace("```", "'''")

    if len(text) > max_length:
        text = f"...（仅显示最后 {max_length} 个字符）\n{text[-max_length:]}"

    return text


def validate_bot_token(token):
    if not token or ":" not in token:
        return False

    bot_id, secret = token.split(":", 1)

    if not bot_id.isdigit() or not secret:
        return False

    return all(char.isalnum() or char in "_-" for char in secret)


def is_private_admin(update):
    user = update.effective_user
    chat = update.effective_chat

    if user is None or chat is None:
        return False

    return (
        user.id == config.get("admin_id", 0)
        and chat.type == "private"
    )


# ================= 配置文件操作 =================
def normalize_config():
    global config

    config["bot_token"] = str(config.get("bot_token", "")).strip()

    try:
        config["admin_id"] = int(config.get("admin_id", 0))
    except (TypeError, ValueError):
        config["admin_id"] = 0

    try:
        config["limit_gb"] = max(0, int(config.get("limit_gb", 0)))
    except (TypeError, ValueError):
        config["limit_gb"] = 0

    # 为兼容旧配置保留字段，但不再使用它执行自动关机。
    config["auto_shutdown"] = False

    config["vnstat_interface"] = str(
        config.get("vnstat_interface", "")
    ).strip()


def save_config():
    temp_path = None

    try:
        BASE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(BASE_DIR, 0o700)

        # 永远禁用自动关机，即使旧版管理面板写入 true。
        config["auto_shutdown"] = False

        fd, temp_path = tempfile.mkstemp(
            prefix=".config.",
            suffix=".tmp",
            dir=str(BASE_DIR),
            text=True,
        )

        os.fchmod(fd, 0o600)

        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())

        os.replace(temp_path, CONFIG_FILE)
        os.chmod(CONFIG_FILE, 0o600)

    except Exception as e:
        logger.error("保存配置失败: %s", e)

        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def load_config():
    global config

    if CONFIG_FILE.exists():
        try:
            with CONFIG_FILE.open("r", encoding="utf-8") as f:
                saved_config = json.load(f)

            if not isinstance(saved_config, dict):
                raise ValueError("config.json 必须是 JSON 对象")

            config.update(saved_config)
            normalize_config()
            os.chmod(CONFIG_FILE, 0o600)
            return

        except Exception as e:
            logger.error("加载配置失败: %s", e)
            sys.exit(1)

    logger.info("配置文件不存在，将首次运行提示输入 Token 和管理员 ID。")

    token = getpass("请输入 Telegram Bot Token（输入不回显）: ").strip()

    if not validate_bot_token(token):
        logger.error("Telegram Bot Token 格式异常。")
        sys.exit(1)

    try:
        admin_id = int(input("请输入管理员 Telegram ID: ").strip())
    except ValueError:
        logger.error("管理员 Telegram ID 必须是数字。")
        sys.exit(1)

    if admin_id <= 0:
        logger.error("管理员 Telegram ID 必须为正整数。")
        sys.exit(1)

    config["bot_token"] = token
    config["admin_id"] = admin_id
    config["auto_shutdown"] = False
    save_config()


def reload_config():
    global config

    if not CONFIG_FILE.exists():
        logger.warning("配置文件不存在，无法重新加载。")
        return

    try:
        with CONFIG_FILE.open("r", encoding="utf-8") as f:
            saved_config = json.load(f)

        if not isinstance(saved_config, dict):
            raise ValueError("config.json 必须是 JSON 对象")

        config.update(saved_config)
        normalize_config()

    except Exception as e:
        logger.error("重新加载配置失败: %s", e)


# ================= 权限装饰器 =================
def admin_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_private_admin(update):
            user = update.effective_user
            chat = update.effective_chat

            logger.warning(
                "拒绝未授权访问：user_id=%s, chat_id=%s, chat_type=%s",
                getattr(user, "id", None),
                getattr(chat, "id", None),
                getattr(chat, "type", None),
            )
            return

        return await func(update, context)

    return wrapper


# ================= 系统状态 =================
def get_system_status():
    cpu_usage = psutil.cpu_percent(interval=1)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    boot_time = datetime.fromtimestamp(
        psutil.boot_time()
    ).strftime("%Y-%m-%d %H:%M:%S")

    return (
        "🖥 *VPS 状态概览*\n"
        "-------------------\n"
        f"⏱ 开机时间: {boot_time}\n"
        f"🧠 CPU 使用: {cpu_usage}%\n"
        f"🐏 内存: {round(mem.used / (1024 ** 3), 2)}G / "
        f"{round(mem.total / (1024 ** 3), 2)}G ({mem.percent}%)\n"
        f"💾 硬盘: {round(disk.used / (1024 ** 3), 2)}G / "
        f"{round(disk.total / (1024 ** 3), 2)}G ({disk.percent}%)\n"
    )


# ================= 流量状态 =================
def get_traffic_status():
    try:
        result = subprocess.run(
            ["vnstat", "--json"],
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )

        data = json.loads(result.stdout)
        interfaces = data.get("interfaces", [])

        if not interfaces:
            return "⚠️ vnStat 未检测到接口数据。", 0

        target_iface = config.get("vnstat_interface", "")
        interface = None

        if target_iface:
            for iface in interfaces:
                if iface.get("name") == target_iface:
                    interface = iface
                    break

        if interface is None:
            interface = interfaces[0]

        name = interface.get("name", "未知接口")
        traffic_month = interface.get("traffic", {}).get("month", [])

        if not traffic_month:
            return f"⚠️ 接口 {markdown_escape(name)} 暂无本月流量记录。", 0

        current_month = traffic_month[-1]
        rx_bytes = current_month.get("rx", 0)
        tx_bytes = current_month.get("tx", 0)

        rx = round(rx_bytes / (1024 ** 3), 2)
        tx = round(tx_bytes / (1024 ** 3), 2)
        total = round((rx_bytes + tx_bytes) / (1024 ** 3), 2)

        limit_gb = config.get("limit_gb", 0)
        limit_msg = f"{limit_gb} GB" if limit_gb > 0 else "未设置告警"

        msg = (
            "📡 *流量统计（本月）*\n"
            "-------------------\n"
            f"🔌 接口: {markdown_escape(name)}\n"
            f"⬇️ 下载: {rx} GB\n"
            f"⬆️ 上传: {tx} GB\n"
            f"📊 总计: {total} GB\n"
            "-------------------\n"
            f"🔔 告警阈值: {limit_msg}\n"
            "🛡 超限行为: 仅通知，不自动关机"
        )

        return msg, total

    except FileNotFoundError:
        return "⚠️ 未安装 vnStat，无法获取流量。", 0

    except subprocess.TimeoutExpired:
        return "⚠️ 获取流量超时。", 0

    except subprocess.CalledProcessError as e:
        logger.error("vnStat 执行失败: %s", e.stderr)
        return "⚠️ vnStat 执行失败。", 0

    except Exception as e:
        logger.error("Traffic check error: %s", e)
        return f"⚠️ 获取流量失败: {markdown_escape(e)}", 0


# ================= SSH 登录监听 =================
async def monitor_ssh_login(app: Application):
    log_path = (
        "/var/log/auth.log"
        if os.path.exists("/var/log/auth.log")
        else "/var/log/secure"
    )

    if not os.path.exists(log_path):
        logger.warning("未找到 SSH 认证日志：%s", log_path)
        return

    process = None
    ip_lock = {}
    pattern = re.compile(
        r"Accepted (password|publickey) for (\S+) from (\S+)"
    )

    try:
        process = await asyncio.create_subprocess_exec(
            "tail",
            "-Fn0",
            log_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )

        while True:
            line = await process.stdout.readline()

            if not line:
                if process.returncode is not None:
                    logger.warning(
                        "SSH 日志监听进程已退出，返回码：%s",
                        process.returncode,
                    )
                    return

                await asyncio.sleep(0.2)
                continue

            text = line.decode("utf-8", errors="replace")
            match = pattern.search(text)

            if not match:
                continue

            auth_type, user, ip = match.groups()
            now = datetime.now()
            last_time = ip_lock.get(ip)

            if last_time and (now - last_time).total_seconds() < 60:
                continue

            ip_lock[ip] = now

            if len(ip_lock) > 1000:
                expire_before = now.timestamp() - 3600
                ip_lock = {
                    key: value
                    for key, value in ip_lock.items()
                    if value.timestamp() >= expire_before
                }

            msg = (
                "🚨 *SSH 登录提醒*\n\n"
                f"👤 用户: {markdown_escape(user)}\n"
                f"🌍 IP: {markdown_escape(ip)}\n"
                f"🔐 方式: {markdown_escape(auth_type)}\n"
                f"⏰ 时间: {now.strftime('%Y-%m-%d %H:%M:%S')}"
            )

            if user == "root":
                msg += "\n⚠️ *ROOT 登录*"

            try:
                reload_config()

                if config.get("admin_id", 0) <= 0:
                    logger.error("admin_id 无效，无法发送 SSH 登录提醒。")
                    continue

                await app.bot.send_message(
                    chat_id=config["admin_id"],
                    text=msg,
                    parse_mode="Markdown",
                )

            except Exception as e:
                logger.error("SSH monitor send error: %s", e)

    except asyncio.CancelledError:
        raise

    except Exception as e:
        logger.error("SSH monitor error: %s", e)

    finally:
        if process and process.returncode is None:
            process.terminate()

            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError:
                process.kill()


# ================= Fail2Ban 状态 =================
def get_fail2ban_stats():
    curr_banned = 0
    total_banned = 0

    try:
        result = subprocess.run(
            ["fail2ban-client", "status", "sshd"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        if result.returncode == 0:
            for line in result.stdout.splitlines():
                stripped = line.strip()

                if "Currently banned" in stripped:
                    curr_banned = int(stripped.split()[-1])

                if "Total banned" in stripped:
                    total_banned = int(stripped.split()[-1])

        if total_banned == 0:
            log_path = "/var/log/fail2ban.log"
            banned_ips = set()
            ip_pattern = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")

            if os.path.exists(log_path):
                with open(
                    log_path,
                    "r",
                    encoding="utf-8",
                    errors="replace",
                ) as f:
                    for line in f:
                        if " Ban " in line or "Banned IP list" in line:
                            banned_ips.update(ip_pattern.findall(line))

                total_banned = len(banned_ips)

        return (
            "⛔ *Fail2Ban 封禁统计*\n"
            f"🔹 当前封禁 IP 数量: {curr_banned}\n"
            f"🔹 累计封禁 IP 数量: {total_banned}"
        )

    except FileNotFoundError:
        return "⚠️ 未安装 Fail2Ban。"

    except Exception as e:
        logger.error("获取 Fail2Ban 统计失败: %s", e)
        return f"⚠️ 获取 Fail2Ban 统计失败: {markdown_escape(e)}"


# ================= 日志读取 =================
def get_recent_ssh_logins():
    try:
        result = subprocess.run(
            ["last", "-n", "10"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )

        lines = [
            line
            for line in result.stdout.splitlines()
            if "reboot" not in line.lower()
        ]

        output = "\n".join(lines).strip() or "暂无 SSH 登录记录"

        return (
            "📜 *最近 10 次 SSH 登录*\n\n"
            f"```\n{safe_code_block(output)}\n```"
        )

    except Exception as e:
        logger.error("获取 SSH 登录记录失败: %s", e)
        return f"⚠️ 获取 SSH 登录记录失败: {markdown_escape(e)}"


def get_recent_ssh_failed_logins():
    log_path = (
        "/var/log/auth.log"
        if os.path.exists("/var/log/auth.log")
        else "/var/log/secure"
    )

    if not os.path.exists(log_path):
        return "⚠️ 未找到 SSH 认证日志。"

    try:
        matched_lines = deque(maxlen=10)

        with open(
            log_path,
            "r",
            encoding="utf-8",
            errors="replace",
        ) as f:
            for line in f:
                if "Failed password" in line:
                    matched_lines.append(line.rstrip())

        output = "\n".join(matched_lines) or "暂无 SSH 失败登录记录"

        return (
            "❌ *最近 10 次 SSH 失败登录*\n\n"
            f"```\n{safe_code_block(output)}\n```"
        )

    except Exception as e:
        logger.error("获取 SSH 失败登录记录失败: %s", e)
        return f"⚠️ 获取 SSH 失败登录记录失败: {markdown_escape(e)}"


# ================= Telegram 面板 =================
def main_menu_keyboard():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📊 系统状态", callback_data="status"),
                InlineKeyboardButton("📡 流量统计", callback_data="traffic"),
            ],
            [
                InlineKeyboardButton(
                    "🔐 SSH 登录记录",
                    callback_data="ssh_logs",
                ),
                InlineKeyboardButton(
                    "❌ SSH 失败记录",
                    callback_data="ssh_fail_logs",
                ),
            ],
            [
                InlineKeyboardButton(
                    "⛔ Fail2Ban 封禁统计",
                    callback_data="fail2ban",
                ),
            ],
            [
                InlineKeyboardButton(
                    "⚙️ 设置流量告警",
                    callback_data="setup_limit",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🧹 清理缓存日志",
                    callback_data="clean_logs",
                ),
            ],
            [
                InlineKeyboardButton("🔄 重启 VPS", callback_data="reboot"),
                InlineKeyboardButton("🛑 立即关机", callback_data="shutdown"),
            ],
            [
                InlineKeyboardButton("❌ 关闭菜单", callback_data="close"),
            ],
        ]
    )


@admin_only
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        f"🤖 *VPS 管理面板（{VERSION}）*\n"
        "流量超限只会告警，不会自动关机。\n\n"
        "请选择操作："
    )

    if update.callback_query:
        await update.callback_query.edit_message_text(
            text=text,
            reply_markup=main_menu_keyboard(),
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            text,
            reply_markup=main_menu_keyboard(),
            parse_mode="Markdown",
        )


# ================= 清理缓存日志 =================
@admin_only
async def clean_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if query is None:
        return

    await query.answer()
    message = await query.edit_message_text("🧹 系统清理任务开始...")

    disk_before = psutil.disk_usage("/")
    used_before_gb = round(disk_before.used / (1024 ** 3), 3)
    total_gb = round(disk_before.total / (1024 ** 3), 3)

    commands = [
        ("归档 systemd 日志", ["journalctl", "--rotate"]),
        ("清理 APT 缓存", ["apt-get", "clean"]),
        ("压缩 systemd 日志至 50MB", ["journalctl", "--vacuum-size=50M"]),
    ]

    output_text = (
        "🧹 系统清理任务开始...\n\n"
        f"💽 清理前占用: {used_before_gb} GB / {total_gb} GB\n\n"
    )

    await message.edit_text(output_text)
    start_time = time.time()

    for index, (description, command) in enumerate(commands, start=1):
        output_text += f"{index}️⃣ {description}...\n"
        await message.edit_text(output_text)

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )

            if result.returncode == 0:
                output_text += " ✅ 成功\n\n"
            else:
                error = result.stderr.strip() or "未知错误"
                output_text += f" ❌ 失败\n错误：{error[:500]}\n\n"

        except subprocess.TimeoutExpired:
            output_text += " ❌ 超时\n\n"

        except Exception as e:
            output_text += f" ❌ 异常：{str(e)[:300]}\n\n"

        await message.edit_text(output_text)

    disk_after = psutil.disk_usage("/")
    used_after_gb = round(disk_after.used / (1024 ** 3), 3)
    freed_gb = round(used_before_gb - used_after_gb, 3)
    freed_percent = (
        round((freed_gb / used_before_gb) * 100, 2)
        if used_before_gb > 0
        else 0
    )
    total_time = round(time.time() - start_time, 2)

    output_text += (
        "📊 *清理完成报告*\n"
        "---------------------------\n"
        f"💽 清理前占用: {used_before_gb} GB / {total_gb} GB\n"
        f"💾 清理后占用: {used_after_gb} GB / {total_gb} GB\n"
        f"🗑 释放空间: {freed_gb} GB\n"
        f"📈 释放百分比: {freed_percent}%\n"
        f"⏱ 总耗时: {total_time} 秒\n"
        "---------------------------"
    )

    await message.edit_text(output_text, parse_mode="Markdown")


# ================= 按钮处理 =================
async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query

    if query is None:
        return

    reload_config()

    if not is_private_admin(update):
        logger.warning(
            "拒绝未授权按钮操作：user_id=%s, chat_id=%s",
            getattr(query.from_user, "id", None),
            getattr(query.message.chat, "id", None)
            if query.message
            else None,
        )
        await query.answer("无权限操作。", show_alert=True)
        return

    await query.answer()

    if query.data == "status":
        msg = get_system_status()

    elif query.data == "traffic":
        msg, _ = get_traffic_status()

    elif query.data == "ssh_logs":
        msg = get_recent_ssh_logins()

    elif query.data == "ssh_fail_logs":
        msg = get_recent_ssh_failed_logins()

    elif query.data == "fail2ban":
        msg = get_fail2ban_stats()

    elif query.data == "setup_limit":
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "180GB 告警",
                        callback_data="set_180",
                    ),
                    InlineKeyboardButton(
                        "200GB 告警",
                        callback_data="set_200",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        "500GB 告警",
                        callback_data="set_500",
                    ),
                    InlineKeyboardButton(
                        "关闭告警",
                        callback_data="set_off",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        "🔙 返回菜单",
                        callback_data="menu",
                    ),
                ],
            ]
        )

        current_limit = config.get("limit_gb", 0)
        status = (
            f"当前告警阈值: {current_limit} GB\n"
            "超限行为: 仅发送 Telegram 通知，不自动关机。"
        )

        await query.edit_message_text(
            f"⚙️ *流量告警设置*\n{status}",
            reply_markup=keyboard,
            parse_mode="Markdown",
        )
        return

    elif query.data.startswith("set_"):
        value = query.data.split("_", 1)[1]

        if value == "off":
            config["limit_gb"] = 0
            config["auto_shutdown"] = False
            result_text = "✅ 已关闭流量告警。"
        else:
            try:
                limit = int(value)
            except ValueError:
                await query.answer("无效的流量阈值。", show_alert=True)
                return

            config["limit_gb"] = limit
            config["auto_shutdown"] = False
            result_text = (
                f"✅ 已设置 {limit} GB 流量告警。\n"
                "达到阈值只会通知，不会自动关机。"
            )

        save_config()
        await query.answer(result_text, show_alert=True)
        await start(update, context)
        return

    elif query.data == "clean_logs":
        await clean_logs(update, context)
        return

    elif query.data == "reboot":
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✅ 确认重启",
                        callback_data="confirm_reboot",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        "❌ 取消",
                        callback_data="menu",
                    ),
                ],
            ]
        )

        await query.edit_message_text(
            "⚠️ *高风险操作*\n确定要重启 VPS 吗？",
            reply_markup=keyboard,
            parse_mode="Markdown",
        )
        return

    elif query.data == "confirm_reboot":
        await query.edit_message_text(
            "🔄 正在执行重启命令...",
            parse_mode="Markdown",
        )

        subprocess.run(["systemctl", "reboot"], check=False)
        return

    elif query.data == "shutdown":
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🛑 确认关机",
                        callback_data="confirm_shutdown",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        "❌ 取消",
                        callback_data="menu",
                    ),
                ],
            ]
        )

        await query.edit_message_text(
            "⚠️ *高风险操作*\n确定要立即关闭 VPS 吗？",
            reply_markup=keyboard,
            parse_mode="Markdown",
        )
        return

    elif query.data == "confirm_shutdown":
        await query.edit_message_text(
            "🛑 正在执行关机命令...",
            parse_mode="Markdown",
        )

        subprocess.run(["systemctl", "poweroff"], check=False)
        return

    elif query.data == "close":
        await query.delete_message()
        return

    elif query.data == "menu":
        await start(update, context)
        return

    else:
        await query.answer("未知操作。", show_alert=True)
        return

    await query.edit_message_text(
        msg,
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 返回菜单", callback_data="menu")]]
        ),
        parse_mode="Markdown",
    )


# ================= 定时流量告警 =================
async def check_traffic_job(context: ContextTypes.DEFAULT_TYPE):
    """
    流量达到阈值时只发送告警，绝不自动执行关机。

    自动关机功能已移除，以避免 OCI 热门区域实例因关机后
    无法重新获得容量而无法启动。
    """
    global last_traffic_alert_time

    reload_config()

    limit_gb = config.get("limit_gb", 0)

    if limit_gb <= 0:
        last_traffic_alert_time = 0.0
        return

    _, total_usage = get_traffic_status()

    # 流量回落或统计周期重置后，允许下次再次告警。
    if total_usage < limit_gb:
        last_traffic_alert_time = 0.0
        return

    now = time.time()

    if now - last_traffic_alert_time < TRAFFIC_ALERT_INTERVAL:
        return

    try:
        await context.bot.send_message(
            chat_id=config["admin_id"],
            text=(
                "🚨 *流量阈值警告*\n\n"
                f"已用流量: {total_usage} GB\n"
                f"设定阈值: {limit_gb} GB\n\n"
                "🛡 当前仅发送告警，不会自动关机。\n"
                "告警冷却时间：6 小时。"
            ),
            parse_mode="Markdown",
        )

        last_traffic_alert_time = now
        logger.warning(
            "流量达到告警阈值：usage=%sGB, limit=%sGB",
            total_usage,
            limit_gb,
        )

    except Exception as e:
        logger.error("发送流量告警失败: %s", e)


# ================= 启动 SSH 监听 =================
async def on_startup(app: Application):
    app.create_task(
        monitor_ssh_login(app),
        name="monitor_ssh_login",
    )


# ================= 主程序 =================
def main():
    load_config()

    if not config.get("bot_token"):
        logger.error("Bot Token 未配置。")
        return

    if config.get("admin_id", 0) <= 0:
        logger.error("Admin ID 未配置或无效。")
        return

    application = (
        Application.builder()
        .token(config["bot_token"])
        .build()
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))

    application.post_init = on_startup

    if application.job_queue:
        application.job_queue.run_repeating(
            check_traffic_job,
            interval=60,
            first=10,
            name="check_traffic_alert_job",
        )
    else:
        logger.warning(
            "JobQueue 不可用，流量告警定时检查不会运行。"
        )

    logger.info("Bot started polling. Version: %s", VERSION)
    application.run_polling()


if __name__ == "__main__":
    main()
