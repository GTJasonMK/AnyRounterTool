# Repository Guidelines

This guide equips contributors to extend AnyRouter responsibly and consistently.

## Project Structure & Module Organization
- `main.py` launches the floating desktop client and wires configuration loading.
- `config.json.example` and `credentials.txt.example` document runtime settings; copy them locally and keep secrets out of Git.
- `src/` hosts modular services: browser orchestration (`browser_manager.py`, `browser_pool.py`), authentication and balance extraction (`auth_manager.py`), scheduling (`monitor_service.py`), and UI (`ui_floating.py`).
- Packaged artifacts live in `dist/main/` alongside runtime logs; snapshots such as `ARLoginer_1.0.0.exe` serve local smoke validation only.

## Build, Test, and Development Commands
- Install dependencies: `pip install -r requirements.txt`.
- Launch the floating client: `python main.py`; add `--headless` for background polling or `--debug` for verbose logging.
- Point to alternate configs with `python main.py --config path/to/config.json`.
- Exercise modules independently: `python src/browser_manager.py`, `python src/auth_manager.py`, `python src/monitor_service.py`.

## Coding Style & Naming Conventions
- Target Python 3.8+, four-space indentation, and `snake_case` for functions and variables.
- Prefer `PascalCase` for classes and exceptions, uppercase with underscores for constants.
- Reuse existing helpers in `src/` instead of introducing bespoke frameworks; keep inline comments brief and intentional.

## Testing Guidelines
- The repository has no pytest or unittest suite; rely on the smoke commands above before every PR.
- Validate login and balance changes with sample credentials in `credentials.txt`, and review `anyrouter_monitor.log` for anomalies.
- For UI adjustments, run `python main.py` in headed mode and confirm expand, collapse, and refresh flows.

## Commit & Pull Request Guidelines
- Follow the existing history: short imperative messages, usually Chinese verbs plus context, for example `优化登录流程`.
- Scope each commit narrowly; document notable file touches when the diff spans multiple modules.
- PR descriptions must include: purpose, major changes, verification commands, linked issues, and screenshots or GIFs for UI work.

## Communication & Collaboration
- 与仓库维护者及代理互动时默认使用中文，确保讨论与记录口径一致。
- 共享运行命令、日志或截图时保持敏感信息脱敏，并同步记录到 PR 描述。

## Configuration & Release Notes
- Never commit generated `config.json`, `credentials.txt`, or log files; they already live in `.gitignore`.
- When repackaging, rebuild in a clean virtual environment with PyInstaller to mirror `dist/main/main.exe`, and record version bumps or installer notes in the PR summary.
