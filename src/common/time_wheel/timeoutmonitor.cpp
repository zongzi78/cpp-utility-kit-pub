#include "timeoutmonitor.h"

#include <Poco/Format.h>

#include <cmath>
#include <iostream>
#include <stdexcept>

#include "logutility.h"

namespace sched
{

CTaskTimeoutMonitor::CTaskTimeoutMonitor(size_t wheel_size, Milliseconds slot_interval, size_t num_wheels)
    : m_wheelSize(wheel_size)
    , m_slotInterval(slot_interval)
    , m_numWheels(num_wheels)
{
	if (m_wheelSize == 0 || m_numWheels == 0)
	{
		throw std::invalid_argument("时间轮大小和层数必须大于0");
	}

	initializeWheels();

	PRINT_RUN_LOG(Poco::format("超时监控器初始化: %?i层时间轮, %?i槽/层, %?i毫秒/槽", m_numWheels, m_wheelSize,
	                           m_slotInterval.count()));
}

CTaskTimeoutMonitor::~CTaskTimeoutMonitor()
{
	stop();
}

void CTaskTimeoutMonitor::start()
{
	if (m_running.exchange(true))
	{
		return;  // 已经在运行
	}

	m_currentSlots.assign(m_numWheels, 0);

	for (size_t i = 0; i < 4; ++i)
	{
		m_timeoutThreads.emplace_back([this]() { timeoutLoop(); });
	}

	m_workerThread = std::thread([this]() { workerLoop(); });

	PRINT_RUN_LOG("任务超时监控器已启动");
}

void CTaskTimeoutMonitor::stop()
{
	if (!m_running.exchange(false))
	{
		return;
	}

	m_cv.notify_all();
	if (m_workerThread.joinable())
	{
		m_workerThread.join();
	}

	m_queueCV.notify_all();
	for (std::thread& thread : m_timeoutThreads)
	{
		if (thread.joinable()) thread.join();
	}
	// 清空超时等待回调的任务队列
	{
		std::lock_guard<std::mutex> lock(m_queueMutex);
		std::queue<std::shared_ptr<TimeoutTask>>().swap(m_taskQueue);
	}

	// 清空所有任务
	{
		std::lock_guard<std::mutex> lock(m_registryMutex);
		m_taskRegistry.clear();
	}

	// 清空时间轮
	for (auto& wheel : m_wheels)
	{
		for (auto& slot : wheel)
		{
			std::lock_guard<std::mutex> lock(slot->mutex);
			slot->tasks.clear();
		}
	}

	PRINT_RUN_LOG("任务超时监控器已停止");
}

bool CTaskTimeoutMonitor::addTaskMonitor(const std::string& taskId, const std::string& nodeId, Milliseconds timeout,
                                         TimeoutCallback callback, std::string& errMsg)
{
	if (!m_running.load())
	{
		errMsg = "超时监控器未运行";
		return false;
	}

	if (timeout.count() <= 0)
	{
		errMsg = "超时时间必须大于0";
		return false;
	}

	// 检查是否超过最大超时范围
	Milliseconds maxRange = getMaxTimeoutRange();
	if (timeout > maxRange)
	{
		errMsg = "设定超时时间超过最大限制";
		return false;
	}

	// 计算超时时间，构建超时任务
	TimePoint                    expireTime = Clock::now() + timeout;
	std::shared_ptr<TimeoutTask> task       = std::make_shared<TimeoutTask>(taskId, nodeId, expireTime, callback);

	// 注册任务
	{
		std::lock_guard<std::mutex> lock(m_registryMutex);
		if (m_taskRegistry.count(taskId))
		{
			errMsg = "任务已存在监控中";
			return false;
		}
		m_taskRegistry[taskId] = task;
	}

	// 添加到时间轮
	if (!addToTimeWheel(task, errMsg))
	{
		std::lock_guard<std::mutex> lock(m_registryMutex);
		m_taskRegistry.erase(taskId);
		return false;
	}

	PRINT_DBG_LOG(
	    Poco::format("开始监控任务 %s 超时, 节点: %s, 超时时间: %?i秒", taskId, nodeId, timeout.count() / 1000));

	return true;
}

bool CTaskTimeoutMonitor::removeTaskMonitor(const std::string& taskId)
{
	std::shared_ptr<TimeoutTask> task;
	{
		std::lock_guard<std::mutex> lock(m_registryMutex);
		auto                        it = m_taskRegistry.find(taskId);
		if (it == m_taskRegistry.end())
		{
			return false;
		}
		task = it->second;
		m_taskRegistry.erase(it);
	}

	// 标记任务为取消状态
	if (task)
	{
		task->cancelled->store(true);
	}

	PRINT_RUN_LOG(Poco::format("移除任务 %s 的超时监控", taskId));
	return true;
}

size_t CTaskTimeoutMonitor::getMonitoredTaskCount() const
{
	std::lock_guard<std::mutex> lock(m_registryMutex);
	return m_taskRegistry.size();
}

void CTaskTimeoutMonitor::initializeWheels()
{
	m_wheels.resize(m_numWheels);
	for (size_t i = 0; i < m_numWheels; ++i)
	{
		m_wheels[i].reserve(m_wheelSize);
		for (size_t j = 0; j < m_wheelSize; ++j)
		{
			m_wheels[i].emplace_back(new TimeSlot);
		}
	}
}

void CTaskTimeoutMonitor::workerLoop()
{
	TimePoint nextCheck = Clock::now();

	while (m_running.load())
	{
		// 计算下一个检查时间
		nextCheck += m_slotInterval;

		// 等待到下一个时间槽
		{
			std::unique_lock<std::mutex> lock(m_cvMutex);
			if (m_cv.wait_until(lock, nextCheck, [this]() { return !m_running.load(); }))
			{
				break;  // 被停止信号唤醒
			}
		}

		if (!m_running.load()) break;

		// 推进时间轮
		advanceTimeWheel_r(0);

		// 处理当前槽的任务
		processCurrentSlot();
	}
}

void CTaskTimeoutMonitor::timeoutLoop()
{
	while (m_running.load())
	{
		std::shared_ptr<TimeoutTask> task;
		{
			std::unique_lock<std::mutex> lock(m_queueMutex);
			m_queueCV.wait(lock, [this]() { return !m_running.load() || !m_taskQueue.empty(); });

			if (!m_running.load())
			{
				break;
			}

			task = std::move(m_taskQueue.front());
			m_taskQueue.pop();
		}

		if (task && !task->cancelled->load() && task->callback)
		{
			try
			{
				task->callback(task->taskId);
			} catch (...)
			{
				PRINT_ERR_LOG(Poco::format("任务 %s 超时回调执行异常", task->taskId));
			}
		}
	}
}

void CTaskTimeoutMonitor::processCurrentSlot()
{
	TimePoint now = Clock::now();

	// 处理最内层（第0层）当前槽
	size_t                                    currentSlot = m_currentSlots[0];
	std::vector<std::shared_ptr<TimeoutTask>> currentTasks;

	std::string log = "槽指针:";
	for (size_t p : m_currentSlots)
	{
		log += " " + std::to_string(p);
	}
	// PRINT_DBG_LOG(log);

	// 取出当前槽的所有任务
	{
		std::lock_guard<std::mutex> lock(m_wheels[0][currentSlot]->mutex);
		currentTasks = std::move(m_wheels[0][currentSlot]->tasks);
		m_wheels[0][currentSlot]->tasks.clear();
	}

	// 处理任务
	for (auto& task : currentTasks)
	{
		// 检查是否被取消
		if (task->cancelled->load())
		{
			continue;
		}

		// 检查是否真正超时
		if (now >= task->expireTime)
		{
			PRINT_ERR_LOG(Poco::format("任务 %s 计算超时, 节点: %s", task->taskId, task->nodeId));
			std::shared_ptr<TimeoutTask> taskTemp = task;
			// // 执行超时回调
			// try
			// {
			// 	task->callback(task->taskId);
			// } catch (const std::exception& e)
			// {
			// 	PRINT_ERR_LOG(Poco::format("任务 %s 超时回调执行异常: %s", task->taskId, e.what()));
			// }

			// 从注册表中移除
			{
				std::lock_guard<std::mutex> lock(m_registryMutex);
				m_taskRegistry.erase(task->taskId);
			}

			// 提交到线程池，执行回调
			{
				std::lock_guard<std::mutex> lock(m_queueMutex);
				m_taskQueue.push(taskTemp);
			}
			m_queueCV.notify_one();
		}
		else
		{
			// 重新添加到时间轮
			std::string errMsg;
			if (!addToTimeWheel(task, errMsg))
			{
				PRINT_ERR_LOG(Poco::format("重新添加任务 %s 到时间轮失败: %s", task->taskId, errMsg));

				// 如果重新添加失败，强制触发超时
				try
				{
					task->callback(task->taskId);
				} catch (const std::exception& e)
				{
					PRINT_ERR_LOG(Poco::format("任务 %s 强制超时回调执行异常: %s", task->taskId, e.what()));
				}

				std::lock_guard<std::mutex> lock(m_registryMutex);
				m_taskRegistry.erase(task->taskId);
			}
		}
	}
}

void CTaskTimeoutMonitor::advanceTimeWheel_r(int wheel)
{
	// 超出层数范围，结束递归
	if (wheel >= m_numWheels)
	{
		return;
	}
	// 推进当前层
	m_currentSlots[wheel] = (m_currentSlots[wheel] + 1) % m_wheelSize;

	// 如果不是第0层，则重新分配当前层的当前槽中的任务
	if (wheel != 0)
	{
		// PRINT_DBG_LOG(Poco::format("第 %?i 层回绕", wheel - 1));

		size_t curr_wheel   = wheel;
		size_t current_slot = (m_currentSlots[curr_wheel]) % m_wheelSize;

		std::vector<std::shared_ptr<TimeoutTask>> cascade_tasks;

		// 取出当前槽中的任务
		{
			std::lock_guard<std::mutex> lock(m_wheels[curr_wheel][current_slot]->mutex);
			cascade_tasks = std::move(m_wheels[curr_wheel][current_slot]->tasks);
			m_wheels[curr_wheel][current_slot]->tasks.clear();
		}

		// 重新分配
		for (auto& task : cascade_tasks)
		{
			if (!task->cancelled->load())
			{
				std::string temp;
				addToTimeWheel(task, temp);
			}
		}
	}

	// 如果当前层没有回绕，停止推进更高层，结束递归
	if (m_currentSlots[wheel] != 0)
	{
		return;
	}
	// 如果当前层回绕，继续推近更高层
	advanceTimeWheel_r(wheel + 1);
}

std::pair<size_t, size_t> CTaskTimeoutMonitor::calculateWheelPosition(TimePoint expireTime) const
{
	TimePoint now = Clock::now();
	if (expireTime <= now)
	{
		return {0, m_currentSlots[0] + 1};  // 立即过期，放到第0层下一个槽中以尽快处理
	}

	// 计算距离过期还有多少时间
	auto    duration    = std::chrono::duration_cast<Milliseconds>(expireTime - now);
	int64_t remainingMs = duration.count();

	// 未过期，但剩余时间已经不足1ms，超出最大处理极限，视为立即过期
	if (remainingMs == 0)
	{
		return{ 0, m_currentSlots[0] + 1 };  // 放到第0层下一个槽中以尽快处理
	}

	// 计算剩余时间对应的槽数，不满足一个槽的部分向上取整
	int64_t remainingSlots = std::ceil((double)remainingMs / m_slotInterval.count());

    // test1

    // test2

	// 从指定的起始层级开始寻找合适的层级
	for (size_t wheel = 0; wheel < m_numWheels; ++wheel)
	{
		int64_t wheelRange = static_cast<int64_t>(std::pow(m_wheelSize, wheel + 1));

		if (remainingSlots <= wheelRange)
		{
			// 计算在当前层的具体槽位
			int64_t base       = static_cast<int64_t>(std::pow(m_wheelSize, wheel));
			int64_t slotOffset = remainingSlots / base;
			size_t  slotIndex  = (m_currentSlots[wheel] + slotOffset) % m_wheelSize;

			return {wheel, slotIndex};
		}
	}

	// 如果所有层级都不合适，放到最外层的最后一个槽
	return {m_numWheels - 1, m_wheelSize - 1};
}

bool CTaskTimeoutMonitor::addToTimeWheel(std::shared_ptr<TimeoutTask> task, std::string& errMsg)
{
	if (task->cancelled->load())
	{
		errMsg = "添加任务到时间轮失败，已被标记为取消";
		return false;
	}

	std::pair<size_t, size_t> kv    = calculateWheelPosition(task->expireTime);
	size_t                    wheel = kv.first;
	size_t                    slot  = kv.second;

	if (wheel >= m_numWheels || slot >= m_wheelSize)
	{
		errMsg = "添加任务到时间轮失败，超出最大时间限制";
		return false;
	}

	std::string log = "当前槽指针为:";
	for (size_t p : m_currentSlots)
	{
		log += " " + std::to_string(p);
	}
	// PRINT_DBG_LOG(log);
	// PRINT_DBG_LOG(Poco::format("任务将添加到 %?i 层, %?i 槽", wheel, slot));

	addToSlot(wheel, slot, task);
	return true;
}

bool CTaskTimeoutMonitor::addToSlot(size_t wheel, size_t slot, std::shared_ptr<TimeoutTask> task)
{
	if (wheel >= m_wheels.size() || slot >= m_wheels[wheel].size())
	{
		return false;
	}

	{
		std::lock_guard<std::mutex> lock(m_wheels[wheel][slot]->mutex);
		m_wheels[wheel][slot]->tasks.push_back(task);
	}

	return true;
}

CTaskTimeoutMonitor::Milliseconds CTaskTimeoutMonitor::getMaxTimeoutRange() const
{
	int64_t maxSlots = static_cast<int64_t>(std::pow(m_wheelSize, m_numWheels));
	return m_slotInterval * maxSlots;
}

}  // namespace sched
