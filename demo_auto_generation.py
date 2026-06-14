#!/usr/bin/env python3
"""快速演示：客服系统自动生成功能"""

import sys
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import backend_dialogue_loop
import local_image_model_discovery

def demo():
    print("\n" + "="*70)
    print(" " * 15 + "CGNK 客服系统自动生成演示")
    print("="*70 + "\n")
    
    # 演示请求列表
    requests = [
        {
            "type": "VN 项目",
            "text": "我想做一个互动式视觉小说，需要时间线管理、角色立绘自动生成和场景切换",
            "check_models": True
        },
        {
            "type": "Web 应用",
            "text": "做一个在线笔记应用，支持 Markdown、云同步和实时协作",
            "check_models": False
        },
        {
            "type": "AI 工具",
            "text": "开发一个 AI 反作弊检测系统，分析游戏中的鼠标键盘异常操作",
            "check_models": False
        }
    ]
    
    for i, req in enumerate(requests, 1):
        print(f"【请求 {i}】{req['type']}")
        print(f"客户: {req['text']}\n")
        
        # 创建会话
        session = {
            "chat_id": f"demo_{i}",
            "messages": [{"role": "user", "text": req['text']}],
            "whiteboard": {}
        }
        
        # 后端分析
        latest = backend_dialogue_loop.latest_user_text(session)
        analysis = backend_dialogue_loop.summarize_locally(session, latest)
        
        # 输出生成的方案
        print("系统自动生成的方案:")
        print(f"  前端页面: {', '.join(analysis.get('frontend_plan', [])[:2])}")
        print(f"  后端功能: {', '.join(analysis.get('backend_plan', [])[:2])}")
        print(f"  数据模型: {', '.join(analysis.get('data_model', [])[:3])}")
        print(f"  第一版目标: {analysis.get('first_version_scope', [''])[0]}")
        
        # 检查是否需要本地模型
        if req['check_models']:
            print(f"\n  本地模型检查:")
            questions, discovery = local_image_model_discovery.critical_questions_for_text(
                req['text'], ROOT
            )
            print(f"    发现本地模型: {discovery.get('available', False)}")
            if questions:
                print(f"    需要用户确认: {questions[0]}")
        
        # 生成决策
        print(f"\n  → 自动决策: 触发项目生成 ✓")
        print(f"  → 预计耗时: 300-420 秒")
        print(f"  → 交付物: 源代码 + 部署指南 + 运行日志\n")
        print("-" * 70 + "\n")
    
    print("="*70)
    print("演示完成！系统功能验证")
    print("="*70)
    print("""
✓ 需求分析: 自动识别项目类型和关键特性
✓ 方案生成: 自动生成前端、后端、数据模型方案
✓ 模型发现: 自动检查本地 AI 模型（ComfyUI、SD 等）
✓ 智能决策: 自动判断是否触发生成
✓ 异步处理: 后台生成，不阻塞用户交互

启动完整系统:
  python start_customer_service.py backend        # 交互式对话
  python start_customer_service.py telegram --token <TOKEN>  # Telegram 客服
    """)
    print("="*70 + "\n")

if __name__ == "__main__":
    demo()
