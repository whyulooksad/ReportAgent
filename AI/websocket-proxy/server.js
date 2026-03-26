const WebSocket = require('ws');
const express = require('express');
const axios = require('axios');
const config = require('./config');
const OpenAI = require('openai');

const app = express();
const server = app.listen(config.websocket.port, config.websocket.host, () => {
    console.log(`WebSocket服务器运行在 ws://${config.websocket.host}:${config.websocket.port}`);
});
// 以接入deepseekapi为例
const openai = new OpenAI({
        baseURL: 'https://api.deepseek.com',
        apiKey: '<填写自己的apikey>'
});

const wss = new WebSocket.Server({ server });

// 处理WebSocket连接
wss.on('connection', (ws) => {
    console.log('客户端已连接');
    
    // 处理来自客户端的消息
    ws.on('message', async (message) => {
        try {
            console.log('收到客户端消息:', message.toString().substring(0, 100) + '...');
            
            // 解析客户端消息（这里假设是JSON格式的请求）
            let request;
            try {
                request = JSON.parse(message);
            } catch (e) {
                // 如果不是JSON，直接作为文本处理
                request = { 
                    prompt: message.toString(),
                    model: "deepseek-chat" // 默认模型
                };
            }
            
            // 调用大模型API
            const response = await callLLMAPI(request);
            
            // 发送响应回客户端
            ws.send(response);
            
        } catch (error) {
            console.error('处理消息时出错:', error);
            ws.send(JSON.stringify({
                error: true,
                message: error.message || '处理请求时发生错误'
            }));
        }
    });
    
    // 处理连接关闭
    ws.on('close', () => {
        console.log('客户端已断开连接');
    });
    
    // 处理错误
    ws.on('error', (error) => {
        console.error('WebSocket错误:', error);
    });
});

// 调用大模型API的函数
async function callLLMAPI(request) {
    try {
        // 这里以deepseek为例
        
        const completion = await openai.chat.completions.create({
            messages: [
                { 
                    role: "system", 
                    content: request.prompt || request.messages?.[0]?.content || '' 
                }
            ],
            model: "deepseek-chat",
        });
        
        // 提取并格式化响应
        const reply = completion.choices[0].message.content;
        console.log(reply)
        
        return reply
        // JSON.stringify({
        //     response: reply
        // });
        
    } catch (error) {
        console.error('调用大模型API失败:', error.response ? error.response.data : error.message);
        
        let errorMessage = '大模型服务暂时不可用';
        if (error.response) {
            errorMessage = error.response.data?.error?.message || error.response.statusText;
        } else if (error.request) {
            errorMessage = '无法连接到大模型服务';
        }
        
        return JSON.stringify({
            success: false,
            error: errorMessage,
            details: error.message
        });
    }
}
