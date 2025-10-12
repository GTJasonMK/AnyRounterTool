# 验收契约

- **接口规格**：
  - `_load_current_openai_key()` 返回当前 `OPENAI_API_KEY` 字符串，异常时返回空串并记录日志。
  - `_save_openai_key_to_codex_auth(token: str)` 将传入 Key 写入 `Path.home() / ".codex" / "auth.json"`，保留已有字段并返回是否成功。
  - `set_openai_key(username, apikey)` 触发写入 OpenAI Key 并更新状态显示。
- **边界条件**：
  - 当文件不存在或 JSON 解析失败时，采用默认结构 `{}` 并写入新 Key。
  - 当账号缺少 API Key 时，禁止显示“设为OpenAI配置Key”动作。
  - 当同一账号同时为 Claude 与 OpenAI 使用者时，表格需能体现双重状态。
- **性能要求**：
  - 读写仅针对单个 JSON 文件，操作应保持同步执行，无显著延迟。
- **测试标准**：
  - 手动验证：运行 UI，右键账号将 Key 设置为 Claude 与 OpenAI，检查 `.claude/settings.json` 与 `.codex/auth.json`。
  - 文件校验：确认 UI 标记符合预期（例如 `●` 与 `◎` 等符号）。
