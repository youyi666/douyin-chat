import json
import re
import os
import time
from pathlib import Path

# ================= 配置区域 =================
SOURCE_FOLDER = "data"
OUTPUT_FOLDER = os.path.join("source", "processed_result")

# 建议设为 False 以便调试，正式跑可改为 True
ONLY_SAVE_RISK_ITEMS = False

# ================= 1. 客服风控规则 (保持不变) =================
RISK_RULES_SERVICE = [
    {
        "label": "引导线下/私下交易",
        "triggers": [ r"(加|发|留|转).{0,5}(微信|V|v|QQ|支付宝|私下|转账)" ],
        "ignore": [ r"(优惠券|领券|发货|教程|视频|核实|单号|JD|SF|链接|截图)" ]
    },
    {
        "label": "辱骂/攻击用户",
        "triggers": [ r"(滚|傻(B|b|X|x|逼)|脑子(有病|进水)|眼瞎|去死|神经病|听不懂|弱智)" ],
        "ignore": [ r"(不|别|垃圾袋|垃圾桶|开玩笑)" ]
    },
    {
        "label": "直接推诿/不耐烦",
        "triggers": [
            r"(我|这边).{0,5}(不管|不负责|没法弄|没空)",
            r"(自己).{0,5}(去|找|问).{0,5}(快递|官网)"
        ],
        "ignore": [ r"(建议|可以|麻烦|核实|打包|运输)" ]
    }
]

# ================= 2. 用户反馈规则 (v4.2 重大升级) =================
# 分为两类：A. 产品品质(Quality)  B. 服务体验(Service/Trust)

USER_MSG_MIN_LEN = 2 

# A. 产品品质问题 (沿用 v4.1)
RISK_RULES_USER_QUALITY = [
    {
        "trigger": r"(质量|做工|手感|面料|材质|东西|实物|屏幕|开关|按键|电池|蓝牙|声音|画面).{0,10}(差|烂|硬|薄|粗糙|垃圾|不行|太次|坏|裂|碎|失灵|没反应|不亮|花屏)",
    },
    {
        "trigger": r"(假货|旧的|二手的|次品|有人用过|翻新机)",
    },
    {
        "trigger": r"^(坏了|坏的|开不了机|没反应|用不了|打不开|烂了|太差了)$", 
    },
    {
        "trigger": r"(根本|完全|直接).{0,5}(用不了|没法用|坏了)",
    }
]

# B. 【新增】服务体验与信任危机 (针对您刚提到的案例)
RISK_RULES_USER_SERVICE = [
    {
        # 1. 信任崩塌/指责欺诈
        "label": "信任/诚信投诉",
        "trigger": r"(骗子|骗人|忽悠|欺诈|黑店|垃圾店|没信用|没有信用|抹黑|大企业.*结果|恶心|套路)",
    },
    {
        # 2. 威胁投诉/维权
        "label": "威胁投诉/升级",
        "trigger": r"(投诉|举报|315|黑猫|工商|报警|曝光|媒体|差评)",
    },
    {
        # 3. 时效/拖延抱怨
        "label": "时效/拖延投诉",
        "trigger": r"(超时|太慢|拖延|墨迹|等到什么时候|还没发|几天了)",
    },
    {
        # 4. 服务态度指责
        "label": "服务态度投诉",
        "trigger": r"(态度|嘴脸|复读机|机器人).{0,10}(差|不行|恶劣|敷衍)",
    }
]

# ================= 核心处理逻辑 =================

def standardize_data(item):
    """数据标准化"""
    if 'id' not in item:
        item['id'] = item.get('info', '').replace('ID：', '').strip() or f"UNKNOWN_{int(time.time())}"
    if 'customer_name' not in item:
        item['customer_name'] = "未知客户"
    if 'last_time' not in item and 'date' in item:
        item['last_time'] = item['date']
    
    clean_messages = []
    for msg in item.get('messages', []):
        msg['time'] = msg.get('time', '00:00')[:5]
        clean_messages.append(msg)
    item['messages'] = clean_messages
    return item

def check_service_risk(content):
    """检测客服违规"""
    for rule in RISK_RULES_SERVICE:
        is_safe = False
        for ignore_pat in rule['ignore']:
            if re.search(ignore_pat, content, re.IGNORECASE):
                is_safe = True
                break
        if is_safe: continue 

        for trigger_pat in rule['triggers']:
            if re.search(trigger_pat, content, re.IGNORECASE):
                return {
                    "is_risk": True,
                    "type": "客服风险",
                    "reason": f"命中[{rule['label']}]",
                    "point": 50
                }
    return None

def check_user_risk(content):
    """检测用户 (合并了品质 + 服务)"""
    if len(content) < USER_MSG_MIN_LEN:
        return None
    
    if content in ["怎么弄", "在吗", "好的", "哦哦", "谢谢", "发货", "什么", "怎么"]:
        return None

    # 1. 检查品质问题
    for rule in RISK_RULES_USER_QUALITY:
        if re.search(rule['trigger'], content, re.IGNORECASE):
             return {
                "is_risk": True,
                "type": "品质反馈",
                "reason": "疑似品质/故障反馈",
                "point": 60
            }
            
    # 2. 【新增】检查服务/信任问题
    for rule in RISK_RULES_USER_SERVICE:
        if re.search(rule['trigger'], content, re.IGNORECASE):
             return {
                "is_risk": True,
                "type": "服务投诉",  # 新类型
                "reason": f"疑似[{rule['label']}]",
                "point": 55
            }
            
    return None

def analyze_chat_logic(messages):
    checkpoints = []
    highlight_indices = []
    total_deduction = 0
    
    # 辅助逻辑：计算客服说“抱歉”的次数，如果太多，说明客服被逼急了，也是风险
    apology_count = 0 
    
    for idx, msg in enumerate(messages):
        # 【修改】忽略系统消息
        if msg.get('type') == 'system':
            continue

        content = msg.get('content', '').strip()
        sender = msg.get('sender', '')
        if not content: continue
        
        risk_item = None
        
        if sender == 'Service':
            risk_item = check_service_risk(content)
            # 统计道歉次数
            if re.search(r"(抱歉|对不起|不好意思|谅解)", content):
                apology_count += 1
                
        elif sender == 'User':
            risk_item = check_user_risk(content)
            
        if risk_item:
            checkpoints.append({
                "point": risk_item['point'],
                "type": risk_item['type'],
                "reason": risk_item['reason'],
                "text": content
            })
            if idx not in highlight_indices:
                highlight_indices.append(idx)
            
            # 【修改】仅当发送者是客服(Service)时才进行实质性扣分
            # 用户(User)的风险仅做预警记录(checkpoints)，不影响分数
            if sender == 'Service':
                total_deduction += risk_item['point']

    # 【新增逻辑】如果客服道歉超过4次，判定为潜在服务风险（即使没违规）
    if apology_count >= 4 and total_deduction == 0:
        total_deduction += 20
        checkpoints.append({
            "point": 20,
            "type": "服务预警",
            "reason": "客服频繁道歉(>3次)，可能存在处理困难",
            "text": "(全局检测)"
        })

    final_score = max(0, 100 - total_deduction)
    is_risk = len(checkpoints) > 0
    
    return {
        "score": final_score,
        "is_risk": is_risk,
        "summary": f"发现 {len(checkpoints)} 处异常" if is_risk else "",
        "checkpoints": checkpoints,
        "highlight_indices": highlight_indices
    }

def process_single_file(file_path, output_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            raw_data = json.load(f)
        if not isinstance(raw_data, list): raw_data = [raw_data]
        processed_data = []
        
        print(f"  > 正在分析 {file_path.name} (共 {len(raw_data)} 条对话)...")

        for item in raw_data:
            item = standardize_data(item)
            
            ai_result = analyze_chat_logic(item.get('messages', []))
            
            if ONLY_SAVE_RISK_ITEMS and not ai_result['is_risk']:
                continue
                
            if ai_result['is_risk']:
                # 打印出命中的原因，方便您确认这次是否抓到了
                reasons = [cp['reason'] for cp in ai_result['checkpoints']]
                # 注意：这里的扣分显示的是 total_deduction，如果只是用户投诉，扣分可能为0，但会有原因显示
                print(f"    [命中] ID:{item.get('id')} 扣分:{100-ai_result['score']} 原因:{reasons}")

            item['ai_analysis'] = ai_result
            processed_data.append(item)

        if not processed_data: 
            print("    [提示] 无风险对话，跳过。")
            return True

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(processed_data, f, ensure_ascii=False, indent=2)
        print(f"    [完成] 已生成: {output_path}")
        return True
    except Exception as e:
        print(f"  [Error] {file_path.name}: {e}")
        return False

def run_batch_job():
    if not os.path.exists(OUTPUT_FOLDER): os.makedirs(OUTPUT_FOLDER)
    files = list(Path(SOURCE_FOLDER).glob("*.json"))
    print(f"开始 v4.2 分析 (新增信任/时效投诉检测)...")
    
    count = 0
    for f in files:
        if "_analyzed" in f.name: continue
        output_path = os.path.join(OUTPUT_FOLDER, f.name)
        if process_single_file(f, output_path):
            count += 1
            
    print(f"任务全部完成。")

if __name__ == "__main__":
    run_batch_job()