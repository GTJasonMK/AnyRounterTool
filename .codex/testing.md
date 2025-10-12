# 测试记录

- `python3 -m compileall src/ui_floating.py` ✅
  - 验证结果：编译通过，无语法错误。
  - 说明：覆盖最新的 WSL 路径解析与 wsl.exe 写入逻辑，运行环境未实际调用 wsl.exe。
