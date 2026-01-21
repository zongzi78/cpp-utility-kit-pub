import os
import sys
import csv
import argparse
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple

# 提前设置matplotlib后端为Agg（无GUI）
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.font_manager as fm
except ImportError:
    plt = None

# 内存单位转换（与主程序保持一致）
MEMORY_UNIT = "MB"
UNIT_CONVERTER = {
    "B": 1,
    "KB": 1024,
    "MB": 1024 * 1024,
    "GB": 1024 * 1024 * 1024
}

# 字体文件配置 - 随程序分发的字体文件路径
# 优先从程序同级的fonts文件夹读取simhei.ttf
FONT_FILE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),  # 获取当前脚本所在目录
    "fonts", 
    "simhei.ttf"  # 你需要放在fonts文件夹中的字体文件
)
# 备选字体列表（按优先级排序）
FONT_PRIORITY_LIST = ["simhei", "Microsoft YaHei", "DejaVu Sans", "WenQuanYi Micro Hei", "Heiti TC"]

def format_duration(total_seconds: float) -> str:
    """
    将总秒数格式化为「x小时y分钟z秒」的可读格式
    优化点：
        - 秒数为整数时显示整数（如25秒，而非25.0秒）
        - 秒数有小数时保留1位（如25.5秒）
        - 无小时/分钟时自动省略对应部分
    """
    total_seconds = max(0, total_seconds)
    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    seconds = total_seconds % 60
    
    # 处理秒数显示格式：整数则去小数，非整数保留1位
    if seconds.is_integer():
        seconds_str = f"{int(seconds)}秒"
    else:
        seconds_str = f"{round(seconds, 1)}秒"
    
    parts = []
    if hours > 0:
        parts.append(f"{hours}小时")
    if minutes > 0 or (hours > 0 and seconds > 0):
        parts.append(f"{minutes}分钟")
    if seconds > 0 or (hours == 0 and minutes == 0):
        parts.append(seconds_str)
    
    return "".join(parts) if parts else "0秒"

def parse_time_range(time_range_str: str) -> Optional[Tuple[datetime, datetime]]:
    """
    解析时间范围参数（格式：YYYY-MM-DDTHH:MM:SS.fff,YYYY-MM-DDTHH:MM:SS.fff 或 YYYY-MM-DD HH:MM:SS,YYYY-MM-DD HH:MM:SS）
    处理逻辑：
        - 起始时间：向下取整到秒（截断毫秒）
        - 终止时间：向上取整到秒（去掉毫秒后+1秒）
    """
    if not time_range_str:
        return None
    
    try:
        # 兼容T分隔和空格分隔的格式
        time_range_str = time_range_str.replace("T", " ")
        start_str, end_str = time_range_str.split(',')
        
        # 解析原始时间（保留毫秒）
        start_time = datetime.fromisoformat(start_str.strip())
        end_time = datetime.fromisoformat(end_str.strip())
        
        # 起始时间向下取整到秒（截断毫秒）
        start_time_floor = start_time.replace(microsecond=0)
        # 终止时间向上取整到秒（去掉毫秒+1秒）
        end_time_ceil = end_time.replace(microsecond=0) + timedelta(seconds=1)
        
        return (start_time_floor, end_time_ceil)
    except Exception as e:
        print(f"[WARNING] 时间范围解析失败：{str(e)}，将使用全部数据")
        return None

def get_pid_and_name_from_log(log_path: str) -> Tuple[Optional[int], Optional[str]]:
    """从日志文件中获取PID和进程名称"""
    try:
        with open(log_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            # 跳过表头
            next(reader)
            # 读取第一行数据
            first_row = next(reader)
            if len(first_row) >= 3:
                pid = int(first_row[1]) if first_row[1].isdigit() else None
                name = first_row[2]
                return (pid, name)
    except Exception as e:
        print(f"[WARNING] 从日志文件获取PID和名称失败：{str(e)}")
    return (None, None)

def setup_chinese_font():
    """
    配置matplotlib中文显示：
    1. 优先使用本地fonts文件夹中的字体文件
    2. 其次自动检测系统可用字体
    3. 最后使用matplotlib自带字体兜底
    """
    # 1：使用本地分发的字体文件（最高优先级）
    if os.path.exists(FONT_FILE_PATH):
        try:
            # 注册本地字体文件
            font_prop = fm.FontProperties(fname=FONT_FILE_PATH)
            fm.fontManager.addfont(FONT_FILE_PATH)
            font_name = font_prop.get_name()
            
            # 设置字体
            plt.rcParams["font.sans-serif"] = [font_name] + FONT_PRIORITY_LIST
            plt.rcParams["axes.unicode_minus"] = False
            # print(f"[INFO] 使用本地字体文件: {FONT_FILE_PATH} (字体名称: {font_name})")
            return
        except Exception as e:
            print(f"[WARNING] 加载本地字体文件失败: {e}，尝试使用系统字体")
    
    # 2：自动检测系统可用字体
    available_fonts = [f.name for f in fm.fontManager.ttflist]
    selected_font = None
    
    for font_name in FONT_PRIORITY_LIST:
        if font_name in available_fonts:
            selected_font = font_name
            break
    
    if selected_font:
        plt.rcParams["font.sans-serif"] = [selected_font] + FONT_PRIORITY_LIST
        plt.rcParams["axes.unicode_minus"] = False
        # print(f"[INFO] 使用系统字体: {selected_font}")
    else:
        # 3：使用matplotlib自带字体作为最后的兜底
        plt.rcParams["font.sans-serif"] = ["DejaVu Sans", "Arial Unicode MS"]
        plt.rcParams["axes.unicode_minus"] = False
        # print(f"[WARNING] 未找到中文支持字体，使用默认字体，可能导致中文显示异常")

def analyze_log(
    log_path: str,
    output_dir: Optional[str] = None,
    time_range: Optional[Tuple[datetime, datetime]] = None,
    is_standalone: bool = True,
    show_rss: bool = True,
    show_private: bool = True,
    show_vms: bool = True
) -> None:
    """
    分析日志文件并生成报告和趋势图
    
    参数:
        log_path: 日志文件路径
        output_dir: 输出目录，None则使用日志文件所在目录
        time_range: 时间范围筛选，None则分析全部数据
        is_standalone: 是否为独立运行模式（影响输出文件名）
        show_rss: 是否显示物理内存（工作集）统计
        show_private: 是否显示专用工作集统计
        show_vms: 是否显示虚拟内存统计
    """
    if not os.path.exists(log_path):
        print(f"[ERROR] 日志文件 {log_path} 不存在")
        return
    
    # 获取输出目录
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    else:
        output_dir = os.path.dirname(log_path) or '.'
    
    # 从日志获取PID和进程名称
    proc_pid, proc_name = get_pid_and_name_from_log(log_path)
    proc_pid = proc_pid or "unknown"
    proc_name = proc_name or "unknown_process"
    
    # 读取日志数据
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [row for row in reader if row["物理内存(MB)"] and row["物理内存(MB)"] != ""]
        if not rows:
            print("[WARNING] 日志文件无有效数据，无法生成分析报告")
            return
    except Exception as e:
        print(f"[ERROR] 读取日志文件失败：{str(e)}")
        return
    
    # 数据预处理：先处理整体数据（所有有效日志），再处理筛选后的数据
    try:
        # 1. 处理整体日志数据（未筛选）
        all_processed_rows = []
        for row in rows:
            try:
                row_time = datetime.fromisoformat(row["采样时间(ISO8601)"])
                all_processed_rows.append({
                    "time": row_time,
                    "rss": float(row["物理内存(MB)"]),
                    "vms": float(row["虚拟内存(MB)"]),
                    "private": float(row["专用工作集(MB)"]),
                    "mem_percent": float(row["物理内存占系统总内存(%)"])
                })
            except Exception as e:
                print(f"[WARNING] 跳过无效数据行：{str(e)}")
                continue
        
        if not all_processed_rows:
            print("[WARNING] 没有有效日志数据，无法生成分析报告")
            return
        
        # 整体数据统计
        all_time_list = [row["time"] for row in all_processed_rows]
        total_samples_all = len(all_processed_rows)
        all_duration_seconds = (all_time_list[-1] - all_time_list[0]).total_seconds()
        all_duration_str = format_duration(all_duration_seconds)
        
        # 2. 处理筛选后的数据（分析数据）
        processed_rows = []
        if time_range:
            start_time, end_time = time_range
            for row in all_processed_rows:
                if start_time <= row["time"] <= end_time:
                    processed_rows.append(row)
        else:
            # 未指定时间范围，分析全部数据
            processed_rows = all_processed_rows
            time_range = (all_time_list[0].replace(microsecond=0), 
                          all_time_list[-1].replace(microsecond=0) + timedelta(seconds=1))
        
        if not processed_rows:
            print("[WARNING] 没有符合分析时间范围的数据，无法生成分析报告")
            return
        
        # 分析数据统计
        analysis_time_list = [row["time"] for row in processed_rows]
        total_samples_analysis = len(processed_rows)
        analysis_duration_seconds = (analysis_time_list[-1] - analysis_time_list[0]).total_seconds()
        analysis_duration_str = format_duration(analysis_duration_seconds)
        
        # 提取核心分析数据
        rss_list = [row["rss"] for row in processed_rows]
        private_list = [row["private"] for row in processed_rows]
        vms_list = [row["vms"] for row in processed_rows]
        
        # 计算统计指标
        # 物理内存（RSS）
        avg_rss = round(sum(rss_list) / total_samples_analysis, 2) if show_rss else 0
        max_rss = round(max(rss_list), 2) if show_rss else 0
        min_rss = round(min(rss_list), 2) if show_rss else 0
        # 专用工作集
        avg_private = round(sum(private_list) / total_samples_analysis, 2) if show_private else 0
        max_private = round(max(private_list), 2) if show_private else 0
        min_private = round(min(private_list), 2) if show_private else 0
        # 虚拟内存
        avg_vms = round(sum(vms_list) / total_samples_analysis, 2) if show_vms else 0
        max_vms = round(max(vms_list), 2) if show_vms else 0
        min_vms = round(min(vms_list), 2) if show_vms else 0
        
        # 计算各内存指标增长率（每分钟）
        def calculate_growth_rate(values: list, duration_min: float) -> float:
            """计算内存增长率（MB/分钟）"""
            if duration_min <= 0 or len(values) <= 1:
                return 0.0
            return round((values[-1] - values[0]) / duration_min, 2)
        
        analysis_duration_min = analysis_duration_seconds / 60  # 分析时长（分钟）
        rss_growth_rate = calculate_growth_rate(rss_list, analysis_duration_min) if show_rss else 0
        private_growth_rate = calculate_growth_rate(private_list, analysis_duration_min) if show_private else 0
        vms_growth_rate = calculate_growth_rate(vms_list, analysis_duration_min) if show_vms else 0
        
        # 生成文件名（独立模式添加标记）
        base_name = os.path.splitext(os.path.basename(log_path))[0]
        if is_standalone:
            report_suffix = "_analysis_report.txt"
            graph_suffix = "_analysis_trend.png"
        else:
            report_suffix = "_report.txt"
            graph_suffix = "_trend.png"
        
        report_path = os.path.join(output_dir, f"{base_name}{report_suffix}")
        graph_path = os.path.join(output_dir, f"{base_name}{graph_suffix}")
        
        # 生成文本报告（按要求拆分监控/分析维度）
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("===== 进程内存监控分析报告 =====\n")
            f.write(f"监控进程：PID={proc_pid} | 名称={proc_name}\n")
            
            # 监控维度（整体日志数据）
            f.write(f"\n【监控维度（全量数据）】\n")
            f.write(f"监控时间段：{all_time_list[0].strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]} ~ {all_time_list[-1].strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}\n")
            f.write(f"监控时长：{all_duration_str} | 总采样次数：{total_samples_all}\n")
            
            # 分析维度（筛选后数据）
            f.write(f"\n【分析维度（指定时段）】\n")
            f.write(f"分析时间范围：{time_range[0].strftime('%Y-%m-%d %H:%M:%S')} ~ {time_range[1].strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"分析时长：{analysis_duration_str} | 时段内采样次数：{total_samples_analysis}\n")
            
            # 内存统计（基于分析维度，根据参数控制显示）
            if show_rss:
                f.write("\n【物理内存（工作集）统计】\n")
                f.write(f"平均值：{avg_rss} MB | 最大值：{max_rss} MB | 最小值：{min_rss} MB\n")
                f.write(f"内存增长率：{rss_growth_rate} MB/分钟（正值=增长，负值=下降）\n")
            
            if show_private:
                f.write("\n【专用工作集统计】\n")
                f.write(f"平均值：{avg_private} MB | 最大值：{max_private} MB | 最小值：{min_private} MB\n")
                f.write(f"内存增长率：{private_growth_rate} MB/分钟（正值=增长，负值=下降）\n")
            
            if show_vms:
                f.write("\n【虚拟内存统计】\n")
                f.write(f"平均值：{avg_vms} MB | 最大值：{max_vms} MB | 最小值：{min_vms} MB\n")
                f.write(f"内存增长率：{vms_growth_rate} MB/分钟（正值=增长，负值=下降）\n")
            
            f.write("\n===== 报告生成完成 =====\n")
        print(f"[INFO] 分析报告已生成：{report_path}")
        
        # 生成趋势图
        try:
            if plt is None:
                raise ImportError("matplotlib未安装")
            
            # 配置中文字体（优先本地字体文件）
            setup_chinese_font()
            
            fig, ax = plt.subplots(figsize=(12, 6))
            if show_rss:
                ax.plot(analysis_time_list, rss_list, label=f"物理内存（工作集）({MEMORY_UNIT})", color="blue", linewidth=1.5)
            if show_private:
                ax.plot(analysis_time_list, private_list, label=f"专用工作集({MEMORY_UNIT})", color="red", linewidth=1.5)
            if show_vms:
                ax.plot(analysis_time_list, vms_list, label=f"虚拟内存({MEMORY_UNIT})", color="green", linewidth=1.0, linestyle="--")
            
            ax.set_xlabel("采样时间", fontsize=10)
            ax.set_ylabel(f"内存占用({MEMORY_UNIT})", fontsize=10)
            ax.set_title(f"进程内存占用趋势（PID={proc_pid} | {proc_name}）", fontsize=12)
            ax.legend(fontsize=9)
            ax.grid(True, alpha=0.3)
            plt.xticks(rotation=45)
            plt.tight_layout()
            
            plt.savefig(graph_path, dpi=150, bbox_inches="tight")
            plt.close()
            print(f"[INFO] 内存趋势图已生成：{graph_path}")
        except ImportError:
            print("[WARNING] 未安装matplotlib，跳过趋势图生成（执行：pip install matplotlib 安装）")
        except Exception as e:
            print(f"[WARNING] 生成趋势图失败：{str(e)}")
            
    except Exception as e:
        print(f"[ERROR] 生成分析报告失败：{str(e)}")

def main():
    parser = argparse.ArgumentParser(description="进程内存日志分析工具")
    parser.add_argument("log_file", help="日志文件路径")
    parser.add_argument("--output-dir", help="报告输出目录，默认与日志文件同目录")
    parser.add_argument("--time-range", help="时间范围筛选（格式：YYYY-MM-DDTHH:MM:SS.fff,YYYY-MM-DDTHH:MM:SS.fff 或 YYYY-MM-DD HH:MM:SS,YYYY-MM-DD HH:MM:SS）")
    # 添加控制显示条目的参数
    parser.add_argument("--no-rss", action="store_false", dest="show_rss", help="不显示物理内存（工作集）统计")
    parser.add_argument("--no-private", action="store_false", dest="show_private", help="不显示专用工作集统计")
    parser.add_argument("--no-vms", action="store_false", dest="show_vms", help="不显示虚拟内存统计")
    args = parser.parse_args()
    
    # 解析时间范围
    time_range = parse_time_range(args.time_range)
    
    # 执行分析
    analyze_log(
        log_path=args.log_file,
        output_dir=args.output_dir,
        time_range=time_range,
        is_standalone=True,
        show_rss=args.show_rss,
        show_private=args.show_private,
        show_vms=args.show_vms
    )

if __name__ == "__main__":
    main()