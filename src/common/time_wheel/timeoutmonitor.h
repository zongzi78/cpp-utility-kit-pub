/**
 * @file timeoutmonitor.h
 * @author YuXinshan (yuxinshan@ieslab.cn)
 * @brief 任务超时监控器，基于时间轮算法实现任务的超时检测
 * @date 2025-09-30 14:09
 */

#ifndef TIMEOUTMONITOR_H
#define TIMEOUTMONITOR_H

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <functional>
#include <memory>
#include <mutex>
#include <queue>
#include <thread>
#include <unordered_map>
#include <vector>

namespace sched
{

/**
 * @brief 任务超时监控器，使用时间轮算法高效管理大量任务的超时检测
 */
class CTaskTimeoutMonitor
{
public:
	using Clock        = std::chrono::steady_clock;
	using TimePoint    = Clock::time_point;
	using Milliseconds = std::chrono::milliseconds;

	// 超时回调函数类型
	using TimeoutCallback = std::function<void(const std::string& taskId)>;

	/**
	 * @brief 超时任务项
	 */
	struct TimeoutTask
	{
		std::string                        taskId;
		std::string                        nodeId;
		TimePoint                          expireTime;
		TimeoutCallback                    callback;
		std::shared_ptr<std::atomic<bool>> cancelled;

		TimeoutTask(const std::string& id, const std::string& nid, TimePoint expire, TimeoutCallback cb)
		    : taskId(id)
		    , nodeId(nid)
		    , expireTime(expire)
		    , callback(cb)
		    , cancelled(std::make_shared<std::atomic<bool>>(false))
		{
		}
	};

	/**
	 * @brief 时间轮槽
	 */
	struct TimeSlot
	{
		std::vector<std::shared_ptr<TimeoutTask>> tasks;
		std::mutex                                mutex;  // 不可复制
	};

public:
	CTaskTimeoutMonitor(size_t       wheel_size    = 60,                       // 时间轮槽数
	                    Milliseconds slot_interval = std::chrono::seconds(1),  // 每个槽的时间间隔
	                    size_t       num_wheels    = 3                         // 时间轮层数
	);

	~CTaskTimeoutMonitor();

	// 禁用拷贝
	CTaskTimeoutMonitor(const CTaskTimeoutMonitor&)            = delete;
	CTaskTimeoutMonitor& operator=(const CTaskTimeoutMonitor&) = delete;

	/**
	 * @brief 启动超时监控器
	 */
	void start();

	/**
	 * @brief 停止超时监控器
	 */
	void stop();

	/**
	 * @brief 添加任务超时监控
	 * @param taskId 任务ID
	 * @param nodeId 节点ID
	 * @param timeout 超时时间
	 * @param callback 超时回调函数
	 * @return 是否添加成功
	 */
	bool addTaskMonitor(const std::string& taskId, const std::string& nodeId, Milliseconds timeout,
	                    TimeoutCallback callback, std::string& errMsg);

	/**
	 * @brief 移除任务超时监控
	 * @param taskId 任务ID
	 * @return 是否移除成功
	 */
	bool removeTaskMonitor(const std::string& taskId);

	/**
	 * @brief 获取监控中的任务数量
	 */
	size_t getMonitoredTaskCount() const;

	/**
	 * @brief 检查是否正在运行
	 */
	bool isRunning() const
	{
		return m_running.load();
	}

private:
	/**
	 * @brief 初始化时间轮
	 */
	void initializeWheels();

	/**
	 * @brief 工作线程主循环
	 */
	void workerLoop();

	/**
	* @brief 超时回调线程主循环
	*/
	void timeoutLoop();

	/**
	 * @brief 处理当前槽的任务
	 */
	void processCurrentSlot();

	/**
	 * @brief 推进时间轮
	 */
	void advanceTimeWheel_r(int wheel);

	/**
	 * @brief 将任务添加到时间轮
	 */
	bool addToTimeWheel(std::shared_ptr<TimeoutTask> task, std::string& errMsg);

	/**
	 * @brief 添加到指定槽
	 */
	bool addToSlot(size_t wheel, size_t slot, std::shared_ptr<TimeoutTask> task);

	/**
	 * @brief 计算任务在时间轮中的位置
	 */
	std::pair<size_t, size_t> calculateWheelPosition(TimePoint expireTime) const;

	/**
	 * @brief 获取时间轮的最大时间范围
	 */
	Milliseconds getMaxTimeoutRange() const;

private:
	// 时间轮配置
	const size_t       m_wheelSize;     // 层大小(槽数)
	const Milliseconds m_slotInterval;  // 槽大小(槽间隔)
	const size_t       m_numWheels;     // 层数

	// 时间轮状态
	std::vector<std::vector<std::unique_ptr<TimeSlot>>> m_wheels;        // mutex不可拷贝，使用unique_ptr
	std::vector<size_t>                                 m_currentSlots;  // 层指针
	// TimePoint                                           m_startTime;

	// 任务注册表
	std::unordered_map<std::string, std::shared_ptr<TimeoutTask>> m_taskRegistry;
	mutable std::mutex                                            m_registryMutex;

	// 工作线程
	std::thread             m_workerThread;
	std::atomic<bool>       m_running{false};
	std::condition_variable m_cv;
	std::mutex              m_cvMutex;

	// 超时回调线程池
	std::vector<std::thread>                 m_timeoutThreads;
	std::queue<std::shared_ptr<TimeoutTask>> m_taskQueue;
	std::mutex                               m_queueMutex;
	std::condition_variable                  m_queueCV;
};

}  // namespace sched

#endif  // TIMEOUTMONITOR_H