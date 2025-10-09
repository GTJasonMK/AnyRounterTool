# AnyRouter 余额监控器

[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)]()

快速查询 AnyRouter 账户余额的悬浮窗工具，支持多账户并行查询。

## ✨ 核心特性

- 🚀 **极速并行查询** - 8个账户仅需40秒，平均每账户5秒
- 🎯 **智能自动化** - 自动登录、关闭公告弹窗、提取余额
- 💎 **悬浮窗界面** - 可收缩/展开、置顶显示、拖拽移动
- ⚡ **高性能优化** - 浏览器实例池化、CPU核心数自适应、智能DOM提取
- 🔄 **智能资源管理** - 自动清理临时文件、防止内存泄漏
- 📊 **总余额统计** - 自动汇总所有账户余额

## 🎬 界面预览

**收缩状态**：小圆圈悬浮在屏幕边缘
**展开状态**：鼠标悬停自动展开，显示账户余额列表

## 📦 安装

### 环境要求

- Python 3.8+
- Chrome 浏览器（自动下载匹配的 ChromeDriver）

### 安装依赖

```bash
pip install -r requirements.txt
```

核心依赖：
- `PyQt6` - GUI框架
- `selenium` - 浏览器自动化
- `psutil` - 系统信息检测
- `requests` - ChromeDriver自动下载

## ⚙️ 配置

### 1. 配置账号信息

复制示例文件并编辑：
```bash
cp credentials.txt.example credentials.txt
```

编辑 `credentials.txt`，添加你的账号信息（每行一个账号）：
```
用户名,密码,API_KEY(可选)
user1@example.com,password123,sk-ant-xxxxxxxxxxxx
user2@example.com,password456,sk-ant-yyyyyyyyyyyy
```

**注意**：`credentials.txt` 包含敏感信息，已自动加入 `.gitignore`，不会被提交到 Git。

### 2. 配置程序参数（可选）

首次运行会自动生成 `config.json`，可手动编辑调整参数：

```json
{
  "browser": {
    "headless": true,           // 无头模式（后台运行）
    "timeout": 20,              // 页面加载超时（秒）
    "disable_images": true      // 禁用图片加载（提升性能）
  },
  "performance": {
    "max_workers": 9,           // 最大并发线程数
    "auto_detect_workers": false, // 自动检测CPU核心数
    "retry_times": 2            // 失败重试次数
  },
  "ui": {
    "stay_on_top": true,        // 窗口置顶
    "collapse_delay": 600       // 自动收缩延迟（毫秒）
  }
}
```

## 🚀 使用方法

### 基本用法

```bash
# 标准模式 - 后台查询，显示悬浮窗
python main.py

# 无头模式 - 强制使用headless浏览器
python main.py --headless

# 调试模式 - 显示详细日志
python main.py --debug

# 指定配置目录
python main.py --config /path/to/config
```

### 悬浮窗操作

- **展开/收缩**：鼠标悬停自动展开，移开自动收缩
- **拖拽移动**：鼠标左键拖拽小圆圈或展开窗口
- **查询余额**：点击"查询"按钮
- **复制API Key**：右键点击账户，选择"复制 API Key"
- **设置Claude配置**：右键点击账户，选择"设为Claude配置Token"
- **强制退出**：点击"退出"按钮或按 `Ctrl+Q`

## 📁 项目结构

```
LogInAngRounter/
├── main.py                      # 程序入口
├── credentials.txt              # 账号配置（需手动创建，不提交到Git）
├── credentials.txt.example      # 账号配置示例
├── config.json                  # 自动生成的配置（不提交到Git）
├── config.json.example          # 配置示例
├── requirements.txt             # Python依赖
├── CLAUDE.md                    # Claude Code 项目文档
├── README.md                    # 本文件
├── LICENSE                      # MIT许可证
└── src/
    ├── config_manager.py        # 配置管理
    ├── browser_manager.py       # 浏览器控制
    ├── browser_pool.py          # 浏览器实例池化（性能优化核心）
    ├── driver_manager.py        # ChromeDriver自动管理
    ├── auth_manager.py          # 登录和余额提取
    ├── monitor_service.py       # 监控服务核心
    ├── performance_monitor.py   # 性能监控
    └── ui_floating.py           # 悬浮窗界面
```

## ⚡ 性能数据

### 查询速度
- **单账号查询**：约 25 秒（包含登录、弹窗处理、余额提取）
- **8账号并行查询**：约 40 秒（平均每账号 5 秒）
- **性能提升**：相比串行查询提升 **80%+**

### 优化技术
1. **浏览器实例池化**：预创建浏览器实例，避免重复启动开销（节省 60%+ 时间）
2. **并行查询**：使用 ThreadPoolExecutor 实现真正的并发（8核心可同时处理8个账号）
3. **智能DOM提取**：5层策略提取余额，避免全DOM遍历
4. **ChromeDriver自动管理**：自动下载匹配版本，支持多源降级
5. **资源智能清理**：自动清理临时文件和僵尸进程，防止内存泄漏

### 资源占用
- **CPU使用率**：根据核心数自适应调节（建议最多9个并发）
- **内存占用**：每个浏览器实例约 50-80MB，4实例池约 200-320MB
- **磁盘占用**：临时目录自动清理，无持续增长

## 🔧 故障排除

### ChromeDriver 版本问题
**问题**：`SessionNotCreatedException: This version of ChromeDriver only supports Chrome version XXX`

**解决方案**：
1. 删除项目中的 `chromedriver.exe`
2. 程序会自动检测Chrome版本并下载匹配的ChromeDriver
3. 如果自动下载失败，手动从 [Chrome for Testing](https://googlechromelabs.github.io/chrome-for-testing/) 下载

### 登录失败
**常见原因**：
- 账号密码错误（检查 `credentials.txt` 格式）
- 公告弹窗未正确关闭（查看日志文件）
- 网络连接问题（检查能否访问目标网站）

**解决方案**：
```bash
# 使用调试模式查看详细日志
python main.py --debug
```

### 余额提取失败
**常见原因**：
- 页面加载时间不足（调整 `config.json` 中的 `timeout`）
- 目标网站DOM结构变化（需要更新提取策略）

**解决方案**：
1. 增加超时时间：编辑 `config.json`，设置 `"timeout": 30`
2. 查看 `anyrouter_monitor.log` 获取详细错误信息

### 程序无法退出
**解决方案**：
- 点击界面上的"退出"按钮（强制杀死所有Chrome进程）
- 按 `Ctrl+Q` 快捷键
- 如果仍然无法退出，手动杀死进程：
  ```bash
  # Windows
  taskkill /F /IM chrome.exe /T
  taskkill /F /IM python.exe /T

  # Linux/macOS
  killall chrome
  killall python
  ```

## 🛠️ 开发指南

### 模块测试

每个核心模块都支持独立运行测试：

```bash
# 测试浏览器管理器
python src/browser_manager.py

# 测试认证管理器（需要在代码中修改测试账号）
python src/auth_manager.py

# 测试监控服务（执行完整查询流程）
python src/monitor_service.py
```

### 代码架构

项目采用分层架构设计：
- **表现层**：`ui_floating.py` - PyQt6 界面
- **业务层**：`monitor_service.py` - 监控服务核心逻辑
- **服务层**：`auth_manager.py` - 认证和余额提取
- **基础层**：`browser_manager.py`, `browser_pool.py` 等 - 浏览器和资源管理

### 设计模式

- **对象池模式**：`BrowserPool` - 复用浏览器实例
- **上下文管理器**：自动管理资源生命周期
- **线程池并发**：`ThreadPoolExecutor` - 多账户并行查询
- **回调机制**：监控服务通过回调函数通知UI更新
- **单例模式**：全局浏览器池、性能监控器

## 🔐 安全提醒

1. **敏感信息保护**：
   - `credentials.txt` 和 `config.json` 已加入 `.gitignore`
   - 请勿将包含真实账号信息的配置文件提交到公共仓库

2. **API Key 管理**：
   - API Key 存储在本地配置文件中
   - 右键菜单可以快速复制和设置Claude配置Token

3. **ChromeDriver 安全**：
   - 程序使用官方 Chrome for Testing 下载源
   - 支持多源降级确保下载安全可靠

## 📝 更新日志

### v2.1 (2025-01) - 性能优化版
- ✨ 新增浏览器实例池化，性能提升50%+
- ✨ 新增ChromeDriver自动版本管理
- ✨ 新增总余额统计功能
- ✨ 新增性能监控模块
- 🐛 修复内存泄漏问题（临时目录清理）
- 🐛 修复程序退出时Chrome进程残留
- ⚡ 优化并行浏览器创建（4x启动速度）
- ⚡ 优化DOM提取策略（5层智能查找）

### v2.0 (2024-12) - 悬浮窗版
- ✨ 重构为悬浮窗界面
- ✨ 支持多账户并行查询
- ✨ 添加Claude配置Token管理

### v1.0 (2024-11) - 初始版本
- ✨ 基础功能实现

## 📄 许可证

本项目采用 MIT 许可证，详见 [LICENSE](LICENSE) 文件。

## 🙏 致谢

- [Selenium](https://www.selenium.dev/) - 浏览器自动化框架
- [PyQt6](https://www.riverbankcomputing.com/software/pyqt/) - Python GUI框架
- [Chrome for Testing](https://googlechromelabs.github.io/chrome-for-testing/) - ChromeDriver下载源

## 📮 反馈与贡献

- 🐛 发现Bug？请提交 [Issue](../../issues)
- 💡 有新想法？欢迎提交 [Pull Request](../../pulls)
- ⭐ 觉得有用？给个 Star 吧！

---

**注意**：本工具仅供学习交流使用，请遵守相关网站的使用条款。
