# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

AnyRouter余额监控器 - 基于 PyQt6 和 Selenium 的自动化多账户余额查询工具，悬浮窗界面。性能优化版本 v2.1。

## 开发命令

```bash
pip install -r requirements.txt        # 安装依赖 (PyQt6, selenium, psutil, requests)
python main.py                          # 标准模式 - 悬浮窗
python main.py --headless               # 强制无头浏览器
python main.py --debug                  # 调试模式 - 详细日志
python main.py --config /path/to/dir    # 指定配置目录

# 模块独立测试（各模块支持 `if __name__ == "__main__"` 直接运行）
python src/browser_manager.py           # 打开浏览器并截图
python src/auth_manager.py              # 测试登录流程（需在代码中改测试账号）
python src/monitor_service.py           # 完整余额查询流程

python cleanup_chrome.py                # 紧急清理残留Chrome进程
```

**注意**：项目无 pytest/unittest 测试套件，依赖模块独立运行进行冒烟测试。

## 核心架构

```
main.py (入口: CLI参数解析 → QApplication → FloatingMonitor)
    │
    FloatingMonitor (ui_floating.py - PyQt6悬浮窗)
    │   ├── MonitorWorker (QThread，后台执行查询)
    │   └── 右键菜单：复制API Key / 设置Claude Token / 设置OpenAI Key
    │
    BalanceMonitorService (monitor_service.py - 并发调度)
    │   ├── 两阶段查询策略：
    │   │   1. ApiBalanceClient 快速API查询 (~1-2s)
    │   │   2. AuthManager Web登录回退 (~25s)
    │   ├── ThreadPoolExecutor 并行 (max_workers ≤ 9)
    │   ├── 缓存: balance_cache.json + daily_web_login_state.json
    │   └── 回调通知UI: on_balance_update / on_progress / on_status_change
    │
    ApiBalanceClient (api_balance_client.py)
    │   └── 尝试多个API端点: /v1/dashboard/billing/subscription → usage → credit_grants → /api/user/* → /v1/models
    │
    AuthManager + BalanceExtractor (auth_manager.py - 最大模块 78KB)
    │   ├── 登录: 导航 → 关闭公告弹窗(JS) → 邮箱登录 → 提交
    │   └── 余额提取: 5层DOM策略 (特定选择器 → XPath → 容器搜索 → 正则 → 全文本)
    │
    BrowserPool (browser_pool.py - 对象池)
    │   ├── 初始3-4实例，最大9个，线程安全获取/归还
    │   └── 自动清理cookies/localStorage/sessionStorage
    │
    BrowserManager (browser_manager.py - Selenium封装)
    │   ├── 跨平台Chrome路径检测 (Windows注册表 / macOS / Linux)
    │   └── 反检测: 禁用自动化特征、图片加载、扩展
    │
    DriverManager (driver_manager.py - ChromeDriver自动管理)
        └── 多源下载降级: Chrome for Testing → NPM镜像 → CNPM → Google Storage
```

## 关键设计决策

- **强制headless**: `monitor_service.py` 中强制设置 `headless=True` 进行并行查询，调试时需临时注释
- **两阶段查询**: 先尝试API查余额（快），失败后回退到Selenium网页登录（慢但可靠）
- **浏览器池复用**: 预创建实例避免重复启动Chrome，复用前清理状态（cookies等）
- **配置优先级**: 代码默认值 < `config.json` < 环境变量 `ANYROUTER_HEADLESS=1` < CLI参数
- **线程安全**: 监控服务的状态更新使用 `status_lock` 保护，修改状态代码必须持锁
- **资源清理**: 浏览器用上下文管理器(`with`)，`main.py` 注册 `atexit` + 信号处理器确保退出时杀Chrome

## 配置文件

- `credentials.txt` - 账号凭证 `用户名,密码,API_KEY`（敏感，已gitignore）
- `config.json` - 运行配置（自动生成，已gitignore）
- `config.json.example` / `credentials.txt.example` - 示例模板
- `balance_cache.json` - 余额缓存
- `daily_web_login_state.json` - 每日Web重认证状态追踪
- `.claude/settings.json` - Claude API Key存储路径
- `.codex/auth.json` - OpenAI API Key存储路径（含Windows/WSL路径检测）

## UI规范

- **收缩态**: 50×50圆圈 → **展开态**: 320×200
- **深色主题**: 背景 `rgba(20,20,30,230)`，紫色按钮 `#5555ff→#8855ff`，成功 `#4caf50`，失败 `#f44336`
- **账号标记**: `●` = 当前Claude Token，`◎` = 当前OpenAI Key
- **快捷键**: `Ctrl+Q` 退出，`F5` 刷新，`Esc` 收缩，`Ctrl+L` 进度日志，`Ctrl+Shift+C` 复制总余额
- **动画参数**: 悬停延迟收缩 600ms，查询完成后自动收缩 2000ms

## 开发注意事项

1. **余额提取脆弱**: 目标网站DOM变化需更新 `auth_manager.py` 中的JavaScript提取逻辑
2. **并发上限9线程**: 超过会耗尽系统资源
3. **Chrome路径检测**: 新增平台需在 `browser_manager.py` 的 `_find_chrome_executable()` 添加路径
4. **回调必须设置**: 自定义UI必须正确设置监控服务的三个回调函数
5. **`performance_monitor.py`**: 在 `monitor_service.py` 中被导入但文件可能不存在，导入有 try/except 保护
6. **提交规范**: 短命令式中文消息，如 `优化登录流程`、`修复密钥泄露`
7. **Python 3.8+**: `snake_case` 函数/变量，`PascalCase` 类名
