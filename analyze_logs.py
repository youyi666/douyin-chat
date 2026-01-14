import json
import re
import os
import time
from pathlib import Path
from openai import OpenAI

# ================= 配置区域 =================
# 输入文件夹路径
SOURCE_FOLDER = "data"

# 输出文件夹路径
OUTPUT_FOLDER = os.path.join("source", "processed_result")

# API 配置
API_KEY = "sk-5ce512e159c64ce7a67b838828dd4f88" 
BASE_URL = "https://api.deepseek.com" 
MODEL_NAME = "deepseek-chat" 

# 阈值控制：是否只保存有风险的会话？
# True = 仅保存有问题的数据（最终文件会很小，全是干货）
# False = 保存所有数据，没问题的只给个100分
ONLY_SAVE_RISK_ITEMS = True 

client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

# ================= 核心处理逻辑 =================

def extract_customer_name(messages):
    """从系统消息提取客户姓名"""
    for msg in messages:
        if msg.get('type') == 'system':
            content = msg.get('content', '')
            match = re.search(r"姓名：\s*([^\n]+)", content)
            if match:
                return match.group(1).strip()
    return "未知客户"

def standardize_data(item):
    """
    【数据标准化】
    确保原始数据包含 HTML 前端所需的字段 (id, last_time, customer_name)。
    """
    if 'id' not in item:
        if 'info' in item:
            item['id'] = item['info'].replace('ID：', '').replace('ID:', '').strip()
        else:
            item['id'] = f"UNKNOWN_{int(time.time())}"

    if 'customer_name' not in item:
        item['customer_name'] = extract_customer_name(item.get('messages', []))

    if 'last_time' not in item and 'date' in item:
        item['last_time'] = item['date']

    # 修复时间格式供前端显示，但不传给AI
    clean_messages = []
    last_valid_time = "00:00"
    for msg in item.get('messages', []):
        raw_time = msg.get('time', '')
        if not raw_time or raw_time.strip() == "":
            final_time = last_valid_time
        else:
            final_time = raw_time.strip()[:5]
            last_valid_time = final_time
        msg['time'] = final_time
        clean_messages.append(msg)
    
    item['messages'] = clean_messages
    return item

def prepare_transcript_for_ai(messages):
    """
    【极简模式】数据清洗
    功能：
    1. 只保留 User 和 Service 的文本。
    2. 去掉时间、System消息、Image占位符、冗余废话。
    3. 拼接成最简短的文本流。
    4. 建立 简化后行号 -> 原始messages索引 的映射，用于后续“还原”。
    """
    transcript = ""
    msg_indices_map = {} # {AI看到的行号 : 原始messages列表中的index}
    valid_count = 0
    
    # 预编译正则：去掉URL
    url_pattern = re.compile(r'http[s]?://\S+')
    
    for idx, msg in enumerate(messages):
        sender = msg.get('sender', 'Unknown')
        content = msg.get('content', '')
        
        # --- 过滤规则 ---
        # 1. 丢弃 System 消息（不需要AI分析系统提示）
        if sender == 'System': 
            continue
            
        # 2. 丢弃空内容
        if not content: 
            continue
            
        # 3. 丢弃机器人自动接入提示（省Token）
        if sender == 'Service' and any(x in content for x in ['接入', '会话分配', '排队', '很高兴为您服务']):
            # 只有当它是纯粹的废话时才跳过，如果包含实质回复则保留
            if len(content) < 50: 
                continue

        # --- 内容清洗 ---
        # 1. 链接转短标
        clean_content = url_pattern.sub('[链接]', content)
        # 2. 移除换行，变成一行
        clean_content = clean_content.replace('\n', ' ').strip()
        
        # --- 格式化 ---
        # 简化角色名
        role = "客" if sender == "User" else "服"
        
        # 拼接： "0. [客]: 什么时候发货"
        line = f"{valid_count}. [{role}]: {clean_content}"
        transcript += f"{line}\n"
        
        # --- 记录映射 ---
        # 关键步骤：记下 AI 看到的第 valid_count 行，对应原始数据的第 idx 行
        msg_indices_map[valid_count] = idx
        valid_count += 1

    if not transcript:
        return None, {}

    return transcript, msg_indices_map

def analyze_chat_with_llm(transcript):
    """调用 LLM 进行分析 - 专注高风险"""
    prompt = f"""
    你是一名电商合规质检员。请分析以下对话记录。

    【输入说明】
    格式为：行号. [角色]: 内容
    角色：[客]=用户, [服]=客服
    内容已简化，忽略时间与上下文缺失。

    【任务目标】
    仅检测 **客服(服)** 的 **高风险** 违规行为。
    忽略用户的态度问题。忽略非原则性的礼貌问题。

    【高风险定义】
    1. 辱骂、嘲讽、阴阳怪气用户。
    2. 明确的虚假承诺（如答应赠品却赖账、答应发货却拖延）。
    3. 严重推诿、复读机式无效回复、长时间不解决问题。
    4. 诱导线下交易或泄露隐私。

    【输出要求】
    严格返回 JSON 格式：
    {{
        "score": 0-100 (整数，无高风险则100，有则根据严重程度扣分),
        "is_risk": boolean (是否存在高风险),
        "summary": "简短的一句话违规摘要（仅在有风险时填写，无风险留空）",
        "checkpoints": [
            {{"point": -扣分值, "reason": "具体哪一句违规，为什么"}}
        ],
        "highlight_indices": [违规行的行号数字]
    }}
    
    对话内容：
    {transcript}
    """
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "你是一个严格的质检JSON生成器。只输出JSON。"},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.1 # 降低随机性，更严谨
        )
        content = response.choices[0].message.content
        content = content.replace("```json", "").replace("```", "")
        return json.loads(content)
    except Exception as e:
        print(f"  [Error] AI 请求失败: {e}")
        return None

def process_single_file(file_path, output_path):
    """处理单个文件"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            raw_data = json.load(f)
        
        processed_data = []
        if not isinstance(raw_data, list):
            raw_data = [raw_data]

        for item in raw_data:
            # 1. 原始数据补全 (为了后续还原 HTML)
            item = standardize_data(item)
            
            chat_id = item.get('id', 'Unknown')
            raw_messages = item.get('messages', [])
            
            # 2. 制作极简版 Input (提取干货 + 建立索引映射)
            transcript, idx_map = prepare_transcript_for_ai(raw_messages)
            
            if not transcript:
                continue # 空对话直接跳过

            # 3. AI 分析
            print(f"    分析 ID: {chat_id} (消息数: {len(idx_map)})...", end="")
            ai_result = analyze_chat_with_llm(transcript)
            
            if ai_result:
                # === 核心逻辑：过滤 ===
                is_risk = ai_result.get('is_risk', False)
                score = ai_result.get('score', 100)

                # 如果开启了“只保留风险项”且判定为无风险，则直接过滤掉，不保存
                if ONLY_SAVE_RISK_ITEMS and not is_risk:
                    print(" -> 无风险，已过滤")
                    continue
                
                print(f" -> 风险: {is_risk}, 分数: {score}")

                # === 核心逻辑：还原 ===
                # AI 返回的是简化后的行号 (0, 1, 2...)
                # 我们需要利用 idx_map 把它映射回原始 messages 的真实索引
                original_indices = []
                if 'highlight_indices' in ai_result:
                    for ai_idx in ai_result['highlight_indices']:
                        try:
                            # 还原步骤：AI行号 -> 原始msg列表下标
                            real_idx = idx_map.get(int(ai_idx))
                            if real_idx is not None:
                                original_indices.append(real_idx)
                        except:
                            pass
                    ai_result['highlight_indices'] = original_indices # 替换回原始索引
                
                # 补全前端必要字段
                ai_result['review_status'] = 'pending' if is_risk else 'confirmed'
                ai_result['manual_reviewed'] = False
                
                # 将 AI 结果挂载回原始的“重型”对象中
                # 这样前端就能读取到完整的 time, image, system 等信息，同时也能看到高亮
                item['ai_analysis'] = ai_result
                processed_data.append(item)
            else:
                print(" -> AI 响应异常")

        # 如果没有数据（都被过滤了），就不生成文件了，或者生成空列表
        if not processed_data:
            print(f"  [提示] 文件 {file_path.name} 中无高风险对话，跳过生成。")
            return True

        # 保存结果
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(processed_data, f, ensure_ascii=False, indent=2)
            
        return True
    except Exception as e:
        print(f"  [Critical Error] 处理失败 {file_path}: {e}")
        return False

# ================= 批量扫描主程序 =================

def run_batch_job():
    if not os.path.exists(OUTPUT_FOLDER):
        os.makedirs(OUTPUT_FOLDER)

    source_path = Path(SOURCE_FOLDER)
    json_files = list(source_path.glob("*.json"))
    
    print(f"扫描目录: {SOURCE_FOLDER}")
    print(f"待处理文件: {len(json_files)} 个")
    print(f"策略模式: {'仅保存高风险会话' if ONLY_SAVE_RISK_ITEMS else '保存所有会话'}")
    print("-" * 30)

    processed_count = 0

    for file_path in json_files:
        if "_analyzed" in file_path.name: continue
            
        output_name = file_path.name
        output_path = os.path.join(OUTPUT_FOLDER, output_name)

        if os.path.exists(output_path):
            print(f"[跳过] {file_path.name} (已存在)")
            continue

        print(f"[处理中] {file_path.name}")
        success = process_single_file(file_path, output_path)
        
        if success:
            processed_count += 1

    print("-" * 30)
    print(f"任务结束。处理文件数: {processed_count}")

if __name__ == "__main__":
    run_batch_job()