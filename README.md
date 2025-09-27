# AnyRouter 余额监控器

极简优雅的 AnyRouter 余额监控工具。

## ✨ 功能

- **智能并发** - 自动检测最优线程数
- **准确余额** - 提取当前可用余额
- **API Key管理** - 右键用户名管理API Key
  - 复制API Key到剪贴板
  - 一键设置ANTHROPIC_AUTH_TOKEN环境变量
  - 自动标记当前使用的API Key (●)
- **置顶窗口** - 便于监控
- **拖拽移动** - 自由定位

## 🚀 使用

### 1. 安装依赖
```bash
pip install selenium PyQt6 psutil
```

### 2. 配置账号
编辑 `credentials.txt`:
```
用户名1,密码1,sk-xxxxxxxx
用户名2,密码2,sk-xxxxxxxx
用户名3,密码3,sk-xxxxxxxx
```

### 3. 启动
```bash
python balance_monitor.py
```

### 4. API Key管理
- **查看当前**: 顶部显示当前ANTHROPIC_AUTH_TOKEN对应的用户
- **标记识别**: 当前使用的用户名前显示 ● 标记
- **复制API Key**: 右键用户名 → "复制 XXX 的API Key"
- **设置系统环境变量**: 右键用户名 → "设置为环境变量"
  - 使用setx /M命令设置系统环境变量
  - 影响范围: 整个系统（所有用户）
  - 需要管理员权限运行程序
  - 弹窗确认设置结果和权限提示

## 💡 特性

- **极简界面** - 纯白背景，无颜色干扰
- **智能并发** - 基于CPU核心数自动调整
- **准确数据** - 提取"当前余额"而非历史消耗
- **便捷复制** - 右键即可复制API Key
- **小巧窗口** - 350×280像素

## 📁 文件结构

```
├── balance_monitor.py    # 主程序
├── fast_anyrouter_login.py    # 批量登录
├── gui_debug.py         # 调试工具
├── credentials.txt      # 账号配置
└── chromedriver.exe    # 浏览器驱动
```

**启动**: `python balance_monitor.py`