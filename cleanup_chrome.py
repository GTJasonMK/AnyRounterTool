#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Chrome进程清理工具 - 清理所有残留的Chrome和ChromeDriver进程
用法: python cleanup_chrome.py
"""

import os
import sys
import time
import subprocess


def kill_chrome_processes():
    """强制清理所有Chrome和ChromeDriver进程"""
    print("正在清理Chrome和ChromeDriver进程...")

    killed_count = 0

    if os.name == 'nt':  # Windows
        for proc_name in ['chrome.exe', 'chromedriver.exe']:
            try:
                result = subprocess.run(
                    ['taskkill', '/F', '/IM', proc_name, '/T'],
                    capture_output=True,
                    timeout=5,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )

                output = result.stdout.decode('gbk', errors='ignore')
                if '成功' in output or 'SUCCESS' in output:
                    # 统计被清理的进程数
                    count = output.count('PID')
                    killed_count += count
                    print(f"已清理 {count} 个 {proc_name} 进程")
                elif '找不到' not in output and 'not found' not in output.lower():
                    print(f"{proc_name}: {output.strip()}")

            except Exception as e:
                print(f"清理 {proc_name} 时出错: {e}")

    else:  # Linux/macOS
        for proc_name in ['chrome', 'chromedriver']:
            try:
                result = subprocess.run(
                    ['pkill', '-9', proc_name],
                    capture_output=True,
                    timeout=5
                )
                if result.returncode == 0:
                    print(f"已清理 {proc_name} 进程")
                    killed_count += 1
            except:
                pass

    # 使用psutil作为备用方案
    try:
        import psutil
        psutil_count = 0
        for proc in psutil.process_iter(['name', 'pid']):
            try:
                proc_name = proc.info['name'].lower()
                if 'chrome' in proc_name or 'chromedriver' in proc_name:
                    proc.kill()
                    proc.wait(timeout=2)
                    psutil_count += 1
            except:
                pass

        if psutil_count > 0:
            print(f"通过psutil额外清理了 {psutil_count} 个进程")
            killed_count += psutil_count

    except ImportError:
        print("警告: psutil未安装，无法使用备用清理方案")
    except Exception as e:
        print(f"psutil清理时出错: {e}")

    return killed_count


def main():
    """主函数"""
    print("=" * 50)
    print("Chrome进程清理工具")
    print("=" * 50)

    # 执行清理
    killed = kill_chrome_processes()

    # 等待进程完全退出
    print("\n等待进程完全退出...")
    time.sleep(1)

    # 检查是否还有残留进程
    print("\n检查残留进程...")
    if os.name == 'nt':
        result = subprocess.run(
            ['tasklist'],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        output = result.stdout.decode('gbk', errors='ignore')

        chrome_count = output.lower().count('chrome.exe')
        chromedriver_count = output.lower().count('chromedriver.exe')

        if chrome_count > 0 or chromedriver_count > 0:
            print(f"警告: 仍有 {chrome_count} 个chrome.exe和 {chromedriver_count} 个chromedriver.exe进程")
        else:
            print("✓ 所有Chrome和ChromeDriver进程已清理完毕")

    print(f"\n总共清理了 {killed} 个进程")
    print("=" * 50)

    return 0


if __name__ == "__main__":
    sys.exit(main())
