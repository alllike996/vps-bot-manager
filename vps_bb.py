#!/usr/bin/env python3
import os
import sys
import json
import psutil
import subprocess
from datetime import datetime
import shutil

VERSION = "v2.0.0"

CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'config.json')
INSTALL_DIR = os.path.dirname(os.path.abspath(__file__))
SHORTCUT_CMD = '/usr/local/bin/vps-bb'
SYSTEMD_SERVICE = '/etc/systemd/system/vpsbot.service'


# ===================== 基础工具函数 =====================

def clear_screen():
    os.system("clear")


def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {}
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(cfg):
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(cfg, f, indent=4)
    except Exception as e:
        print(f"❌ 保存配置失败: {e}")


def safe_int_input(prompt):
    value = input(prompt)
    if not value.isdigit():
        print("❌ 请输入有效数字！")
        return None
    return int(value)


# ===================== 设置功能 =====================

def set_token():
    cfg = load_config()
    token = input("请输入新的 Telegram Bot Token: ").strip()
    if not token:
        print("❌ Token 不能为空")
        return
    cfg['bot_token'] = token
    save_config(cfg)
    print("✅ Bot Token 已更新！")


def set_admin():
    cfg = load_config()
    admin_id = safe_int_input("请输入新的 Admin ID: ")
    if admin_id is None:
        return
    cfg['admin_id'] = admin_id
    save_config(cfg)
    print("✅ Admin ID 已更新！")


def set_limit():
    cfg = load_config()
    limit = safe_int_input("请输入流量阈值(GB, 0为不限制): ")
    if limit is None:
        return
    cfg['limit_gb'] = limit
    cfg['auto_shutdown'] = True if limit > 0 else False
    save_config(cfg)
    print(f"✅ 流量阈值已更新为 {limit} GB")


def toggle_auto_shutdown():
    cfg = load_config()
    cfg['auto_shutdown'] = not cfg.get('auto_shutdown', False)
    save_config(cfg)
    print(f"✅ 自动关机已{'开启' if cfg['auto_shutdown'] else '关闭'}")


# ===================== 状态功能 =====================

def show_status():
    cpu = psutil.cpu_percent(interval=1)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    uptime = datetime.fromtimestamp(psutil.boot_time()).strftime("%Y-%m-%d %H:%M:%S")

    print("\n🖥 VPS 状态:")
    print(f"⏱ 开机时间: {uptime}")
    print(f"🧠 CPU 使用率: {cpu}%")
    print(f"🐏 内存: {mem.percent}% ({round(mem.used/1024**3,2)}G/{round(mem.total/1024**3,2)}G)")
    print(f"💾 硬盘: {disk.percent}% ({round(disk.used/1024**3,2)}G/{round(disk.total/1024**3,2)}G)\n")


def show_traffic():
    cfg = load_config()
    iface = cfg.get('vnstat_interface')

    try:
        result = subprocess.check_output(["vnstat", "--json"])
        data = json.loads(result.decode())

        interface = None
        for i in data['interfaces']:
            if iface and i['name'] == iface:
                interface = i
                break

        if not interface:
            interface = data['interfaces'][0]

        rx = round(interface['traffic']['month'][-1]['rx']/1024**3, 2)
        tx = round(interface['traffic']['month'][-1]['tx']/1024**3, 2)
        total = round(rx + tx, 2)

        print(f"\n📡 流量统计 ({interface['name']}):")
        print(f"⬇️ 下载: {rx} GB")
        print(f"⬆️ 上传: {tx} GB")
        print(f"📊 总计: {total} GB\n")

    except FileNotFoundError:
        print("⚠️ 未安装 vnstat")
    except Exception as e:
        print(f"⚠️ 无法获取流量: {e}")


# ===================== 系统操作 =====================

def reboot_vps():
    confirm = input("⚠️ 确定要重启 VPS 吗? (y/n): ").lower()
    if confirm == 'y':
        print("🔄 正在重启...")
        subprocess.run(["reboot"])


def shutdown_vps():
    confirm = input("⚠️ 确定要关机 VPS 吗? (y/n): ").lower()
    if confirm == 'y':
        print("🛑 正在关机...")
        subprocess.run(["shutdown", "-h", "now"])


def restart_script():
    print("🔄 正在重启管理脚本...")
    python = sys.executable
    os.execl(python, python, *sys.argv)


def stop_script():
    print("🛑 正在退出管理脚本...")
    sys.exit(0)


def uninstall_script():
    confirm = input(
        "⚠️ 确定要卸载管理脚本吗? "
        "这将删除安装目录、快捷命令和 systemd 服务! (y/n): "
    ).lower()

    if confirm != 'y':
        print("❌ 已取消卸载")
        return

    try:
        if os.path.exists(SYSTEMD_SERVICE):
            subprocess.run(["systemctl", "stop", "vpsbot"])
            subprocess.run(["systemctl", "disable", "vpsbot"])
            os.remove(SYSTEMD_SERVICE)
            subprocess.run(["systemctl", "daemon-reload"])
            print("✅ 已删除 systemd 服务")

        if os.path.exists(INSTALL_DIR):
            shutil.rmtree(INSTALL_DIR)
            print("✅ 已删除安装目录")

        if os.path.exists(SHORTCUT_CMD):
            os.remove(SHORTCUT_CMD)
            print("✅ 已删除快捷命令")

        print("🛑 管理脚本已卸载")
    except Exception as e:
        print(f"⚠️ 卸载失败: {e}")

    sys.exit(0)


# ===================== 菜单 =====================

def menu():
    YELLOW = "\033[93m"
    RESET = "\033[0m"

    while True:
        clear_screen()
        cfg = load_config()

        auto_status = "开启" if cfg.get("auto_shutdown") else "关闭"
        limit = cfg.get("limit_gb", 0)

        print(f"""
========================
   VPS 快捷管理面板
   Version {VERSION}
========================
自动关机状态: {auto_status}
流量阈值: {limit} GB
========================
{YELLOW}1){RESET} 修改 Telegram Token
{YELLOW}2){RESET} 修改 Admin ID
{YELLOW}3){RESET} 修改流量阈值
{YELLOW}4){RESET} 开/关自动关机
{YELLOW}5){RESET} 查看 VPS 状态
{YELLOW}6){RESET} 查看流量统计
{YELLOW}7){RESET} 重启 VPS
{YELLOW}8){RESET} 关机 VPS
{YELLOW}9){RESET} 重启管理脚本
{YELLOW}10){RESET} 停止管理脚本
{YELLOW}11){RESET} 卸载管理脚本
{YELLOW}0){RESET} 退出
========================
""")

        choice = input("请输入选项: ").strip()

        if choice == '1':
            set_token()
        elif choice == '2':
            set_admin()
        elif choice == '3':
            set_limit()
        elif choice == '4':
            toggle_auto_shutdown()
        elif choice == '5':
            show_status()
        elif choice == '6':
            show_traffic()
        elif choice == '7':
            reboot_vps()
        elif choice == '8':
            shutdown_vps()
        elif choice == '9':
            restart_script()
        elif choice == '10':
            stop_script()
        elif choice == '11':
            uninstall_script()
        elif choice == '0':
            print("退出...")
            break
        else:
            print("❌ 无效选项，请重新输入！")

        input("\n按回车键返回菜单...")


if __name__ == "__main__":
    menu()
