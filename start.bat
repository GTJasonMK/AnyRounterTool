@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion

:: ============================================================
::  AnyRouter - 一键启动脚本
::  功能: 虚拟环境管理 / 依赖校验 / 资源清理 / 启动监控器
:: ============================================================

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

set "VENV_DIR=%SCRIPT_DIR%venv"
set "PYTHON_EXE="
set "PIP_EXE="
set "EXIT_CODE=0"

:: -----------------------------------------------------------
::  [1/5] 启动前 - 清理残留进程和临时文件
:: -----------------------------------------------------------
echo [1/5] 清理残留进程...
call :cleanup_chrome_quiet

:: -----------------------------------------------------------
::  [2/5] 检测或创建 Python 虚拟环境
:: -----------------------------------------------------------
echo [2/5] 检测 Python 环境...

if exist "%VENV_DIR%\Scripts\python.exe" (
    set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
    set "PIP_EXE=%VENV_DIR%\Scripts\pip.exe"
    echo       虚拟环境就绪
    goto :step_deps
)

:: 寻找系统 Python
set "SYS_PYTHON="
where python >nul 2>&1 && for /f "delims=" %%P in ('where python 2^>nul') do if not defined SYS_PYTHON set "SYS_PYTHON=%%P"
if not defined SYS_PYTHON (
    where python3 >nul 2>&1 && for /f "delims=" %%P in ('where python3 2^>nul') do if not defined SYS_PYTHON set "SYS_PYTHON=%%P"
)
if not defined SYS_PYTHON (
    echo [ERROR] 未找到 Python. 请安装 Python 3.8+ 后重试.
    pause
    exit /b 1
)

:: 校验版本
for /f "tokens=2 delims= " %%V in ('"!SYS_PYTHON!" --version 2^>^&1') do set "PY_VER=%%V"
for /f "tokens=1,2 delims=." %%A in ("!PY_VER!") do (
    if %%A lss 3 goto :ver_fail
    if %%A equ 3 if %%B lss 8 goto :ver_fail
)
echo       Python !PY_VER!
goto :create_venv

:ver_fail
echo [ERROR] Python !PY_VER! 版本过低, 需要 3.8+
pause
exit /b 1

:create_venv
echo       创建虚拟环境...
"!SYS_PYTHON!" -m venv "%VENV_DIR%"
if !errorlevel! neq 0 (
    echo [ERROR] 虚拟环境创建失败. 请检查 Python 安装是否完整.
    pause
    exit /b 1
)
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
set "PIP_EXE=%VENV_DIR%\Scripts\pip.exe"
echo       虚拟环境已创建

:: -----------------------------------------------------------
::  [3/5] 校验并安装依赖
:: -----------------------------------------------------------
:step_deps
echo [3/5] 校验依赖...

set "MISSING="
for %%M in (PyQt6 selenium psutil requests) do (
    "!PYTHON_EXE!" -c "import %%M" >nul 2>&1
    if !errorlevel! neq 0 set "MISSING=!MISSING! %%M"
)

if defined MISSING (
    echo       缺少:!MISSING!
    echo       安装中...
    "!PIP_EXE!" install -r "%SCRIPT_DIR%requirements.txt" --quiet --disable-pip-version-check
    if !errorlevel! neq 0 (
        echo [WARN] pip 返回非零, 校验关键依赖...
    )
    :: 关键依赖二次校验
    for %%M in (PyQt6 selenium) do (
        "!PYTHON_EXE!" -c "import %%M" >nul 2>&1
        if !errorlevel! neq 0 (
            echo [ERROR] %%M 安装失败. 请手动运行:
            echo         "!PIP_EXE!" install -r requirements.txt
            pause
            exit /b 1
        )
    )
    echo       依赖已安装
) else (
    echo       全部就绪
)

:: -----------------------------------------------------------
::  [4/5] 检查端口冲突 / 检测已运行实例
:: -----------------------------------------------------------
echo [4/5] 环境检查...

:: 检测是否已有实例在运行
tasklist /fi "windowtitle eq AnyRouter Monitor" 2>nul | findstr /i "python" >nul 2>&1
if !errorlevel! equ 0 (
    echo [WARN] 检测到已有 AnyRouter 实例运行中
)

:: Chrome 调试端口使用 --remote-debugging-port=0 由浏览器自动分配
:: (已在 browser_manager.py 中配置, 无需硬编码端口号)
echo       端口: 动态分配

:: -----------------------------------------------------------
::  [5/5] 启动
:: -----------------------------------------------------------
echo [5/5] 启动 AnyRouter 监控器...
echo ============================================================

"!PYTHON_EXE!" "%SCRIPT_DIR%main.py" %*
set "EXIT_CODE=!errorlevel!"

:: -----------------------------------------------------------
::  退出后清理
:: -----------------------------------------------------------
echo.
echo ============================================================
echo 正在清理资源...
call :cleanup_chrome_quiet
echo 清理完成 (退出码: !EXIT_CODE!)

if !EXIT_CODE! neq 0 (
    echo.
    echo 程序异常退出, 详情见 anyrouter_monitor.log
    pause
)

endlocal
exit /b %EXIT_CODE%


:: ===========================================================
::  子程序: 静默清理 ChromeDriver 及自动化 Chrome 进程
:: ===========================================================
:cleanup_chrome_quiet

:: 清理 chromedriver 进程
tasklist /fi "imagename eq chromedriver.exe" 2>nul | findstr /i "chromedriver" >nul 2>&1
if !errorlevel! equ 0 (
    taskkill /f /im chromedriver.exe /t >nul 2>&1
    echo       已清理 chromedriver 进程
)

:: 清理 anyrouter 专用的 Chrome 临时目录
for /d %%D in ("%TEMP%\anyrouter_chrome_*") do (
    rd /s /q "%%D" >nul 2>&1
)

goto :eof
