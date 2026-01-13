# 进程内存监控工具使用说明
## 一、工具简介
该工具是一款基于Python开发的跨平台进程内存监控程序，支持Windows/Linux/macOS系统。核心功能包括：
- 交互式选择或命令行指定目标进程
- 定时采样进程物理内存、虚拟内存、专用工作集等指标
- 自动生成CSV格式日志文件（支持日志轮转）
- 退出时自动生成内存分析报告和可视化趋势图（可配置显示指标）
- 支持配置文件、命令行参数、交互式三种启动方式


## 二、环境搭建
### 1. 创建Conda环境（推荐）
```bash
# 创建名为mem_monitor的Python 3.9环境（兼容3.7+）
conda create -n mem_monitor python=3.9 -y

# 激活环境
# Windows
conda activate mem_monitor
# Linux/macOS
source activate mem_monitor
```

### 2. 安装依赖包
```bash
# 基础依赖（必装）
pip install psutil

# Windows额外依赖（增强Ctrl+C捕获，可选）
pip install pywin32

# 可视化依赖（生成趋势图，可选）
pip install matplotlib

# 解决NumPy 2.x兼容问题（若安装matplotlib后出现版本警告）
pip install "numpy<2" --force-reinstall
```


## 三、文件准备
### 1. 程序文件
需准备以下文件：
- 监控主程序：`mem_monitor.py`
- 日志分析模块：`analyze_log.py`（自动被主程序调用，也可独立运行）
- 配置文件（可选）：`config.ini`


### 2. 配置文件（可选）
在程序同目录下创建 `config.ini` 文件，内容模板如下（新增分析报告配置）：
```ini
[MONITOR]
# 目标进程（二选一：pid/name，name支持模糊匹配）
pid = 1234
# name = chrome
# 采样间隔（秒）
interval = 5
# 日志保存目录
log_path = ./mem_monitor_logs
# 单日志文件最大大小（字节，100MB=104857600）
max_log_size = 104857600

[ANALYSIS]
; 分析报告是否显示物理内存（工作集）统计（默认True）
; True=显示，False=不显示
show_rss=True
; 分析报告是否显示专用工作集统计（默认True）
show_private=True
; 分析报告是否显示虚拟内存统计（默认True）
show_vms=True
```


## 四、使用方法
### 1. 基础使用（无参数启动，交互式选择进程）
#### 命令
```bash
cd D:\mem_monitor  # 进入程序目录
python mem_monitor.py
```
#### 操作流程
1. 程序自动列出所有运行中的进程（按名称排序），格式如下：
   ```
   ===== 运行中的进程列表（按名称排序） =====
     1 | PID:  1234 | 名称:chrome.exe        | 启动时间:2025-12-17 10:00:00 | 用户:admin
     2 | PID:  5678 | 名称:python.exe        | 启动时间:2025-12-17 10:05:00 | 用户:admin
   ```
2. 输入进程序号（如 `1`），按回车开始监控；输入 `q` 退出。
3. 监控过程中按 `Ctrl+C` 终止，程序会自动生成分析报告和趋势图。


### 2. 命令行参数启动（直接指定进程）
#### 2.1 指定PID监控
```bash
# 监控PID=1234的进程，采样间隔2秒，日志保存到指定目录
python mem_monitor.py --pid 1234 --interval 2 --log-path ./chrome_logs
```

#### 2.2 指定进程名监控（模糊匹配）
```bash
# 监控名称包含"python"的进程，单日志文件最大50MB
python mem_monitor.py --name python --max-log-size 52428800
```

#### 2.3 控制分析报告显示指标
```bash
# 监控PID=1234，分析报告不显示虚拟内存统计
python mem_monitor.py --pid 1234 --no-vms

# 监控名称包含"chrome"，分析报告仅显示物理内存统计
python mem_monitor.py --name chrome --no-private --no-vms
```


### 3. 配置文件启动
#### 3.1 使用默认配置文件（config.ini）
```bash
python mem_monitor.py --config ./config.ini
```

#### 3.2 使用自定义配置文件
```bash
python mem_monitor.py --config D:\config\my_config.ini
```


### 4. 混合参数启动（命令行参数覆盖配置文件）
```bash
# 配置文件中指定pid=1234和show_vms=False，但命令行覆盖为pid=5678且显示虚拟内存
python mem_monitor.py --config ./config.ini --pid 5678 --show-vms
```


### 5. 独立分析日志文件
可使用`analyze_log.py`单独分析已生成的日志文件：
```bash
# 示例：分析指定日志文件
python analyze_log.py ./mem_monitor_logs/mem_monitor_Weixin.exe_2352_20251218_090849.log
```


## 五、参数说明
| 参数 | 类型 | 说明 | 示例 |
|------|------|------|------|
| `--config` | 字符串 | 配置文件路径，不指定则不加载配置 | `--config ./config.ini` |
| `--pid` | 整数 | 目标进程PID（优先级最高） | `--pid 1234` |
| `--name` | 字符串 | 目标进程名（模糊匹配） | `--name chrome` |
| `--interval` | 整数 | 采样间隔（秒），默认5秒 | `--interval 1` |
| `--log-path` | 字符串 | 日志保存目录，默认`./mem_monitor_logs` | `--log-path ./my_logs` |
| `--max-log-size` | 整数 | 单日志文件最大大小（字节），默认104857600（100MB） | `--max-log-size 52428800` |
| `--no-rss` | 标志 | 分析报告不显示物理内存（工作集）统计 | `--no-rss` |
| `--no-private` | 标志 | 分析报告不显示专用工作集统计 | `--no-private` |
| `--no-vms` | 标志 | 分析报告不显示虚拟内存统计 | `--no-vms` |


## 六、输出文件说明
程序运行后会在指定日志目录生成以下文件：

| 文件类型 | 文件名示例 | 说明 |
|----------|------------|------|
| 监控日志 | `mem_monitor_chrome_1234_20251217_173340.log` | CSV格式，包含采样时间、PID、进程名、物理内存、虚拟内存、专用工作集、内存占比、备注 |
| 分析报告 | `mem_monitor_chrome_1234_20251217_173340_report.txt` | 文本格式，包含监控时长、采样次数、内存平均值/最大值/最小值、增长率等统计信息（显示内容受配置控制） |
| 独立分析报告 | `mem_monitor_chrome_1234_20251217_173340_independent_report.txt` | 独立分析工具生成的报告（格式与主程序报告一致） |
| 趋势图 | `mem_monitor_chrome_1234_20251217_173340_trend.png` | PNG格式，可视化展示内存变化趋势（显示内容受配置控制，需安装matplotlib） |
| 独立趋势图 | `mem_monitor_chrome_1234_20251217_173340_independent_trend.png` | 独立分析工具生成的趋势图（格式与主程序趋势图一致） |


## 七、关键指标说明
| 指标名称 | 含义 | Windows任务管理器对应项 |
|----------|------|------------------------|
| 物理内存（RSS） | 进程实际占用的物理内存总量 | 工作集（内存） |
| 虚拟内存（VMS） | 进程申请的虚拟地址空间总大小 | 虚拟内存 |
| 专用工作集 | 进程仅自身占用的物理内存（核心泄漏排查指标） | 内存（专用工作集） |
| 物理内存占比 | 进程物理内存占系统总内存的百分比 | - |


## 八、常见问题解决
### 1. NumPy版本冲突警告
**现象**：运行时出现 `NumPy 1.x cannot be run in NumPy 2.x` 警告  
**解决**：执行以下命令降级NumPy：
```bash
pip install "numpy<2" --force-reinstall
```

### 2. 趋势图无法生成
**现象**：提示“未安装matplotlib”或生成失败  
**解决**：安装matplotlib并确保版本兼容：
```bash
pip install matplotlib
pip install "numpy<2" --force-reinstall  # 确保NumPy版本兼容
```

### 3. 无权限访问进程
**现象**：提示“无权限访问PID=xxx的进程”  
**解决**：
- Windows：以管理员身份运行命令提示符/终端
- Linux/macOS：添加`sudo`运行，如 `sudo python mem_monitor.py --pid 1234`

### 4. 进程列表为空
**现象**：交互式启动时提示“未检测到运行的进程”  
**解决**：
- Windows：确保以管理员身份运行
- Linux/macOS：检查psutil权限，执行 `pip install --upgrade psutil` 升级psutil

### 5. 分析报告缺少指标
**现象**：报告中未显示物理内存/虚拟内存等指标  
**解决**：检查配置文件`[ANALYSIS]`部分或命令行参数，确保对应的`show_rss`/`show_vms`等配置为`True`（默认开启）


## 九、退出说明
1. 监控过程中按 `Ctrl+C` 可优雅终止程序；
2. 程序终止后会自动：
   - 保存最后一次采样数据到日志文件
   - 生成文本格式的分析报告（根据配置显示指定指标）
   - 生成内存趋势图（根据配置显示指定指标，需安装matplotlib）
3. 目标进程终止时，程序会自动停止监控并退出。