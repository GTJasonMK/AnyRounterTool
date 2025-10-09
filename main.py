#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AnyRouter 余额监控器 - 主程序入口
重构版本 2.0 - 悬浮窗口版
"""

import sys
import os
import argparse
import logging
import signal
import atexit
from pathlib import Path

# 添加src目录到Python路径
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from PyQt6.QtWidgets import QApplication
from src.ui_floating import FloatingMonitor


def setup_logging(level=logging.INFO):
    """设置日志系统"""
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

    # 控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(log_format))

    # 文件处理器
    file_handler = logging.FileHandler(
        'anyrouter_monitor.log',
        encoding='utf-8'
    )
    file_handler.setFormatter(logging.Formatter(log_format))

    # 配置根日志记录器
    logging.basicConfig(
        level=level,
        handlers=[console_handler, file_handler]
    )


def check_requirements():
    """检查必要的依赖"""
    required_modules = {
        'PyQt6': 'PyQt6',
        'selenium': 'selenium',
        'psutil': 'psutil (可选，用于自动检测CPU核心数)'
    }

    missing = []
    for module, name in required_modules.items():
        try:
            __import__(module)
        except ImportError:
            if module != 'psutil':  # psutil是可选的
                missing.append(name)

    if missing:
        print("缺少必要的依赖包:")
        for pkg in missing:
            print(f"  - {pkg}")
        print("\n请运行以下命令安装:")
        print("  pip install " + " ".join(missing))
        return False

    return True


def cleanup_resources():
    """快速清理所有资源"""
    logger = logging.getLogger(__name__)
    logger.info("正在清理资源...")

    try:
        from src.browser_pool import _global_pool
        if _global_pool:
            # 直接强制关闭所有浏览器
            for instance in _global_pool.instances:
                try:
                    instance.driver.quit()
                except:
                    pass
            _global_pool.instances.clear()
            logger.info("浏览器池已清理")

        # 强制杀死Chrome进程
        try:
            import psutil
            killed = 0
            for proc in psutil.process_iter(['name', 'cmdline']):
                try:
                    if 'chrome' in proc.info['name'].lower():
                        # 检查是否是自动化控制的Chrome
                        cmdline = proc.info.get('cmdline', [])
                        if any('--remote-debugging' in str(arg) for arg in cmdline):
                            proc.kill()
                            killed += 1
                except:
                    pass
            if killed > 0:
                logger.info(f"已杀死 {killed} 个Chrome进程")
        except:
            pass

    except Exception as e:
        logger.error(f"清理浏览器池失败: {e}")


def signal_handler(signum, frame):
    """处理系统信号"""
    logger = logging.getLogger(__name__)
    logger.info(f"接收到信号 {signum}，正在退出...")
    cleanup_resources()
    import os
    os._exit(0)  # 强制退出


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='AnyRouter 余额监控器')
    parser.add_argument(
        '--debug',
        action='store_true',
        help='启用调试模式'
    )
    parser.add_argument(
        '--config',
        type=str,
        default='.',
        help='配置文件目录路径'
    )
    parser.add_argument(
        '--headless',
        action='store_true',
        help='强制使用无头浏览器模式'
    )

    args = parser.parse_args()

    # 设置日志级别
    log_level = logging.DEBUG if args.debug else logging.INFO
    setup_logging(log_level)

    logger = logging.getLogger(__name__)
    logger.info("AnyRouter 余额监控器启动")
    logger.info(f"配置目录: {args.config}")

    # 检查依赖
    if not check_requirements():
        sys.exit(1)

    # 注册清理函数
    atexit.register(cleanup_resources)

    # 注册信号处理器
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 创建应用程序
    app = QApplication(sys.argv)
    app.setApplicationName("AnyRouter Monitor")
    app.setOrganizationName("AnyRouter")

    # 设置环境变量（如果需要强制无头模式）
    if args.headless:
        os.environ['ANYROUTER_HEADLESS'] = '1'

    # 创建并显示悬浮窗口
    try:
        window = FloatingMonitor()
        window.show()
        logger.info("悬浮窗口已启动")

        # 运行应用
        exit_code = app.exec()

        # 快速清理并退出
        cleanup_resources()
        import os
        os._exit(exit_code)

    except KeyboardInterrupt:
        logger.info("用户中断程序")
        cleanup_resources()
        import os
        os._exit(0)

    except Exception as e:
        logger.error(f"启动失败: {e}", exc_info=True)
        cleanup_resources()
        import os
        os._exit(1)


if __name__ == "__main__":
    main()