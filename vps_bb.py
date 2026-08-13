#!/usr/bin/env python3
import json
import os
import psutil
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from getpass import getpass
from pathlib import Path

VERSION = "v2.1.2"

INSTALL_DIR = Path(__file__).resolve().parent
EXPECTED_INSTALL_DIR = Path("/opt/vpsbot").resolve()
CONFIG_FILE = INSTALL_DIR / "config.json"
SHORTCUT_CMD = Path("/usr/local/bin/vps-bb")
SYSTEMD_SERVICE = Path("/etc/systemd/system/vpsbot.service")

# ===================== 颜色定义 =====================
RESET = "\033[0m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
BOLD = "\033[1m"


# ===================== 工具函数 =====================
def clear_screen():
    subprocess.run(["clear"], check=False)


def require_root():
    if os.geteuid() != 0:
        print(f"{RED}❌ 请使用 root 或 sudo 运行：sudo vps-bb{RESET}")
        sys.exit(1)


def load_config():
    if not CONFIG_FILE.exists():
        return {}

    try:
        with CONFIG_FILE.open("r", encoding="utf-8") as f:
            config = json.load(f)

        if not isinstance(config, dict):
            raise ValueError("配置文件格式不是 JSON 对象")

        return config

    except Exception as e:
        print(f"{RED}❌ 读取配置失败: {e}{RESET}")
        return {}


def save_config(cfg):
    """
    原子写入配置文件，并固定权限为 0600。
    防止 Bot Token 被 VPS 上其他普通用户读取。
    """
    temp_path = None

    try:
        INSTALL_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(INSTALL_DIR, 0o700)

        # 自动关机功能已移除；保留字段仅为兼容旧版配置。
        cfg["auto_shutdown"] = False

        fd, temp_path = tempfile.mkstemp(
            prefix=".config.",
            suffix=".tmp",
            dir=str(INSTALL_DIR),
            text=True,
        )

        os.fchmod(fd, 0o600)

        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4, ensure_ascii=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())

        os.replace(temp_path, CONFIG_FILE)
        os.chmod(CONFIG_FILE, 0o600)

    except Exception as e:
        print(f"{RED}❌ 保存配置失败: {e}{RESET}")

        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def safe_int_input(prompt, min_value=0):
    value = input(prompt).strip()

    if not value.isdigit():
        print(f"{RED}❌ 请输入有效数字！{RESET}")
        return None

    result = int(value)

    if result < min_value:
        print(f"{RED}❌ 数值不能小于 {min_value}！{RESET}")
        return None

    return result


def valid_bot_token(token):
    if not token or ":" not in token:
        return False

    bot_id, secret = token.split(":", 1)

    if not bot_id.isdigit() or not secret:
        return False

    return all(char.isalnum() or char in "_-" for char in secret)


def progress_bar(percent, width=30):
    percent = max(0, min(100, percent))
    filled = int(width * percent / 100)
    bar = "█" * filled + "-" * (width - filled)

    if percent < 60:
        color = GREEN
    elif percent < 85:
        color = YELLOW
    else:
        color = RED

    return f"{color}[{bar}] {percent}%{RESET}"


def pause():
    input("\n按回车返回菜单...")


# ===================== 设置功能 =====================
def set_token():
    cfg = load_config()

    token = getpass(
        "请输入新的 Telegram Bot Token（输入不回显）: "
    ).strip()

    if not valid_bot_token(token):
        print(f"{RED}❌ Token 格式异常，未保存。{RESET}")
        return

    cfg["bot_token"] = token
    save_config(cfg)

    print(f"{GREEN}✅ Bot Token 已更新！{RESET}")
    print(f"{YELLOW}提示：请重启 Bot 服务使新 Token 生效。{RESET}")
    print(f"{YELLOW}执行：systemctl restart vpsbot{RESET}")


def set_admin():
    cfg = load_config()

    admin_id = safe_int_input(
        "请输入新的 Admin ID: ",
        min_value=1,
    )

    if admin_id is None:
        return

    cfg["admin_id"] = admin_id
    save_config(cfg)

    print(f"{GREEN}✅ Admin ID 已更新！{RESET}")
    print(f"{YELLOW}提示：请重启 Bot 服务使新 Admin ID 生效。{RESET}")
    print(f"{YELLOW}执行：systemctl restart vpsbot{RESET}")


def set_limit():
    cfg = load_config()

    limit = safe_int_input(
        "请输入流量告警阈值（GB，0 为关闭告警）: ",
        min_value=0,
    )

    if limit is None:
        return

    cfg["limit_gb"] = limit
    cfg["auto_shutdown"] = False
    save_config(cfg)

    if limit == 0:
        print(f"{GREEN}✅ 已关闭流量告警。{RESET}")
    else:
        print(f"{GREEN}✅ 流量告警阈值已更新为 {limit} GB。{RESET}")
        print(f"{YELLOW}提示：达到阈值时仅发送 Telegram 告警，不会自动关机。{RESET}")


# ===================== 状态显示 =====================
def show_status():
    cpu = psutil.cpu_percent(interval=1)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    boot_time = datetime.fromtimestamp(
        psutil.boot_time()
    ).strftime("%Y-%m-%d %H:%M:%S")

    print(f"\n{CYAN}{BOLD}🖥 VPS 状态{RESET}")
    print(f"⏱ 开机时间: {boot_time}\n")

    print("🧠 CPU 使用率:")
    print(progress_bar(cpu))

    print("\n🐏 内存使用率:")
    print(progress_bar(mem.percent))

    print("\n💾 磁盘使用率:")
    print(progress_bar(disk.percent))
    print()


def show_traffic():
    cfg = load_config()
    target_iface = cfg.get("vnstat_interface", "")

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
            print(f"{YELLOW}⚠️ vnStat 暂无任何接口流量数据。{RESET}")
            return

        interface = None

        if target_iface:
            for item in interfaces:
                if item.get("name") == target_iface:
                    interface = item
                    break

        if interface is None:
            interface = interfaces[0]

        months = interface.get("traffic", {}).get("month", [])

        if not months:
            print(
                f"{YELLOW}⚠️ 接口 {interface.get('name', '未知')} "
                f"暂无本月流量数据。{RESET}"
            )
            return

        current_month = months[-1]

        rx = round(current_month.get("rx", 0) / 1024**3, 2)
        tx = round(current_month.get("tx", 0) / 1024**3, 2)
        total = round(rx + tx, 2)

        try:
            limit_gb = int(cfg.get("limit_gb", 0) or 0)
        except (TypeError, ValueError):
            limit_gb = 0

        limit_text = (
            f"{limit_gb} GB"
            if limit_gb > 0
            else "未设置"
        )

        print(
            f"\n{CYAN}{BOLD}📡 流量统计 "
            f"({interface.get('name', '未知')}){RESET}"
        )
        print(f"⬇️ 下载: {rx} GB")
        print(f"⬆️ 上传: {tx} GB")
        print(f"📊 总计: {total} GB")
        print(f"🔔 告警阈值: {limit_text}")
        print("🛡 超限行为: 仅通知，不自动关机\n")

    except FileNotFoundError:
        print(f"{RED}⚠️ 未安装 vnStat。{RESET}")

    except subprocess.TimeoutExpired:
        print(f"{RED}⚠️ 获取流量统计超时。{RESET}")

    except subprocess.CalledProcessError as e:
        error = e.stderr.strip() or "未知错误"
        print(f"{RED}⚠️ vnStat 执行失败: {error}{RESET}")

    except Exception as e:
        print(f"{RED}⚠️ 无法获取流量: {e}{RESET}")


# ===================== 系统操作 =====================
def reboot_vps():
    confirm = input(
        f"{RED}⚠️ 确定要重启 VPS 吗？"
        f"请输入 REBOOT 确认: {RESET}"
    ).strip()

    if confirm != "REBOOT":
        print(f"{YELLOW}已取消重启。{RESET}")
        return

    print(f"{YELLOW}🔄 正在请求重启 VPS...{RESET}")
    subprocess.run(["systemctl", "reboot"], check=False)


def shutdown_vps():
    confirm = input(
        f"{RED}⚠️ 确定要关机 VPS 吗？"
        f"请输入 POWEROFF 确认: {RESET}"
    ).strip()

    if confirm != "POWEROFF":
        print(f"{YELLOW}已取消关机。{RESET}")
        return

    print(f"{RED}🛑 正在请求关闭 VPS...{RESET}")
    subprocess.run(["systemctl", "poweroff"], check=False)


def restart_bot_service():
    print(f"{YELLOW}🔄 正在重启后台 Bot 服务...{RESET}")

    result = subprocess.run(
        ["systemctl", "restart", "vpsbot"],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode == 0:
        print(f"{GREEN}✅ Bot 服务已重启。{RESET}")
    else:
        error = result.stderr.strip() or "未知错误"
        print(f"{RED}❌ Bot 服务重启失败: {error}{RESET}")


def stop_panel():
    print(f"{YELLOW}已退出管理面板。后台 Bot 服务仍会继续运行。{RESET}")
    sys.exit(0)


def uninstall_script():
    """
    仅允许卸载 install.sh 安装在 /opt/vpsbot 的实例。
    避免在测试目录、root 家目录或其他路径误删文件。
    """
    actual_dir = INSTALL_DIR.resolve()

    if actual_dir != EXPECTED_INSTALL_DIR:
        print(f"{RED}❌ 拒绝卸载：脚本目录不符合预期。{RESET}")
        print(f"{YELLOW}当前目录: {actual_dir}{RESET}")
        print(f"{YELLOW}预期目录: {EXPECTED_INSTALL_DIR}{RESET}")
        return

    confirm = input(
        f"{RED}⚠️ 即将永久删除以下内容：\n"
        f"  - {EXPECTED_INSTALL_DIR}\n"
        f"  - {SYSTEMD_SERVICE}\n"
        f"  - {SHORTCUT_CMD}\n\n"
        f"请输入 DELETE 确认卸载: {RESET}"
    ).strip()

    if confirm != "DELETE":
        print(f"{YELLOW}已取消卸载。{RESET}")
        return

    try:
        print(f"{YELLOW}⏳ 正在停止并移除 systemd 服务...{RESET}")

        subprocess.run(
            ["systemctl", "disable", "--now", "vpsbot"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        if SYSTEMD_SERVICE.exists():
            SYSTEMD_SERVICE.unlink()
            print(f"{GREEN}✅ 已删除 systemd 服务: {SYSTEMD_SERVICE}{RESET}")

        subprocess.run(["systemctl", "daemon-reload"], check=False)

        if SHORTCUT_CMD.exists() or SHORTCUT_CMD.is_symlink():
            SHORTCUT_CMD.unlink()
            print(f"{GREEN}✅ 已删除快捷命令: {SHORTCUT_CMD}{RESET}")

        if EXPECTED_INSTALL_DIR.exists():
            shutil.rmtree(EXPECTED_INSTALL_DIR)
            print(f"{GREEN}✅ 已删除安装目录: {EXPECTED_INSTALL_DIR}{RESET}")

        print(f"{GREEN}✅ VPS Bot 已卸载。{RESET}")
        print(f"{YELLOW}提示：vnStat 与 Python 系统依赖不会自动卸载。{RESET}")

    except Exception as e:
        print(f"{RED}⚠️ 卸载失败: {e}{RESET}")

    sys.exit(0)


# ===================== 菜单 =====================
def menu():
    while True:
        clear_screen()
        cfg = load_config()

        try:
            limit_gb = int(cfg.get("limit_gb", 0) or 0)
        except (TypeError, ValueError):
            limit_gb = 0

        alert_status = (
            f"{limit_gb} GB"
            if limit_gb > 0
            else "关闭"
        )

        print(f"""
========================
{CYAN}{BOLD}   VPS 快捷管理面板
   Version {VERSION}{RESET}
========================
流量告警阈值: {alert_status}
超限行为: 仅通知，不自动关机
安装目录: {INSTALL_DIR}
========================
{YELLOW}1) 修改 Telegram Token{RESET}
{YELLOW}2) 修改 Admin ID{RESET}
{YELLOW}3) 修改流量告警阈值{RESET}
{GREEN}4) 查看 VPS 状态{RESET}
{GREEN}5) 查看流量统计{RESET}
{YELLOW}6) 重启后台 Bot 服务{RESET}
{RED}7) 重启 VPS{RESET}
{RED}8) 关机 VPS{RESET}
{YELLOW}9) 退出管理面板{RESET}
{RED}10) 卸载管理脚本与后台 Bot{RESET}
{YELLOW}0) 退出{RESET}
========================
""")

        choice = input("请输入选项: ").strip()

        if choice == "1":
            set_token()
            pause()

        elif choice == "2":
            set_admin()
            pause()

        elif choice == "3":
            set_limit()
            pause()

        elif choice == "4":
            show_status()
            pause()

        elif choice == "5":
            show_traffic()
            pause()

        elif choice == "6":
            restart_bot_service()
            pause()

        elif choice == "7":
            reboot_vps()
            pause()

        elif choice == "8":
            shutdown_vps()
            pause()

        elif choice == "9":
            stop_panel()

        elif choice == "10":
            uninstall_script()

        elif choice == "0":
            print(f"{YELLOW}退出管理面板。{RESET}")
            break

        else:
            print(f"{RED}❌ 无效选项。{RESET}")
            pause()


if __name__ == "__main__":
    require_root()
    menu()
