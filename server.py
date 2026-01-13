from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
import json
import os
import sys
import glob

# 解决中文编码
sys.stdout.reconfigure(encoding='utf-8')

app = Flask(__name__)
CORS(app)

# 这里配置你的数据文件夹路径 (默认为当前目录)
DATA_DIR = '.' 

@app.route('/')
def index():
    if os.path.exists('dashboard.html'):
        return send_file('dashboard.html')
    elif os.path.exists('index.html'):
        return send_file('index.html')
    else:
        return "找不到 dashboard.html，请确保文件在同一目录下", 404

# 🆕 新接口：获取所有有数据的日期列表
@app.route('/api/meta', methods=['GET'])
def get_meta_data():
    # 扫描目录下所有的 YYYY-MM-DD.json 文件
    files = glob.glob(os.path.join(DATA_DIR, "????-??-??.json"))
    dates = []
    for f in files:
        # 从文件名提取日期 (去掉路径和 .json 后缀)
        filename = os.path.basename(f)
        date_str = filename.replace('.json', '')
        dates.append(date_str)
    
    # 按日期倒序排列（最新的在前面）
    dates.sort(reverse=True)
    return jsonify({"dates": dates})

# 🔄 升级接口：根据日期获取会话
@app.route('/api/sessions', methods=['GET'])
def get_sessions():
    # 获取前端传来的 date 参数，如果没有则为空
    target_date = request.args.get('date')
    
    if not target_date:
        return jsonify([])

    file_path = os.path.join(DATA_DIR, f"{target_date}.json")
    
    if not os.path.exists(file_path):
        return jsonify([]) # 如果该日期没文件，返回空数组
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return jsonify(data)
    except Exception as e:
        print(f"读取 {target_date} 失败: {e}")
        return jsonify([]), 500

# 🔄 升级接口：写入指定日期的文件
@app.route('/api/review', methods=['POST'])
def update_review():
    try:
        req_data = request.json
        session_id = req_data.get('id')
        action = req_data.get('action') 
        target_date = req_data.get('date') # 👈 关键：前端必须告诉我是哪一天的
        
        if not target_date:
            return jsonify({"status": "error", "msg": "缺少日期参数"}), 400

        file_path = os.path.join(DATA_DIR, f"{target_date}.json")
        
        if not os.path.exists(file_path):
            return jsonify({"status": "error", "msg": "该日期文件不存在"}), 404

        with open(file_path, 'r', encoding='utf-8') as f:
            all_data = json.load(f)
        
        found = False
        for item in all_data:
            if str(item['id']) == str(session_id):
                found = True
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
                    if 'original_score' not in analysis:
                        analysis['original_score'] = analysis['score']
                    analysis['review_status'] = 'approved'
                    analysis['is_risk'] = False
                    analysis['score'] = 100
                    analysis['manual_reviewed'] = True
                elif action == 'admin_reject':
                    analysis['review_status'] = 'rejected'
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
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(all_data, f, ensure_ascii=False, indent=2)
            return jsonify({"status": "success", "msg": "保存成功"})
        else:
            return jsonify({"status": "error", "msg": "ID未找到"}), 404

    except Exception as e:
        print(f"❌ 错误: {e}")
        return jsonify({"status": "error", "msg": str(e)}), 500

if __name__ == '__main__':
    print(">>> 服务已启动，支持日期切换模式")
    app.run(host='0.0.0.0', port=5000, debug=True)