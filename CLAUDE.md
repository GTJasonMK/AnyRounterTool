# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

AnyRouter余额监控器 - 基于 PyQt6 和 Selenium 的自动化账户余额查询工具，支持多账户并行查询和悬浮窗界面。

**性能优化版本 v2.1** - 引入浏览器实例池化、智能DOM提取、自动ChromeDriver管理等多项优化，性能提升50%以上。

## 核心架构

### 分层架构设计
- **表现层**: `src/ui_floating.py` - PyQt6 悬浮窗界面，支持展开/收缩动画
- **业务层**: `src/monitor_service.py` - 监控服务核心逻辑，处理并发查询
- **服务层**: `src/auth_manager.py` - 认证和余额提取逻辑
- **基础层**:
  - `src/browser_manager.py` - Selenium 浏览器封装
  - `src/browser_pool.py` - 浏览器实例池化管理
  - `src/config_manager.py` - 配置管理
  - `src/driver_manager.py` - ChromeDriver自动版本管理
  - `src/performance_monitor.py` - 性能监控和指标收集

### 关键设计模式
- **对象池模式**: `BrowserPool` - 复用浏览器实例，避免重复创建开销
- **上下文管理器**: `BrowserManager.create_driver()`, `BrowserPool.get_browser()` - 自动管理资源生命周期
- **线程池并发**: `ThreadPoolExecutor` - 实现多账户并行查询
- **回调机制**: 监控服务通过回调函数通知 UI 更新状态
- **单例模式**: 全局浏览器池、性能监控器
- **配置分离**: JSON 配置文件 + 账号凭证文件分离管理

## 开发命令

### 基础运行
```bash
# 标准模式 - 显示悬浮窗
python main.py

# 无头模式 - 后台运行，强制使用 headless 浏览器
python main.py --headless

# 调试模式 - 详细日志输出
python main.py --debug

# 指定配置目录
python main.py --config /path/to/config
```

### 模块测试
每个核心模块都支持独立运行测试:
```bash
# 测试浏览器管理器 - 打开百度并截图
python src/browser_manager.py

# 测试认证管理器 - 需要在代码中修改测试账号信息
python src/auth_manager.py

# 测试监控服务 - 执行完整的余额查询流程
python src/monitor_service.py
```

### 调试技巧
```bash
# 可视化调试 - 显示浏览器窗口(修改配置后运行)
# 1. 编辑 config.json，设置 "browser.headless": false
# 2. 运行: python main.py --debug

# 单账号调试 - 临时修改 credentials.txt，只保留一个账号进行测试

# 查看实时日志
tail -f anyrouter_monitor.log  # Linux/macOS
Get-Content anyrouter_monitor.log -Wait  # Windows PowerShell
```

### 依赖管理
```bash
# 安装依赖
pip install -r requirements.txt

# 核心依赖包括:
# PyQt6>=6.4.0 - GUI框架
# selenium>=4.0.0 - 浏览器自动化
# psutil>=5.9.0 - 系统信息检测(可选)
```

### 配置文件结构
- `config.json` - 应用程序配置(自动生成，可手动编辑)
- `credentials.txt` - 账号凭证: `用户名,密码,API_KEY`
- `anyrouter_monitor.log` - 日志文件
- `chromedriver.exe` - Chrome驱动程序(Windows，需与Chrome版本匹配)

## 核心模块详解

### 监控服务 (`monitor_service.py`)
- **并发策略**: 默认使用 CPU 核心数作为最大工作线程(最多9个)
- **性能优化**: 强制使用 headless 模式进行并行查询(在 `src/monitor_service.py:52` 强制设置)
- **错误处理**: 智能重试机制，支持配置重试次数和延迟
- **状态管理**: 线程安全的账号状态追踪(`status_lock` 保护状态更新)
- **回调函数**: 通过三个回调函数与UI层通信:
  - `on_balance_update(username, balance, success)` - 余额更新时调用
  - `on_status_change(username, status)` - 状态变更时调用
  - `on_error(username, error_msg)` - 发生错误时调用

### 认证管理 (`auth_manager.py`)
- **弹窗处理**: 自动检测并关闭公告弹窗(使用JavaScript快速查找并点击关闭按钮)
- **余额提取**: 高性能余额提取算法，5层DOM查找策略 + 备用方案(在 `BalanceExtractor.extract_balance()` 中实现)
  - 优先使用特定选择器(`.balance-amount`等)避免全局遍历
  - XPath定位包含"余额"文本的元素
  - 限定容器范围搜索，避免全DOM查找
  - 正则表达式文本匹配作为最后手段
- **登录流程**: 优化的登录流程，自动切换到邮箱登录模式
- **性能优化**: 减少了不必要的等待时间，从原版的多处3秒等待优化到0.5-1.5秒

### 浏览器池管理 (`browser_pool.py`)
- **实例复用**: 预创建3个浏览器实例，最大支持9个，避免重复启动开销
- **状态管理**: 自动清理cookies、localStorage、sessionStorage，确保实例可复用
- **智能分配**: 线程安全的实例获取和归还机制
- **性能统计**: 实时追踪实例复用率、等待时间等指标
- **资源监控**: 自动检测实例健康状态，失效实例自动重建

### ChromeDriver管理 (`driver_manager.py`)
- **自动检测**: 自动检测本地Chrome浏览器版本(支持Windows/macOS/Linux)
- **智能下载**: 根据Chrome版本自动下载匹配的ChromeDriver
- **多源支持**: 支持Chrome for Testing、Google官方源、NPM镜像等多个下载源
- **版本缓存**: 已下载的驱动缓存在本地，避免重复下载
- **降级策略**: API失败时自动切换到备用下载源

### 性能监控 (`performance_monitor.py`)
- **指标收集**: 自动记录每个操作的耗时、成功率、错误信息
- **系统监控**: 实时监控CPU、内存使用、Chrome进程数量
- **统计分析**: 计算平均耗时、最小/最大耗时、成功率等统计指标
- **性能报告**: 生成详细的性能分析报告
- **装饰器支持**: 提供`@monitor_operation`装饰器快速添加监控

### 浏览器管理 (`browser_manager.py`)
- **跨平台支持**: 自动检测 Windows/macOS/Linux 的 Chrome 安装路径
- **性能优化**: 禁用图片加载、扩展等非必要功能
- **反检测**: 注入 JavaScript 隐藏自动化特征
- **资源管理**: 临时目录管理，避免浏览器配置冲突

### 悬浮窗界面 (`ui_floating.py`)
- **仿冒设计**: 完全仿照原版 UI 的外观和交互
- **动画效果**: 平滑的展开/收缩动画，悬停延迟收缩
- **置顶显示**: 始终保持在其他窗口之上
- **拖拽支持**: 支持鼠标拖拽移动窗口位置

## 配置系统

### 配置优先级
配置加载顺序(后者覆盖前者):
1. 代码中的 `DEFAULT_CONFIG` (最低优先级)
2. `config.json` 文件中的配置
3. 环境变量 `ANYROUTER_HEADLESS=1` (强制无头模式)
4. 命令行参数 `--headless`, `--debug`, `--config` (最高优先级)

## 性能基准

- **单账号查询**: ~25秒(包含登录、弹窗处理、余额提取)
- **8账号并行**: ~40秒(平均每账号5秒)
- **CPU使用率**: 线程池自动调节，建议不超过9个并发
- **内存占用**: 每个浏览器实例约50-80MB

## 故障排除

### ChromeDriver 问题
- 确保 ChromeDriver 版本与 Chrome 浏览器版本匹配
- ChromeDriver 需放置在项目根目录或系统 PATH 中
- 常见错误: "This version of ChromeDriver only supports Chrome version"

### 登录失败
- 检查 `credentials.txt` 格式: `用户名,密码,API_KEY`
- 确认账号密码正确，支持邮箱登录
- 公告弹窗处理失败可能影响登录流程

### 余额提取失败
- 页面加载时间不足，可调整 `wait_time` 参数
- DOM 结构变化可能导致提取策略失效
- 查看日志文件获取详细错误信息

## UI 主题和样式规范

### 颜色体系（深色主题）
- **背景渐变**: `rgba(20, 20, 30, 230)` → `rgba(30, 30, 45, 230)`
- **主按钮（紫色）**: `#5555ff` → `#8855ff`
- **退出按钮（红色）**: `#ff5555` → `#ff8855`
- **成功状态**: `#4caf50`（绿色）
- **失败状态**: `#f44336`（红色）
- **总余额显示**: `#90d090` / `#90ff90`
- **边框高亮**: `rgba(100, 100, 255, 0.2)` → `rgba(150, 150, 255, 0.4)`

### 尺寸规范
- **收缩状态**: 50×50 小圆圈
- **展开状态**: 320×200
- **圆角**: 大容器 `20px`，按钮 `12px`，小控件 `6px`
- **表格行高**: 固定 18px，最多显示3行

### 账号状态标记
- `●` 表示当前 Claude 配置 Token
- `◎` 表示当前 OpenAI 配置 Key

### 键盘快捷键
| 快捷键 | 功能 |
|--------|------|
| `Ctrl+Q` | 退出程序 |
| `F5` | 刷新查询 |
| `Esc` | 收缩窗口 |
| `Ctrl+L` | 切换进度日志 |
| `Ctrl+Shift+C` | 复制总余额 |

### 交互时间参数
- **悬停延迟收缩**: 600ms（`ui_floating.py:1823`）
- **查询完成后自动收缩**: 2000ms（`ui_floating.py:1645`）

## 开发注意事项

1. **敏感信息**: `credentials.txt` 包含账号密码，请勿提交到版本控制(建议添加到 `.gitignore`)
2. **线程安全**: 监控服务的状态更新使用 `status_lock` 保护，修改状态相关代码时必须使用锁
3. **资源清理**: 浏览器实例使用上下文管理器(`with` 语句)确保正确释放，临时目录会在 `finally` 块中自动清理
4. **跨平台**: Chrome 路径检测在 `browser_manager.py:101-138` 实现，新增平台需要添加对应路径
5. **ChromeDriver 版本**: 必须与本地 Chrome 浏览器版本匹配，版本不匹配会导致 `SessionNotCreatedException`
6. **并发限制**: 线程池最多使用9个工作线程，过多并发会导致系统资源耗尽
7. **余额提取稳定性**: 如果目标网站DOM结构变化，需要修改 `auth_manager.py:272-391` 中的JavaScript提取逻辑
8. **回调函数**: 自定义UI时必须正确设置监控服务的三个回调函数，否则无法接收状态更新
9. **强制 headless 模式**: 监控服务在 `monitor_service.py:54` 强制设置 `headless=True`，如需调试需临时注释
10. **浏览器池配置**: 初始池大小4个，最大9个（`browser_pool.py:355-358`）