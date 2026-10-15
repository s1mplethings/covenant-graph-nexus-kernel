#!/usr/bin/env python3
"""
E2E test: Customer Service (Codex conversation) + Backend Dialogue Integration
Tests if the system auto-generates and discovers local models.
"""

import sys
import pathlib
import json
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import check_connectivity
import backend_dialogue_loop
import local_image_model_discovery
import capability_strategy

def now_str():
    return datetime.now(timezone.utc).isoformat()

def test_backend_response():
    """Test backend dialogue generation for a customer request."""
    print("=" * 60)
    print("测试 1: 后端对话生成")
    print("=" * 60)
    
    # Simulate a customer message
    session = {
        "conversation_id": "test_chat_123",
        "messages": [
            {
                "role": "user",
                "text": "我想做一个视觉小说类型的故事生成工具，需要时间线梳理和背景图片生成",
                "timestamp": now_str()
            }
        ],
        "whiteboard": {}
    }
    
    print(f"客户消息: {session['messages'][0]['text']}\n")
    
    # Run backend dialogue to analyze
    latest_text = backend_dialogue_loop.latest_user_text(session)
    print(f"提取的文本: {latest_text}\n")
    
    # Summarize locally (should identify requirements)
    analysis = backend_dialogue_loop.summarize_locally(
        session, 
        latest_text, 
        reason="initial_request"
    )
    
    print("后端分析结果:")
    for key in ["frontend_plan", "backend_plan", "data_model", "first_version_scope", "assumptions"]:
        if key in analysis:
            print(f"  {key}: {analysis[key]}")
    print()
    
    # Check for local image discovery
    if analysis.get("local_image_model_discovery", {}).get("checked"):
        print("PASS: 系统已检查本地图片模型\n")
    if not analysis.get("ready_to_generate"):
        raise AssertionError("明确项目请求未被 backend dialogue 放行")
    return analysis

def test_local_model_discovery():
    """Test if system detects available local image models."""
    print("=" * 60)
    print("测试 2: 本地模型发现")
    print("=" * 60)
    
    vn_request = "我需要背景图生成，请检查本地ComfyUI或Stable Diffusion"
    
    critical_questions, local_discovery = local_image_model_discovery.critical_questions_for_text(
        vn_request, 
        ROOT
    )
    
    print(f"检查内容: {vn_request}\n")
    print(f"临界问题: {critical_questions}\n")
    print(f"本地模型发现结果:")
    print(f"  Checked: {local_discovery.get('checked', False)}")
    print(f"  Available: {local_discovery.get('available', False)}")
    if local_discovery.get("models"):
        print(f"  Models: {local_discovery.get('models', [])}")
    if local_discovery.get("backends"):
        print(f"  Backends: {local_discovery.get('backends', [])}")
    print()
    
    return local_discovery

def test_capability_strategy():
    """Test capability strategy for complex requests."""
    print("=" * 60)
    print("测试 3: 能力策略识别")
    print("=" * 60)
    
    cs_request = "我想做一个反作弊系统，需要分析CSGO游戏中的鼠标键盘操作异常"
    
    strategy = capability_strategy.build_capability_strategy(cs_request, ROOT)
    
    print(f"请求内容: {cs_request}\n")
    print("识别的能力策略:")
    for key, value in strategy.items():
        if value:
            print(f"  {key}: {value}")
    print()
    
    return strategy

def test_api_connectivity():
    """Verify API connectivity with default settings."""
    print("=" * 60)
    print("测试 4: API 连接性")
    print("=" * 60)
    
    print("检查 API 配置...")
    result = check_connectivity.check_api(live=True, timeout_sec=10, model="gpt-5.4-nano")
    
    if result.get("ok"):
        print("PASS: API 连接成功")
        print(f"  Base URL: {result.get('base_url')}")
        print(f"  Model: {result.get('model')}")
        print(f"  API Key Source: {result.get('api_key_source', 'unknown')}")
    else:
        print("FAIL: API 连接失败")
        print(f"  Error: {result.get('error')}")
    print()
    
    return result

def test_e2e_flow():
    """Test full E2E flow: Customer input -> Analysis -> Generation decision."""
    print("=" * 60)
    print("测试 5: 完整端到端流程")
    print("=" * 60)
    
    customer_requests = [
        "我想做一个时间旅行冒险类视觉小说，需要时间线管理和角色立绘生成",
        "做一个个人投资组合网站，展示我的编程项目",
        "我需要一个数据分析平台，可以处理CSV和JSON数据，生成图表"
    ]
    
    for i, request in enumerate(customer_requests, 1):
        print(f"\n--- 请求 {i} ---")
        print(f"客户: {request}\n")
        
        session = {
            "conversation_id": f"test_{i}",
            "messages": [{"role": "user", "text": request, "timestamp": now_str()}],
            "whiteboard": {}
        }
        
        # Backend processes
        latest = backend_dialogue_loop.latest_user_text(session)
        analysis = backend_dialogue_loop.summarize_locally(session, latest)
        
        # Check if needs local model
        has_image_gen = "图片生成" in request or "背景" in request or "立绘" in request
        if has_image_gen:
            _, discovery = local_image_model_discovery.critical_questions_for_text(request, ROOT)
            print(f"  → 需要图片生成: 是")
            print(f"  → 本地模型可用: {discovery.get('available', False)}")
        
        # Check capability strategy
        strategy = capability_strategy.build_capability_strategy(request, ROOT)
        if strategy.get("capabilities"):
            print(f"  → 识别的能力: 是")
        
        needs_gen = bool(analysis.get("ready_to_generate"))
        print(f"  → 触发生成: {'是' if needs_gen else '否'}")
        if not needs_gen:
            raise AssertionError(f"明确项目请求未触发生成决策: {request}")
        
    print()

if __name__ == "__main__":
    print("\n")
    print("+" + "=" * 58 + "+")
    print("|" + " CGNK 客服系统 E2E 测试 ".center(58) + "|")
    print("+" + "=" * 58 + "+")
    print()
    
    try:
        # Test 1: Backend response
        analysis1 = test_backend_response()
        
        # Test 2: Local model discovery
        discovery = test_local_model_discovery()
        
        # Test 3: Capability strategy
        strategy = test_capability_strategy()
        
        # Test 4: API connectivity
        api_result = test_api_connectivity()
        
        # Test 5: E2E flow
        test_e2e_flow()
        
        all_ok = bool(analysis1.get("ready_to_generate")) and bool(api_result.get("ok"))
        print("=" * 60)
        print("PASS: 所有测试完成" if all_ok else "FAIL: E2E 验收未通过")
        print("=" * 60)
        print()

        print("系统状态:")
        print("  PASS: 后端对话分析正常")
        print(f"  {'PASS' if discovery.get('checked') else 'INFO'}: 本地模型检查 {'已启用' if discovery.get('checked') else '禁用'}")
        print(f"  {'PASS' if api_result.get('ok') else 'FAIL'}: API 连接")
        print()
        if not all_ok:
            sys.exit(1)
        
    except Exception as e:
        print(f"FAIL: 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
