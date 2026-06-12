#!/usr/bin/env python3
"""
CGNK 客服系统启动脚本
支持三种模式：
1. 后端对话模式 (快速测试)
2. 完整 E2E 流程 (系统验证)
3. Telegram 客服模式 (生产环境)
"""

import sys
import argparse
import pathlib
import os

ROOT = pathlib.Path(__file__).resolve().parent
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

def run_backend_mode():
    """后端对话模式 - 直接调用后端接口"""
    print("\n" + "="*60)
    print("CGNK 客服系统 - 后端对话模式")
    print("="*60 + "\n")

    import backend_dialogue_loop
    import local_image_model_discovery

    print("输入客户请求 (Ctrl+C 退出):\n")

    session = {"chat_id": "local_test", "messages": [], "whiteboard": {}}
    turn = 1

    while True:
        try:
            user_input = input(f"客户 #{turn}: ").strip()
            if not user_input:
                continue

            # Add to session
            session["messages"].append({
                "role": "user",
                "text": user_input,
                "timestamp": str(__import__('datetime').datetime.now())
            })

            # Analyze
            latest = backend_dialogue_loop.latest_user_text(session)
            analysis = backend_dialogue_loop.summarize_locally(session, latest)

            print(f"\n助手分析:")
            print(f"  前端: {', '.join(analysis.get('frontend_plan', [])[:2])}")
            print(f"  后端: {', '.join(analysis.get('backend_plan', [])[:2])}")
            print(f"  范围: {analysis.get('first_version_scope', [''])[0]}\n")

            # Check for local models
            if "图片" in user_input or "背景" in user_input or "立绘" in user_input:
                questions, discovery = local_image_model_discovery.critical_questions_for_text(
                    user_input, ROOT
                )
                print(f"  模型检查: {'✓ 本地模型可用' if discovery.get('available') else '○ 未发现本地模型'}")
                if questions:
                    print(f"  需要确认: {questions[0]}")
                print()

            turn += 1

        except KeyboardInterrupt:
            print("\n再见！")
            break
        except Exception as e:
            print(f"  错误: {e}\n")

def run_e2e_mode():
    """完整 E2E 模式 - 运行完整测试"""
    print("\n运行完整 E2E 测试...\n")

    import subprocess
    result = subprocess.run([sys.executable, "test_e2e_service.py"], cwd=ROOT)
    return result.returncode

def run_telegram_mode(token, chat_id=None):
    """Telegram 客服模式 - 启动客服系统"""
    print("\n" + "="*60)
    print("CGNK 客服系统 - Telegram 实时模式")
    print("="*60)
    print(f"Token: {token[:20]}..." if len(token) > 20 else f"Token: {token}")
    if chat_id:
        print(f"Chat ID: {chat_id}")
    print("="*60 + "\n")

    import subprocess

    env = os.environ.copy()
    env["CGKN_TELEGRAM_GENERATION_MODE"] = "api"
    env.setdefault("CGNK_USE_LOCAL_MODEL", "1")
    env.setdefault("CGNK_AUTO_START_OLLAMA", "1")
    tasks = {
        item.strip()
        for item in env.get("CGNK_LOCAL_MODEL_TASKS", "").replace(";", ",").split(",")
        if item.strip()
    }
    tasks.update({"customer_public_reply", "customer_status", "backend_dialogue"})
    env["CGNK_LOCAL_MODEL_TASKS"] = ",".join(sorted(tasks))
    env.setdefault("CGNK_OLLAMA_MODEL", "qwen2.5:7b-instruct")
    env.setdefault("OLLAMA_HOST", "http://127.0.0.1:11434")

    args = [
        sys.executable,
        str(SCRIPTS_DIR / "telegram_live_bridge.py"),
        "--token", token,
        "--model", "gpt-5.4-nano",
        "--generation-timeout", "420"
    ]

    if chat_id:
        args.extend(["--chat-id", str(chat_id)])

    print("启动客服系统...")
    print("Ctrl+C 停止\n")

    try:
        result = subprocess.run(args, env=env)
        return result.returncode
    except KeyboardInterrupt:
        print("\n\n客服系统已停止")
        return 0
    except Exception as e:
        print(f"启动失败: {e}")
        return 1

def main():
    parser = argparse.ArgumentParser(
        description="CGNK 客服系统启动工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 后端对话模式 (快速测试)
  python start_customer_service.py backend

  # 完整 E2E 测试
  python start_customer_service.py e2e

  # Telegram 客服模式 (需要 Token)
  python start_customer_service.py telegram --token YOUR_BOT_TOKEN

  # 限制特定聊天 ID
  python start_customer_service.py telegram --token YOUR_BOT_TOKEN --chat-id 123456789
        """)

    parser.add_argument("mode", choices=["backend", "e2e", "telegram"],
                       help="运行模式")
    parser.add_argument("--token", default="",
                       help="Telegram Bot Token (telegram 模式必需)")
    parser.add_argument("--chat-id", default="",
                       help="限制仅接收的聊天 ID (可选)")

    args = parser.parse_args()

    if args.mode == "backend":
        run_backend_mode()
        return 0

    elif args.mode == "e2e":
        return run_e2e_mode()

    elif args.mode == "telegram":
        if not args.token:
            print("错误: telegram 模式需要 --token 参数")
            print("请指定 Telegram Bot Token")
            return 1
        return run_telegram_mode(args.token, args.chat_id)

    return 0

if __name__ == "__main__":
    sys.exit(main())
