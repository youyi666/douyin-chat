from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
import json
import os
import sys
import glob

# 解决控制台中文乱码问题
sys.stdout.reconfigure(encoding='utf-8')

app = Flask(__name__)
CORS(app)

# ================= 配置区域 =================
# 配置数据文件夹路径
# [MODIFIED] 修改路径为 source\processed_result
# 原注释：如果你的 json 文件在当前目录下的 data 文件夹里，请保持为 'data'
# 原注释：如果 json 文件和 server.py 在同一级目录，请改为 '.'
# 使用 os.path.join 确保在 Windows/Linux 下路径拼接正确
DATA_DIR = os.path.join('source', 'processed_result')

# 启动时检查文件夹是否存在，不存在则创建（避免报错）
# os.makedirs 会递归创建目录（例如 source 不存在时也会一并创建）
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)
    print(f"提示: 已自动创建数据文件夹 '{DATA_DIR}'，请将 JSON 文件放入其中。")

# ================= 路由定义 =================

@app.route('/')
def index():
    # 优先寻找 dashboard.html
    if os.path.exists('dashboard.html'):
        return send_file('dashboard.html')
    elif os.path.exists('index.html'):
        return send_file('index.html')
    else:
        return "找不到 dashboard.html，请确保文件在同一目录下", 404

# 🆕 接口：获取所有有数据的日期列表
@app.route('/api/meta', methods=['GET'])
def get_meta_data():
    # 扫描 DATA_DIR 目录下所有的 YYYY-MM-DD.json 文件
    # 使用 os.path.join 确保跨平台路径正确
    search_pattern = os.path.join(DATA_DIR, "????-??-??.json")
    if DATA_DIR == '.':
        # 如果是当前目录，glob 可能会扫到非日期文件，加强一下过滤
        pass 
        
    files = glob.glob(search_pattern)
    dates = []
    
    for f in files:
        # 从文件名提取日期 (去掉路径和 .json 后缀)
        filename = os.path.basename(f)
        date_str = filename.replace('.json', '')
        dates.append(date_str)
    
    # 按日期倒序排列（最新的在前面）
    dates.sort(reverse=True)
    return jsonify({"dates": dates})

# 🔄 接口：根据日期获取会话
@app.route('/api/sessions', methods=['GET'])
def get_sessions():
    # 获取前端传来的 date 参数
    target_date = request.args.get('date')
    
    if not target_date:
        return jsonify([])

    # 拼接完整路径：source/processed_result/2026-01-13.json
    file_path = os.path.join(DATA_DIR, f"{target_date}.json")
    
    if not os.path.exists(file_path):
        return jsonify([]) # 如果该日期没文件，返回空数组
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return jsonify(data)
    except json.JSONDecodeError:
        print(f"❌ 读取 {target_date} 失败: JSON 格式错误")
        return jsonify([])
    except Exception as e:
        print(f"❌ 读取 {target_date} 失败: {e}")
        return jsonify([]), 500

# 🔄 接口：写入指定日期的文件
# 注意：这里必须顶格写，不能有缩进
@app.route('/api/review', methods=['POST'])
def update_review():
    try:
        req_data = request.json
        if not req_data:
            return jsonify({"status": "error", "msg": "无效的请求数据"}), 400

        session_id = req_data.get('id')
        action = req_data.get('action') 
        target_date = req_data.get('date') # 👈 关键：前端必须告诉我是哪一天的
        
        if not target_date:
            return jsonify({"status": "error", "msg": "缺少日期参数"}), 400

        file_path = os.path.join(DATA_DIR, f"{target_date}.json")
        
        if not os.path.exists(file_path):
            return jsonify({"status": "error", "msg": "该日期文件不存在"}), 404

        # 读取现有数据
        with open(file_path, 'r', encoding='utf-8') as f:
            all_data = json.load(f)
        
        found = False
        # 遍历查找对应的 session ID
        for item in all_data:
            # 转换为字符串比较，防止一个是 int 一个是 string
            if str(item.get('id')) == str(session_id):
                found = True
                # 确保 ai_analysis 字段存在
                if 'ai_analysis' not in item:
                    item['ai_analysis'] = {}
                
                analysis = item['ai_analysis']
                
                # === 状态流转逻辑 ===
                if action == 'submit_appeal': 
                    analysis['review_status'] = 'pending'
                    analysis['manual_reviewed'] = True
                elif action == 'confirm_risk':
                    analysis['review_status'] = 'confirmed'
                    analysis['is_risk'] = True
                    analysis['manual_reviewed'] = True
                elif action == 'admin_approve':
                    # 保存原始分数以便恢复
                    if 'original_score' not in analysis:
                        analysis['original_score'] = analysis.get('score', 60)
                    analysis['review_status'] = 'approved'
                    analysis['is_risk'] = False
                    analysis['score'] = 100
                    analysis['manual_reviewed'] = True
                elif action == 'admin_reject':
                    analysis['review_status'] = 'rejected'
                    # 如果有原始分数，恢复它
                    if 'original_score' in analysis:
                        analysis['score'] = analysis['original_score']
                    analysis['manual_reviewed'] = True
                elif action == 'admin_reset':
                    analysis['review_status'] = None
                    analysis['manual_reviewed'] = False
                    if 'original_score' in analysis:
                        analysis['score'] = analysis['original_score']
                break
        
        if found:
            # 写入回文件
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(all_data, f, ensure_ascii=False, indent=2)
            return jsonify({"status": "success", "msg": "保存成功"})
        else:
            return jsonify({"status": "error", "msg": "ID未找到"}), 404

    except Exception as e:
        print(f"❌ 写入错误: {e}")
        return jsonify({"status": "error", "msg": str(e)}), 500

if __name__ == '__main__':
    print(f">>> 服务已启动")
    print(f">>> 数据目录: {os.path.abspath(DATA_DIR)}")
    print(f">>> 请访问: http://localhost:5000")
    app.run(host='0.0.0.0', port=5000, debug=True)