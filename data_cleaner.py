import json
import re
import os
from pathlib import Path

# ================= 配置区域 =================
# 存放脏数据的文件夹
SOURCE_FOLDER = r"F:\douyin-chat\source\processed_result"

# 清洗后存放的文件夹 (建议新建一个，避免覆盖原文件)
OUTPUT_FOLDER = os.path.join(SOURCE_FOLDER, "cleaned_data")

# ================= 清洗逻辑 =================

def extract_customer_name(messages):
    """从系统消息提取客户姓名（兼容脏数据的格式）"""
    for msg in messages:
        if msg.get('type') == 'system':
            content = msg.get('content', '')
            # 匹配 "姓名：\n黄*" 或 "姓名：黄*"
            match = re.search(r"姓名：\s*([^\n]+)", content)
            if match:
                return match.group(1).strip()
    return "未知客户"

def clean_single_item(item):
    """
    将单个脏数据对象转化为标准的老版本格式
    """
    # 1. 修复 ID：从 info 字段提取
    if 'id' not in item and 'info' in item:
        # 去掉 "ID：" 前缀，保留纯数字
        item['id'] = item['info'].replace('ID：', '').replace('ID:', '').strip()
    
    # 2. 修复 last_time：从 date 字段映射
    if 'last_time' not in item and 'date' in item:
        item['last_time'] = item['date']

    # 3. 修复 messages 里的时间和格式
    clean_messages = []
    last_valid_time = "00:00"
    
    for msg in item.get('messages', []):
        raw_time = msg.get('time', '')
        
        # 时间修复逻辑
        if not raw_time or raw_time.strip() == "":
            final_time = last_valid_time
        else:
            # 截取前5位 (14:42:56 -> 14:42)
            final_time = raw_time.strip()[:5]
            last_valid_time = final_time
            
        msg['time'] = final_time
        clean_messages.append(msg)
    
    item['messages'] = clean_messages

    # 4. 修复 customer_name：如果缺失则提取
    if 'customer_name' not in item:
        item['customer_name'] = extract_customer_name(clean_messages)

    # 5. 清理多余的脏字段 (可选，保持整洁)
    if 'info' in item:
        del item['info'] 
    if 'date' in item:
        del item['date']

    return item

def run_cleaner():
    if not os.path.exists(OUTPUT_FOLDER):
        os.makedirs(OUTPUT_FOLDER)
    
    json_files = list(Path(SOURCE_FOLDER).glob("*.json"))
    print(f"找到 {len(json_files)} 个文件，准备清洗...")

    count = 0
    for file_path in json_files:
        # 跳过已经处理过的文件
        if "_cleaned" in file_path.name or "_analyzed" in file_path.name:
            continue

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # 兼容列表或单对象
            if isinstance(data, list):
                cleaned_data = [clean_single_item(i) for i in data]
            else:
                cleaned_data = [clean_single_item(data)]

            # 保存为 _cleaned 文件
            output_name = file_path.stem + "_cleaned.json"
            output_path = os.path.join(OUTPUT_FOLDER, output_name)
            
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(cleaned_data, f, ensure_ascii=False, indent=2)
            
            print(f"✔ 已清洗: {file_path.name}")
            count += 1
            
        except Exception as e:
            print(f"❌ 失败 {file_path.name}: {e}")

    print(f"清洗完成，共处理 {count} 个文件。")

if __name__ == "__main__":
    run_cleaner()