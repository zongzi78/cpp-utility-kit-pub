import os
import sys
import csv
import time
import signal
import argparse
import configparser
import warnings
import psutil
import os
import platform
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple, Dict, Any

# 导入内存分析模块
from memory_analyzer import analyze_log

def get_program_dir():
    # """
    # 获取程序的实际运行目录：
    # - 开发模式：返回当前.py文件所在目录
    # - exe模式：返回exe文件所在目录
    # """
    if getattr(sys, "frozen", False):
        # 打包成exe后的情况
        # sys.executable 是exe文件的完整路径，dirname取其所在目录
        program_dir = Path(os.path.dirname(sys.executable))
    else:
        # 开发阶段运行.py文件的情况
        program_dir = Path(os.path.dirname(os.path.abspath(__file__)))
    return program_dir


# 全局变量：控制程序退出
EXIT_FLAG = False
# 默认配置
PROGRAM_DIR = get_program_dir()
DEFAULT_CONFIG_PATH = PROGRAM_DIR / "./config.ini"
DEFAULT_INTERVAL = 5  # 默认采样间隔（秒）
DEFAULT_LOG_PATH = PROGRAM_DIR / "./mem_monitor_logs"  # 默认日志目录
DEFAULT_MAX_LOG_SIZE = 100 * 1024 * 1024  # 默认单日志文件最大size（100MB）
MEMORY_UNIT = "MB"  # 内存单位（支持 B/KB/MB/GB）
UNIT_CONVERTER = {"B": 1, "KB": 1024, "MB": 1024 * 1024, "GB": 1024 * 1024 * 1024}

# 屏蔽NumPy版本警告（核心修复1）
warnings.filterwarnings("ignore", category=UserWarning, module="numpy")
# 提前设置matplotlib后端为Agg（无GUI，避免Qt依赖冲突）（核心修复2）
try:
    import matplotlib

    matplotlib.use("Agg")  # 强制使用非交互式后端，不加载Qt
    import matplotlib.pyplot as plt
except ImportError:
    plt = None


def signal_handler(signum, frame):
    """信号处理：捕获Ctrl+C/退出信号，优雅终止"""
    global EXIT_FLAG
    print("\n[INFO] 接收到退出信号，正在优雅终止监控...")
    EXIT_FLAG = True


def init_signal():
    """初始化信号处理"""
    signal.signal(signal.SIGINT, signal_handler)  # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)  # 系统终止信号（Linux/macOS）
    if sys.platform == "win32":
        # Windows下兼容Ctrl+C
        try:
            import win32api

            win32api.SetConsoleCtrlHandler(lambda sig: signal_handler(sig, None), True)
        except ImportError:
            print(
                "[WARNING] 未安装pywin32，Windows下Ctrl+C可能无法正常捕获（建议执行：pip install pywin32）"
            )


def convert_memory(value: int, unit: str = MEMORY_UNIT) -> float:
    """转换内存单位（字节 -> 指定单位）"""
    if value <= 0:
        return 0.0
    return round(value / UNIT_CONVERTER[unit], 2)


def check_numpy_version():
    """检测NumPy版本，提示兼容问题"""
    try:
        import numpy as np

        if np.__version__ >= "2.0.0":
            print("[WARNING] 当前NumPy版本为2.x，可能与matplotlib依赖的模块冲突！")
            print(
                "[WARNING] 建议降级NumPy：pip install 'numpy<2' 或升级PySide2：pip install --upgrade PySide2"
            )
    except ImportError:
        pass  # 无NumPy则跳过


def load_config(config_path: str) -> Dict[str, Any]:
    """加载配置文件"""
    config = configparser.ConfigParser()
    config_data = {
        "pid": None,
        "name": None,
        "interval": DEFAULT_INTERVAL,
        "log_path": DEFAULT_LOG_PATH,
        "max_log_size": DEFAULT_MAX_LOG_SIZE,
        "show_rss": True,
        "show_private": True,
        "show_vms": True,
    }
    if not os.path.exists(config_path):
        print(f"[INFO] 配置文件 {config_path} 不存在，使用默认配置")
        return config_data

    try:
        config.read(config_path, encoding="utf-8")
        if "MONITOR" in config.sections():
            # 解析配置项
            config_data["pid"] = config.getint("MONITOR", "pid", fallback=None)
            config_data["name"] = config.get("MONITOR", "name", fallback=None)
            config_data["interval"] = config.getint(
                "MONITOR", "interval", fallback=DEFAULT_INTERVAL
            )
            config_data["log_path"] = config.get(
                "MONITOR", "log_path", fallback=DEFAULT_LOG_PATH
            )
            config_data["max_log_size"] = config.getint(
                "MONITOR", "max_log_size", fallback=DEFAULT_MAX_LOG_SIZE
            )

        if "ANALYSIS" in config.sections():
            # 解析分析报告配置项
            config_data["show_rss"] = config.getboolean(
                "ANALYSIS", "show_rss", fallback=True
            )
            config_data["show_private"] = config.getboolean(
                "ANALYSIS", "show_private", fallback=True
            )
            config_data["show_vms"] = config.getboolean(
                "ANALYSIS", "show_vms", fallback=True
            )

        print(f"[INFO] 已加载配置文件：{config_path}")
    except Exception as e:
        print(f"[WARNING] 配置文件解析失败：{str(e)}，使用默认配置")
    return config_data


def list_running_processes() -> list:
    """列出当前运行的进程（去重+关键信息），按进程名称小写排序"""
    processes = []
    seen_pids = set()
    for proc in psutil.process_iter(["pid", "name", "create_time", "username"]):
        try:
            if proc.pid in seen_pids:
                continue
            seen_pids.add(proc.pid)
            create_time = datetime.fromtimestamp(proc.info["create_time"]).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            processes.append(
                {
                    "pid": proc.pid,
                    "name": proc.info["name"] or "未知进程",
                    "create_time": create_time,
                    "username": proc.info["username"] or "未知用户",
                }
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    # 按进程名称小写排序（核心优化点）
    processes.sort(key=lambda x: x["name"].lower())
    return processes


def select_process_interactive() -> Optional[int]:
    """交互式选择进程"""
    print("\n===== 运行中的进程列表（按名称排序） =====")
    processes = list_running_processes()
    if not processes:
        print("[ERROR] 未检测到运行的进程！")
        return None

    # 打印进程列表
    for idx, proc in enumerate(processes, 1):
        print(
            f"{idx:3d} | PID:{proc['pid']:6d} | 名称:{proc['name']:<20} | 启动时间:{proc['create_time']} | 用户:{proc['username']}"
        )

    # 选择进程
    while True:
        try:
            choice = input("\n请输入要监控的进程序号（输入q退出）：")
            if choice.lower() == "q":
                return None
            choice_idx = int(choice) - 1
            if 0 <= choice_idx < len(processes):
                target_pid = processes[choice_idx]["pid"]
                print(
                    f"[INFO] 已选择进程：PID={target_pid}，名称={processes[choice_idx]['name']}"
                )
                return target_pid
            else:
                print("[ERROR] 序号超出范围，请重新输入！")
        except ValueError:
            print("[ERROR] 输入无效，请输入数字序号！")
        except KeyboardInterrupt:
            return None


def get_process_by_pid(pid: int) -> Optional[psutil.Process]:
    """通过PID获取进程对象，校验有效性"""
    try:
        proc = psutil.Process(pid)
        # 校验进程是否存活
        if not proc.is_running():
            print(f"[ERROR] PID={pid} 的进程已终止！")
            return None
        return proc
    except psutil.NoSuchProcess:
        print(f"[ERROR] 未找到PID={pid} 的进程！")
        return None
    except psutil.AccessDenied:
        print(f"[ERROR] 无权限访问PID={pid} 的进程（需管理员/root权限）！")
        return None


def get_process_by_name(name: str) -> Optional[int]:
    """通过进程名查找PID（处理重名，让用户选择）"""
    matched_procs = []
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            if name.lower() in proc.info["name"].lower():
                matched_procs.append({"pid": proc.pid, "name": proc.info["name"]})
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if not matched_procs:
        print(f"[ERROR] 未找到名称包含「{name}」的进程！")
        return None
    elif len(matched_procs) == 1:
        pid = matched_procs[0]["pid"]
        print(f"[INFO] 找到唯一匹配进程：PID={pid}，名称={matched_procs[0]['name']}")
        return pid
    else:
        print(f"\n===== 找到{len(matched_procs)}个名称包含「{name}」的进程 =====")
        for idx, proc in enumerate(matched_procs, 1):
            print(f"{idx:3d} | PID:{proc['pid']:6d} | 名称:{proc['name']}")
        while True:
            try:
                choice = input("\n请输入要监控的进程序号（输入q退出）：")
                if choice.lower() == "q":
                    return None
                choice_idx = int(choice) - 1
                if 0 <= choice_idx < len(matched_procs):
                    return matched_procs[choice_idx]["pid"]
                else:
                    print("[ERROR] 序号超出范围，请重新输入！")
            except ValueError:
                print("[ERROR] 输入无效，请输入数字序号！")


def get_log_file_path(proc_pid: int, proc_name: str, log_dir: str) -> str:
    """生成日志文件路径（格式：mem_monitor_进程名_PID_启动时间.log）"""
    start_time = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_proc_name = proc_name.replace("/", "_").replace("\\", "_").replace(":", "_")
    log_filename = f"mem_monitor_{safe_proc_name}_{proc_pid}_{start_time}.log"
    return os.path.join(log_dir, log_filename)


def init_log_dir(log_dir: str) -> None:
    """初始化日志目录（不存在则创建）"""
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
        print(f"[INFO] 日志目录已创建：{log_dir}")


def get_next_log_file(current_log_path: str) -> str:
    """日志轮转：生成下一个日志文件路径（加序号）"""
    dir_name = os.path.dirname(current_log_path)
    file_name = os.path.basename(current_log_path)
    name_parts = file_name.split(".")
    if len(name_parts) == 2:
        base_name, ext = name_parts
        # 检查是否已有序号
        if "_" in base_name:
            last_part = base_name.split("_")[-1]
            if last_part.isdigit():
                seq = int(last_part) + 1
                new_base_name = "_".join(base_name.split("_")[:-1]) + f"_{seq}"
            else:
                new_base_name = base_name + "_1"
        else:
            new_base_name = base_name + "_1"
        new_log_path = os.path.join(dir_name, f"{new_base_name}.{ext}")
    else:
        new_log_path = current_log_path.replace(".log", "_1.log")
    return new_log_path


def write_log_header(log_file: csv.writer) -> None:
    """写入日志表头（新增专用工作集字段）"""
    log_file.writerow(
        [
            "采样时间(ISO8601)",
            "进程PID",
            "进程名称",
            f"物理内存({MEMORY_UNIT})",
            f"虚拟内存({MEMORY_UNIT})",
            f"专用工作集({MEMORY_UNIT})",  # 新增字段
            "物理内存占系统总内存(%)",
            "备注",
        ]
    )


def sample_process_memory(proc: psutil.Process) -> Tuple[Optional[dict], str]:
    """采样进程内存数据（新增专用工作集）"""
    try:
        # 基础内存信息
        mem_info = (
            proc.memory_full_info()
            if hasattr(proc, "memory_full_info")
            else proc.memory_info()
        )
        rss = convert_memory(mem_info.rss)  # 物理内存（工作集）
        vms = convert_memory(mem_info.vms)  # 虚拟内存
        # private = (
        #     convert_memory(mem_info.private) if hasattr(mem_info, "private") else 0.0
        # )  # 专用工作集
        # 跨平台兼容获取专用工作集（修复Linux下private恒为0的问题）
        private = 0.0
        system_type = platform.system()
        if system_type == "Windows":
            # Windows系统沿用原有逻辑
            private = convert_memory(mem_info.private) if hasattr(mem_info, "private") else 0.0
        elif system_type == "Linux":
            # Linux系统优先取uss（精准私有内存），无uss则用rss-shared估算
            if hasattr(mem_info, "uss"):
                private = convert_memory(mem_info.uss)
            elif hasattr(mem_info, "shared"):
                private = convert_memory(mem_info.rss - mem_info.shared)
            # 无任何可用字段时保持0.0

        # 系统总内存
        total_system_mem = psutil.virtual_memory().total
        mem_percent = round((mem_info.rss / total_system_mem) * 100, 2)

        # 采样时间（ISO8601，毫秒级）
        sample_time = datetime.now().isoformat(timespec="milliseconds")

        # 进程名称（避免进程退出导致获取失败）
        proc_name = proc.name() if proc.is_running() else "进程已终止"

        return {
            "sample_time": sample_time,
            "pid": proc.pid,
            "name": proc_name,
            "rss": rss,
            "vms": vms,
            "private": private,  # 新增字段
            "mem_percent": mem_percent,
        }, ""
    except psutil.NoSuchProcess:
        return None, "进程已终止"
    except psutil.AccessDenied:
        return None, "无权限读取内存信息"
    except Exception as e:
        return None, f"采集失败：{str(e)[:50]}"


def generate_analysis_report(
    log_path: str,
    proc_pid: int,
    proc_name: str,
    show_rss: bool = True,
    show_private: bool = True,
    show_vms: bool = True,
) -> None:
    """调用分析程序生成监控分析报告和趋势图"""
    try:
        analyze_log(
            log_path=log_path,
            is_standalone=False,
            show_rss=show_rss,
            show_private=show_private,
            show_vms=show_vms,
        )
    except Exception as e:
        print(f"[WARNING] 调用分析程序失败：{str(e)}")


def main():
    # 前置检测NumPy版本
    check_numpy_version()

    # 1. 解析命令行参数（调整：--config 默认为 None，而非 DEFAULT_CONFIG_PATH）
    parser = argparse.ArgumentParser(
        description="进程内存监控工具（支持配置文件/命令行/交互式）"
    )
    parser.add_argument(
        "--config", type=str, help=f"配置文件路径（不指定则不加载配置）"
    )
    parser.add_argument(
        "--pid", type=int, help="要监控的进程PID（优先级高于--name和配置文件）"
    )
    parser.add_argument(
        "--name", type=str, help="要监控的进程名（支持模糊匹配，优先级高于配置文件）"
    )
    parser.add_argument(
        "--interval",
        type=int,
        help=f"采样间隔（秒），默认{DEFAULT_INTERVAL}秒（覆盖配置文件）",
    )
    parser.add_argument("--log-path", type=str, help=f"日志保存目录（覆盖配置文件）")
    parser.add_argument(
        "--max-log-size",
        type=int,
        help=f"单日志文件最大大小（字节），默认{DEFAULT_MAX_LOG_SIZE}字节（覆盖配置文件）",
    )
    # 添加分析报告控制参数
    parser.add_argument(
        "--no-rss",
        action="store_false",
        dest="show_rss",
        help="分析报告不显示物理内存（工作集）统计",
    )
    parser.add_argument(
        "--no-private",
        action="store_false",
        dest="show_private",
        help="分析报告不显示专用工作集统计",
    )
    parser.add_argument(
        "--no-vms",
        action="store_false",
        dest="show_vms",
        help="分析报告不显示虚拟内存统计",
    )
    args = parser.parse_args()

    # 2. 初始化信号处理
    init_signal()

    # 3. 配置加载逻辑：仅当用户指定--config时才加载配置
    config_data = {
        "pid": None,
        "name": None,
        "interval": DEFAULT_INTERVAL,
        "log_path": DEFAULT_LOG_PATH,
        "max_log_size": DEFAULT_MAX_LOG_SIZE,
        "show_rss": True,
        "show_private": True,
        "show_vms": True,
    }
    if args.config:
        config_data = load_config(args.config)

    # 4. 合并配置（命令行 > 配置文件 > 默认值）
    final_config = {
        "pid": args.pid or config_data["pid"],
        "name": args.name or config_data["name"],
        "interval": args.interval or config_data["interval"],
        "log_path": args.log_path or config_data["log_path"],
        "max_log_size": args.max_log_size or config_data["max_log_size"],
        "show_rss": (
            args.show_rss if hasattr(args, "show_rss") else config_data["show_rss"]
        ),
        "show_private": (
            args.show_private
            if hasattr(args, "show_private")
            else config_data["show_private"]
        ),
        "show_vms": (
            args.show_vms if hasattr(args, "show_vms") else config_data["show_vms"]
        ),
    }

    # 5. 确定目标进程PID（核心修复：无pid/name时直接进入交互式）
    target_pid = None
    if final_config["pid"]:
        target_pid = final_config["pid"]
        # 校验PID有效性
        if not get_process_by_pid(target_pid):
            sys.exit(1)
    elif final_config["name"]:
        target_pid = get_process_by_name(final_config["name"])
        if not target_pid:
            sys.exit(1)
    else:
        # 无任何参数，直接进入交互式选择（忽略配置文件）
        target_pid = select_process_interactive()
        if not target_pid:
            print("[INFO] 用户取消选择，程序退出")
            sys.exit(0)

    # 6. 获取进程对象
    proc = get_process_by_pid(target_pid)
    if not proc:
        sys.exit(1)
    proc_name = proc.name()

    # 7. 初始化日志
    init_log_dir(final_config["log_path"])
    current_log_path = get_log_file_path(
        target_pid, proc_name, final_config["log_path"]
    )
    log_file = open(current_log_path, "a", newline="", encoding="utf-8")
    log_writer = csv.writer(log_file)

    # 若日志文件为空，写入表头
    if os.path.getsize(current_log_path) == 0:
        write_log_header(log_writer)
        log_file.flush()

    print(f"\n[INFO] 开始监控进程：PID={target_pid}，名称={proc_name}")
    print(f"[INFO] 采样间隔：{final_config['interval']}秒")
    print(f"[INFO] 日志文件：{current_log_path}")
    print(f"[INFO] 按Ctrl+C终止监控（退出后自动生成分析报告）...\n")

    # 8. 精准定时采样循环
    sample_count = 0
    next_sample_time = time.perf_counter()
    while not EXIT_FLAG:
        try:
            # 检查进程是否存活
            if not proc.is_running():
                print("[ERROR] 目标进程已终止，监控结束！")
                break

            # 采样内存数据
            sample_data, remark = sample_process_memory(proc)

            # 写入日志
            if sample_data:
                log_writer.writerow(
                    [
                        sample_data["sample_time"],
                        sample_data["pid"],
                        sample_data["name"],
                        sample_data["rss"],
                        sample_data["vms"],
                        sample_data["private"],  # 新增字段
                        sample_data["mem_percent"],
                        remark,
                    ]
                )
                # 控制台输出（新增专用工作集）
                print(
                    f"[{sample_data['sample_time']}] PID:{sample_data['pid']} | 物理内存:{sample_data['rss']} {MEMORY_UNIT} | 专用工作集:{sample_data['private']} {MEMORY_UNIT} | 虚拟内存:{sample_data['vms']} {MEMORY_UNIT} | 占比:{sample_data['mem_percent']}% | {remark}"
                )
                sample_count += 1
            else:
                # 采集失败，记录备注
                sample_time = datetime.now().isoformat(timespec="milliseconds")
                log_writer.writerow(
                    [sample_time, target_pid, proc_name, "", "", "", "", remark]
                )
                print(f"[{sample_time}] 采集失败：{remark}")

            # 日志刷新（避免崩溃丢失数据）
            log_file.flush()

            # 检查日志文件大小，触发轮转
            if os.path.getsize(current_log_path) >= final_config["max_log_size"]:
                print(
                    f"[INFO] 日志文件已达{final_config['max_log_size']/1024/1024:.1f}MB，触发轮转..."
                )
                log_file.close()
                current_log_path = get_next_log_file(current_log_path)
                log_file = open(current_log_path, "a", newline="", encoding="utf-8")
                log_writer = csv.writer(log_file)
                write_log_header(log_writer)
                log_file.flush()
                print(f"[INFO] 新日志文件：{current_log_path}")

            # 精准定时（补偿sleep误差）
            next_sample_time += final_config["interval"]
            sleep_time = next_sample_time - time.perf_counter()
            if sleep_time > 0:
                time.sleep(sleep_time)
            else:
                # 若采样耗时超过间隔，立即执行下一次
                next_sample_time = time.perf_counter()
                print(
                    f"[WARNING] 采样耗时超过间隔({final_config['interval']}秒)，跳过休眠"
                )

        except Exception as e:
            print(f"[ERROR] 采样循环异常：{str(e)}")
            # 休眠1秒避免死循环报错
            time.sleep(1)
            continue

    # 9. 程序退出清理
    log_file.close()
    print(f"\n[INFO] 监控结束！累计采样{sample_count}次")
    print(f"[INFO] 日志文件已保存至：{current_log_path}")

    # 10. 生成分析报告和趋势图
    print("\n[INFO] 开始生成监控分析报告...")
    generate_analysis_report(
        current_log_path,
        target_pid,
        proc_name,
        show_rss=final_config["show_rss"],
        show_private=final_config["show_private"],
        show_vms=final_config["show_vms"],
    )
    print("[INFO] 程序正常退出！")


if __name__ == "__main__":
    main()
