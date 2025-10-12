# 验证说明

- 已执行 `python3 -m compileall src/ui_floating.py`，确认语法检查通过。
- GUI 功能需在目标 Windows 主机上手动操作：
  - 在本地 Windows 路径 `C:\Users\<用户名>\.codex\auth.json` 下触发“设为OpenAI配置Key”，确认写入成功并观察 UI 标记。
  - 针对每个 WSL 发行版（例如 `Ubuntu-24.04`），使用右键菜单设置 Key，确认对应 `~/.codex/auth.json` 被更新，可借助 `wsl.exe cat ~/.codex/auth.json` 验证。
  - 检查弹窗提示中是否列出各目标的成功/失败详情。
- WSL 写入依赖 `wsl.exe`，若主机禁用或超时将以错误提示展示，请根据提示排查。
