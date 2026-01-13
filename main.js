const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const dayjs = require('dayjs');
const config = require('./config');

/**
 * 工具函数：确保目录存在
 */
function ensureDir(dirPath) {
    if (!fs.existsSync(dirPath)) {
        fs.mkdirSync(dirPath, { recursive: true });
    }
}

/**
 * 主程序入口
 */
(async () => {
    // 1. 基础检查
    ensureDir(config.dataDir);

    // 检查是否有登录凭证
    if (!fs.existsSync(config.authFile)) {
        console.error('❌ 错误：未找到登录凭证文件 (auth.json)。');
        console.error('⚠️ 请先运行 "node login.js" 进行扫码登录，登录成功后再运行此脚本。');
        return;
    }

    console.log('✅ 检测到登录凭证，正在启动浏览器...');

    // 2. 启动浏览器
    // headless: false 方便你观察运行情况，如果以后在服务器跑改为 true
    const browser = await chromium.launch({ headless: true });
    
    // 使用保存的 Cookie/LocalStorage 上下文
    const context = await browser.newContext({ storageState: config.authFile });
    const page = await context.newPage();

    try {
        // 3. 打开页面并验证登录状态
        console.log(`>>> 正在前往: ${config.url}`);
        await page.goto(config.url);

        try {
            // 等待页面加载出关键元素（例如“历史会话”文字），超时设置为 5秒
            // 如果 5秒出不来，说明可能 Cookie 过期了，需要重新登录
            await page.waitForSelector('text=历史会话', { timeout: 5000 });
            console.log('✅ 登录状态验证通过。');
        } catch (e) {
            console.error('❌ 凭证似乎已失效或页面加载过慢。');
            console.error('   建议删除 auth.json 并重新运行 node login.js');
            await browser.close();
            return;
        }

        // ==========================================
        // 🔥 核心修复：强力处理“AI智能客服”弹窗 🔥
        // ==========================================
        try {
            console.log('   正在监测可能出现的弹窗 (耐心等待 10秒)...');
            
            // 直接定位我们要点的“放弃”按钮
            const closeBtn = page.locator('text=放弃定制售后').first();

            // ⚠️ 关键修改：使用 waitFor 而不是 isVisible
            // 这会让脚本真的暂停下来等待，直到元素出现或者超时
            await closeBtn.waitFor({ state: 'visible', timeout: 10000 });
            
            console.log('🚨 终于等到弹窗了！正在点击“放弃”...');
            
            // 强制点击，防止有透明层遮挡
            await closeBtn.click({ force: true });
            
            // 点击后，必须确认它真的消失了，否则后面点日期还是会被挡
            // 这里我们等待这个按钮从页面上消失
            await closeBtn.waitFor({ state: 'hidden', timeout: 5000 });
            console.log('✅ 弹窗已成功清除。');

        } catch (e) {
            // 如果 10秒 到了还没找到按钮，playwright 会报错跳到这里
            // 这说明确实没有弹窗，我们可以安全地继续
            console.log('   (10秒内未出现弹窗，自动跳过...)');
        }
        // ==========================================

        // 5. 日期循环任务 (过去7天)
        const daysToCheck = 7;
        
        for (let i = 0; i < daysToCheck; i++) {
            // 计算目标日期
            const targetDate = dayjs().subtract(i, 'day').format('YYYY-MM-DD');
            const filePath = path.join(config.dataDir, `${targetDate}.json`);

            // 检查本地是否已有数据
            if (fs.existsSync(filePath)) {
                console.log(`⏭️ [${targetDate}] 数据已存在，跳过。`);
                continue;
            }

            console.log(`\n>>> 正在处理日期: [${targetDate}] ...`);
            
            // 执行当天的抓取任务
            const data = await scrapeDataForDate(page, targetDate);
            
            // 保存结果
            if (data && data.length > 0) {
                fs.writeFileSync(filePath, JSON.stringify(data, null, 2));
                console.log(`💾 [${targetDate}] 保存成功，共采集 ${data.length} 个会话。`);
            } else {
                console.log(`⚠️ [${targetDate}] 未采集到数据或当天无会话。`);
            }
        }

    } catch (err) {
        console.error('❌ 主程序运行发生未捕获异常:', err);
    } finally {
        console.log('\n✅ 所有任务执行完毕，关闭浏览器。');
        await browser.close();
    }
})();


/**
 * 核心任务：抓取指定日期的所有会话
 * @param {Object} page Playwright Page对象
 * @param {String} dateStr 日期字符串 YYYY-MM-DD
 */
/**
 * 抓取指定日期 (修复日期选择逻辑)
 */
async function scrapeDataForDate(page, dateStr) {
    let allConversations = [];

    // --- 步骤 A: 精确设置日期范围 ---
    // 逻辑：为了锁定仅查询"当他"，必须把 开始日期 和 结束日期 都设为 dateStr
    try {
        // 1. 设置【开始日期】
        // 使用精确选择器，防止点偏
        const startInput = page.locator('input[placeholder="开始日期"]').first();
        await startInput.waitFor({ state: 'visible' });
        
        // 强力清空并输入
        await startInput.click({ force: true });
        await startInput.fill(dateStr); 
        await startInput.press('Enter'); // 确认开始日期
        
        await page.waitForTimeout(300);

        // 2. 设置【结束日期】 (关键修复点！！！)
        // 如果不设置这个，结束日期会停留在上一轮的日期，导致查询范围变大
        const endInput = page.locator('input[placeholder="结束日期"]').first();
        
        // 只有当结束日期输入框存在时才操作 (通常都在)
        if (await endInput.isVisible()) {
            await endInput.click({ force: true });
            await endInput.fill(dateStr);
            await endInput.press('Enter'); // 确认结束日期
        } else {
            // 如果没找到结束输入框，尝试再次在开始输入框按回车，模拟“区间闭合”
            await startInput.press('Enter');
        }

        await page.waitForTimeout(500); 

        // 3. 点击查询
        const searchBtn = page.locator(config.selectors.searchBtn);
        await searchBtn.click();
        
        // 4. 等待加载
        // 观察表格的第一行是否出现，或者 loading 消失
        // 这里简单等待 2秒，确保数据刷新
        await page.waitForTimeout(2000); 

    } catch (e) {
        console.error(`   ⚠️ 日期 [${dateStr}] 设置阶段出错:`, e.message);
        // 如果日期都没设对，接着跑也没意义，返回空数组
        return [];
    }

    // --- 步骤 B: 遍历分页 (保持不变) ---
    let pageNum = 1;
    let hasNextPage = true;

    while (hasNextPage) {
        // 重新获取按钮，防止 DOM 刷新失效
        const viewButtons = await page.locator('a:has-text("查看会话")').all();
        
        if (viewButtons.length === 0) {
            console.log(`   第 ${pageNum} 页无数据。`);
            break;
        }

        console.log(`   正在采集第 ${pageNum} 页，共 ${viewButtons.length} 条...`);

        for (let j = 0; j < viewButtons.length; j++) {
            try {
                // 重新定位行
                const rows = await page.locator('tr').filter({ hasText: '查看会话' }).all();
                if (!rows[j]) continue;

                const currentRow = rows[j];
                const btn = currentRow.locator('a:has-text("查看会话")');
                
                // 提取简略信息
                const rowText = await currentRow.innerText();
                const shortInfo = rowText.split('\n')[0].substring(0, 30);

                // 点击进入
                await btn.click();
                
                // 提取详情
                const chatHistory = await extractChatHistory(page);
                
                allConversations.push({
                    info: shortInfo,
                    date: dateStr,
                    messages: chatHistory
                });

                console.log(`     -> [${j + 1}/${viewButtons.length}] 采集完成 (${chatHistory.length}条消息)`);

                // 关闭弹窗
                const closeBtn = page.getByRole('button', { name: 'Close' })
                                     .or(page.locator('button[aria-label="Close"]'))
                                     .or(page.locator('.arco-modal-close-icon'));

                if (await closeBtn.isVisible()) {
                    await closeBtn.click();
                } else {
                    await page.keyboard.press('Escape');
                }
                await page.waitForTimeout(500);

            } catch (itemErr) {
                console.error(`     -> 第 ${j + 1} 条采集出错:`, itemErr.message);
                await page.keyboard.press('Escape');
            }
        }

        // 翻页逻辑
        const nextBtn = page.getByRole('button', { name: 'right' }); 
        if (await nextBtn.isVisible()) {
            const isDisabled = await nextBtn.getAttribute('disabled') !== null || 
                               await nextBtn.evaluate(el => el.classList.contains('disabled') || el.classList.contains('arco-pagination-disabled'));
            if (isDisabled) {
                hasNextPage = false;
            } else {
                await nextBtn.click();
                await page.waitForTimeout(2000);
                pageNum++;
            }
        } else {
            hasNextPage = false;
        }
    }

    return allConversations;
}


/**
 * 核心功能：提取聊天记录详情
 * 适配：飞鸽虚拟列表 + 向上滚动 + DOM结构解析
 */
async function extractChatHistory(page) {
    // 1. 尝试点击“切换该用户全部聊天消息”
    try {
        const switchBtn = page.getByRole('button', { name: '切换该用户全部聊天消息' });
        // 等待一下按钮出现，超时设短一点，因为可能本来就是全部
        if (await switchBtn.isVisible({ timeout: 2000 })) {
            await switchBtn.click();
            await page.waitForTimeout(1000);
        }
    } catch (e) { /* 忽略，可能已经是全部消息 */ }

    // 2. 定位滚动容器
    // 基于你提供的HTML，容器 class 是 .scroller
    const scrollContainerSelector = '.scroller';
    
    // 使用 Map 进行去重 (Key = "时间_内容")
    const collectedMap = new Map();

    try {
        await page.waitForSelector(scrollContainerSelector, { timeout: 3000 });
        
        // 3. 循环滚动抓取
        // 逻辑：每抓一次 -> 向上滚一点 -> 再抓 -> 直到滚不动
        const maxScrollAttempts = 30; // 防止死循环，最大滚30次

        for (let k = 0; k < maxScrollAttempts; k++) {
            
            // --- A. 解析当前视口内的消息 ---
            // 根据你的HTML，每一条消息包裹在 div[data-qa-id="qa-message-warpper"]
            const items = await page.$$('div[data-qa-id="qa-message-warpper"]');
            
            for (const item of items) {
                // 在浏览器上下文中执行解析，性能更高
                const msgData = await item.evaluate(el => {
                    // --- 内部逻辑开始 ---
                    // --- 内部辅助函数：清洗特殊字符 ---
                    const cleanText = (str) => {
                        if (!str) return '';
                        // 将行分隔符(\u2028)和段落分隔符(\u2029)替换为普通换行符
                        return str.replace(/[\u2028\u2029]/g, '\n').trim();
                    };
                    
                    // 1. 提取时间
                    // 匹配 HH:mm 或 HH:mm:ss
                    const timeRegex = /(\d{1,2}:\d{2}(:\d{2})?)/;
                    const allText = el.innerText || '';
                    const timeMatch = allText.match(timeRegex);
                    const timeStr = timeMatch ? timeMatch[0] : '';

                    // 2. 提取内容 & 类型
                    let content = '';
                    let type = 'text';

                    const imgEl = el.querySelector('img[alt="图片"]'); // 飞鸽图片特征
                    const preEl = el.querySelector('pre'); // 飞鸽文本特征

                    if (imgEl) {
                        content = imgEl.src;
                        type = 'image';
                    } else if (preEl) {
                        content = preEl.innerText;
                        type = 'text';
                    } else {
                        // 既不是图也不是普通文本，可能是系统提示（如：机器人接待中、关闭会话）
                        // 去除时间文本，剩下的就是系统提示
                        content = allText.replace(timeStr, '').trim();
                        type = 'system';
                    }

                    // 3. 判断发送者 (Service vs User)
                    // 依据：flex-direction: row-reverse 为己方(客服)
                    let sender = 'User'; // 默认为客户
                    const htmlStyle = el.innerHTML; // 获取内部HTML查style
                    
                    if (htmlStyle.includes('flex-direction: row-reverse') || htmlStyle.includes('flex-direction:row-reverse')) {
                        sender = 'Service';
                    }

                    // 修正系统消息的发送者
                    if (content.includes('机器人接待中') || content.includes('关闭会话') || content.includes('接入')) {
                        sender = 'System';
                    }

                    return { time: timeStr, sender, content, type };
                    // --- 内部逻辑结束 ---
                });

                // --- B. 存入 Map 去重 ---
                // 使用 (时间 + 内容) 作为唯一标识
                // 如果是图片，内容是URL，也足够唯一
                if (msgData.content) {
                    const uniqueKey = `${msgData.time}_${msgData.content}`;
                    collectedMap.set(uniqueKey, msgData);
                }
            }

            // --- C. 向上滚动逻辑 ---
            // 检查当前 scrollTop
            const scrollTop = await page.$eval(scrollContainerSelector, el => el.scrollTop);
            
            // 如果已经滚到顶 (scrollTop 为 0)，且已经尝试滚动了几次，则退出
            if (scrollTop <= 0 && k > 1) {
                // console.log('       已滚动到顶部。');
                break;
            }

            // 向上滚动 500 像素 (模拟滚轮)
            await page.$eval(scrollContainerSelector, el => {
                el.scrollTop = Math.max(0, el.scrollTop - 500);
            });
            
            // 等待 DOM 渲染新内容 (虚拟列表需要时间加载)
            await page.waitForTimeout(600);
        }

    } catch (e) {
        console.warn(`     ⚠️ 聊天记录抓取微小异常 (通常可忽略): ${e.message}`);
    }

    // 4. 将 Map 转为 数组 并排序
    const results = Array.from(collectedMap.values());
    
    // 按时间字符串简单排序 (09:00 -> 09:01)
    // 注意：如果聊天跨天，这种排序可能不准确，但在单个会话窗口中通常没问题
    results.sort((a, b) => {
        if (!a.time) return 1;
        if (!b.time) return -1;
        return a.time.localeCompare(b.time);
    });

    return results;
}