// config.js
module.exports = {
    url: 'https://im.jinritemai.com/pc_seller_v2/main/data/historyConversation',
    authFile: 'auth.json',
    dataDir: './data',
    
    selectors: {
        popups: [
            { role: 'button', name: '放弃定制售后' },
            { role: 'button', name: 'Close' }
        ],
        dateInput: 'input[placeholder="开始日期"]', 
        searchBtn: 'button:has-text("查询")',
        
        // 这里的 row 可能需要根据你的实际列表调整，如果没有 data-qa-id，就用更通用的
        tableRow: 'tr', 
        
        chatModal: {
            switchAllBtn: 'button:has-text("切换该用户全部聊天消息")',
            
            // ✅ 核心修正1：滚动容器
            messageContainer: '.scroller', 
            
            // ✅ 核心修正2：每一条消息的包裹层
            messageItem: 'div[data-qa-id="qa-message-warpper"]',
            
            closeBtn: 'button[aria-label="Close"]'
        }
    }
};