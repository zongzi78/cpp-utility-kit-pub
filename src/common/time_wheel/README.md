## 概述

### 功能描述

基于分层时间轮算法的高性能任务超时监控器，用于在分布式系统中精确检测和管理任务的执行超时。它通过多级时间轮结构实现对大量任务的高效调度和超时回调触发。

### 功能特性
- **分层时间轮设计**：支持多层时间轮（默认3层），扩大超时检测范围
- **精确时间控制**：支持毫秒级超时精度
- **线程安全**：内置多级锁机制，支持多线程环境
- **异步回调**：独立的回调线程池，避免阻塞时间轮推进
- **动态任务管理**：支持运行时添加/移除监控任务
- **优雅关闭**：完整的资源清理和线程安全退出机制

### 适用场景
- 分布式任务调度系统的超时控制
- 网络请求超时管理
- 异步任务执行状态监控
- 需要精确时间控制的定时任务管理

## 接口说明

### 核心接口
```cpp
// 构造时间轮监控器
CTaskTimeoutMonitor(size_t wheel_size = 60, 
                   Milliseconds slot_interval = std::chrono::seconds(1),
                   size_t num_wheels = 3)

// 启动/停止监控器
void start();
void stop();

// 任务管理
bool addTaskMonitor(const std::string& taskId, const std::string& nodeId, 
                   Milliseconds timeout, TimeoutCallback callback, std::string& errMsg);
bool removeTaskMonitor(const std::string& taskId);
size_t getMonitoredTaskCount() const;
```

### 配置参数
- `wheel_size`：每层时间轮的槽数量（默认60）
- `slot_interval`：每个槽的时间间隔（默认1秒）
- `num_wheels`：时间轮层数（默认3层）

## 示例

```cpp
// 创建超时监控器（60槽/层，1秒/槽，3层）
auto monitor = std::make_unique<sched::CTaskTimeoutMonitor>();

// 启动监控器
monitor->start();

// 添加任务监控
std::string errMsg;
bool success = monitor->addTaskMonitor("task_001", "node_01", 
                                      std::chrono::seconds(30),
                                      [](const std::string& taskId) {
                                          std::cout << "Task " << taskId << " timeout!" << std::endl;
                                      }, errMsg);

// 移除任务监控
monitor->removeTaskMonitor("task_001");

// 停止监控器
monitor->stop();
```

## 版本历史
- 2025-09-30: 初始版本实现完整的时间轮超时监控功能

## TODO
- [ ] 添加性能监控指标（吞吐量、延迟统计）
- [ ] 支持动态调整时间轮参数
- [ ] 添加持久化支持，防止服务重启丢失监控任务
- [ ] 实现任务超时的重试机制
- [ ] 添加更丰富的回调上下文信息