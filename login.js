// login.js - 人工确认版
// 运行命令: node login.js
const { chromium } = require('playwright');
const config = require('./config');
const readline = require('readline');

(async () => {
    // 1. 创建终端交互接口
    const rl = readline.createInterface({
        input: process.stdin,
        output: process.stdout
    });

    console.log('>>> [1/3] 正在启动浏览器...');
    const browser = await chromium.launch({ headless: false });
    const context = await browser.newContext();
    const page = await context.newPage();

    console.log(`>>> [2/3] 正在打开网址: ${config.url}`);
    try {
        await page.goto(config.url);
    } catch (e) {
        console.log('   (页面加载可能超时，但不影响登录，继续执行...)');
    }

    // --- 人工介入环节 ---
    console.log('\n======================================================');
    console.log('🟢 步骤 1: 请在弹出的浏览器中，手动完成所有登录操作。');
    console.log('🟢 步骤 2: 确认你能看到历史会话的数据列表。');
    console.log('🟢 步骤 3: 回到这里，按下【回车键 (Enter)】确认保存凭证。');
    console.log('======================================================\n');

    // 2. 挂起脚本，等待用户按下回车键
    await new Promise((resolve) => {
        rl.question('>>> 确认已登录成功？请按回车键继续...', (answer) => {
            resolve(answer);
            rl.close(); // 关闭输入流
        });
    });

    console.log('\n>>> [3/3] 收到确认指令，正在保存凭证...');

    try {
        // 3. 保存 Cookie 和 LocalStorage
        await context.storageState({ path: config.authFile });
        
        console.log(`✅ 凭证已强制保存至: ${config.authFile}`);
        console.log('🎉 登录流程结束。你可以关闭浏览器，去运行 node main.js 了。');

    } catch (e) {
        console.error('❌ 保存凭证失败:', e);
    } finally {
        // 稍微等待一下再关闭
        await page.waitForTimeout(1000);
        await browser.close();
        process.exit(0);
    }
})();