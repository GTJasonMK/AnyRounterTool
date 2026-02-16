@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion

:: ============================================================
::  AnyRouter - 一键安装依赖 (基于 uv)
:: ============================================================

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"
set "VENV_DIR=%SCRIPT_DIR%venv"

echo ============================================================
echo  AnyRouter - 依赖安装
echo ============================================================
echo.

:: -----------------------------------------------------------
::  [1/4] 检测系统 Python
:: -----------------------------------------------------------
echo [1/4] 检测 Python...

set "SYS_PYTHON="
where python >nul 2>&1 && for /f "delims=" %%P in ('where python 2^>nul') do if not defined SYS_PYTHON set "SYS_PYTHON=%%P"
if not defined SYS_PYTHON (
    where python3 >nul 2>&1 && for /f "delims=" %%P in ('where python3 2^>nul') do if not defined SYS_PYTHON set "SYS_PYTHON=%%P"
)
if not defined SYS_PYTHON (
    echo [ERROR] 未找到 Python, 请先安装 Python 3.8+
    goto :fail
)

for /f "tokens=2 delims= " %%V in ('"!SYS_PYTHON!" --version 2^>^&1') do set "PY_VER=%%V"
for /f "tokens=1,2 delims=." %%A in ("!PY_VER!") do (
    if %%A lss 3 goto :ver_fail
    if %%A equ 3 if %%B lss 8 goto :ver_fail
)
echo       Python !PY_VER!
goto :step_uv

:ver_fail
echo [ERROR] Python !PY_VER! 版本过低, 需要 3.8+
goto :fail

:: -----------------------------------------------------------
::  [2/4] 确保 uv 可用
:: -----------------------------------------------------------
:step_uv
echo [2/4] 检测 uv...

where uv >nul 2>&1
if !errorlevel! equ 0 (
    for /f "delims=" %%U in ('where uv 2^>nul') do (
        echo       uv 已安装: %%U
        goto :step_venv
    )
)

echo       uv 未找到, 正在安装...
"!SYS_PYTHON!" -m pip install uv --quiet --disable-pip-version-check 2>nul
if !errorlevel! neq 0 (
    echo       pip 安装失败, 尝试官方安装脚本...
    powershell -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex" 2>nul
)

:: 安装后重新检测 (可能在 Python Scripts 目录下)
where uv >nul 2>&1
if !errorlevel! neq 0 (
    :: 尝试从 pip 安装的路径找
    for /f "delims=" %%S in ('"!SYS_PYTHON!" -c "import sysconfig; print(sysconfig.get_path(\"scripts\"))" 2^>nul') do (
        if exist "%%S\uv.exe" set "PATH=%%S;!PATH!"
    )
)

where uv >nul 2>&1
if !errorlevel! neq 0 (
    echo [ERROR] uv 安装失败. 请手动安装: pip install uv
    goto :fail
)
echo       uv 安装完成

:: -----------------------------------------------------------
::  [3/4] 创建虚拟环境
:: -----------------------------------------------------------
:step_venv
echo [3/4] 配置虚拟环境...

if exist "%VENV_DIR%\Scripts\python.exe" (
    echo       虚拟环境已存在, 跳过创建
) else (
    uv venv "%VENV_DIR%" --python "!SYS_PYTHON!"
    if !errorlevel! neq 0 (
        echo [ERROR] 虚拟环境创建失败
        goto :fail
    )
    echo       虚拟环境已创建
)

:: -----------------------------------------------------------
::  [4/4] 安装依赖
:: -----------------------------------------------------------
echo [4/4] 安装依赖...

uv pip install -r "%SCRIPT_DIR%requirements.txt" --python "%VENV_DIR%\Scripts\python.exe"
if !errorlevel! neq 0 (
    echo [ERROR] 依赖安装失败
    goto :fail
)

:: 校验关键依赖
set "CHECK_OK=1"
for %%M in (PyQt6 selenium psutil requests) do (
    "%VENV_DIR%\Scripts\python.exe" -c "import %%M" >nul 2>&1
    if !errorlevel! neq 0 (
        echo [ERROR] %%M 未正确安装
        set "CHECK_OK=0"
    )
)

if "!CHECK_OK!"=="0" goto :fail

echo.
echo ============================================================
echo  安装完成
echo  启动方式: start.bat 或 venv\Scripts\python.exe main.py
echo ============================================================
goto :end

:fail
echo.
echo ============================================================
echo  安装失败, 请检查上方错误信息
echo ============================================================
pause
exit /b 1

:end
pause
exit /b 0
