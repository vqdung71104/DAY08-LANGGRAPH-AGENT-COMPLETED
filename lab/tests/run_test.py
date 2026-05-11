#!/usr/bin/env python
"""Auto test runner - fixed version"""

import json
import sys
import subprocess
from pathlib import Path

# Hardcode đường dẫn tuyệt đối - dùng forward slash
LAB_PATH = Path(r"D:/day08-langgraph-agent-completed/lab")  # Đổi \ thành /
PROJECT_PATH = Path(r"D:/day08-langgraph-agent-completed")  # Đổi \ thành /
SCENARIOS_FILE = LAB_PATH / "data" / "scenarios_hidden.jsonl"
OUTPUT_FILE = LAB_PATH / "outputs" / "test_results.json"
CONFIG_FILE = LAB_PATH / "auto_config.yaml"

# Thêm project path vào sys.path
sys.path.insert(0, str(PROJECT_PATH))

def setup():
    """Tạo thư mục cần thiết"""
    (LAB_PATH / "outputs").mkdir(parents=True, exist_ok=True)
    (LAB_PATH / "reports").mkdir(parents=True, exist_ok=True)
    
def create_config():
    """Tạo file config - dùng single quotes để tránh escape"""
    # Dùng single quotes thay vì double quotes
    config_content = f'''scenarios_path: '{SCENARIOS_FILE}'
checkpointer: "memory"
database_url: null
report_path: '{LAB_PATH}/reports/test_report.md'
'''
    CONFIG_FILE.write_text(config_content, encoding="utf-8")
    return CONFIG_FILE

def run_scenarios():
    """Chạy scenarios bằng CLI"""
    print("=" * 60)
    print("🚀 Running LangGraph Agent Tests")
    print("=" * 60)
    print(f"📁 Scenarios: {SCENARIOS_FILE}")
    print(f"📄 Output: {OUTPUT_FILE}")
    print("-" * 60)
    
    # Chạy command
    cmd = f'python -m langgraph_agent_lab.cli run-scenarios --config "{CONFIG_FILE}" --output "{OUTPUT_FILE}"'
    result = subprocess.run(cmd, shell=True, cwd=str(PROJECT_PATH), capture_output=True, text=True)
    
    if result.stdout:
        print(result.stdout)
    if result.stderr and "error" not in result.stderr.lower():
        print("⚠️ Warnings:", result.stderr)
    
    return result.returncode == 0

def analyze_results():
    """Phân tích kết quả"""
    if not OUTPUT_FILE.exists():
        print("❌ No results file generated!")
        return False
    
    with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    print("\n" + "=" * 60)
    print("📊 TEST RESULTS")
    print("=" * 60)
    
    print(f"\n📈 Summary:")
    print(f"   Total scenarios: {data['total_scenarios']}")
    print(f"   ✅ Success rate: {data['success_rate']:.2%}")
    print(f"   📍 Avg nodes visited: {data['avg_nodes_visited']:.1f}")
    print(f"   🔄 Total retries: {data['total_retries']}")
    print(f"   👤 Human interrupts: {data['total_interrupts']}")
    
    print("\n📋 Detailed Results:")
    print("-" * 80)
    print(f"{'ID':<15} {'Expected':<12} {'Actual':<12} {'Status':<8} {'Retries':<8} {'Nodes':<6}")
    print("-" * 80)
    
    passed = sum(1 for s in data['scenario_metrics'] if s['success'])
    
    for s in data['scenario_metrics']:
        status = "✅ PASS" if s['success'] else "❌ FAIL"
        actual = s['actual_route'] or 'N/A'
        print(f"{s['scenario_id']:<15} {s['expected_route']:<12} {actual:<12} {status:<8} {s['retry_count']:<8} {s['nodes_visited']:<6}")
    
    print("\n" + "=" * 60)
    print(f"🎯 FINAL SCORE: {passed}/{data['total_scenarios']} ({data['success_rate']:.2%})")
    print("=" * 60)
    
    return True

def cleanup():
    """Dọn dẹp file tạm"""
    if CONFIG_FILE.exists():
        CONFIG_FILE.unlink()

def main():
    try:
        setup()
        create_config()
        
        if run_scenarios():
            analyze_results()
        else:
            print("❌ Failed to run scenarios!")
        
        cleanup()
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()