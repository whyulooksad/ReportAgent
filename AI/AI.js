let websocket = null;
let isConnected = false;

// DOM元素
const questionBox = document.getElementById('questionBox');
const responseBox = document.getElementById('responseBox');
const connectBtn = document.getElementById('connectBtn');
const disconnectBtn = document.getElementById('disconnectBtn');
const sendBtn = document.getElementById('sendBtn');
const connectionStatus = document.getElementById('connectionStatus');
const wsUrlInput = document.getElementById('wsUrl');
const loading = document.getElementById('loading');

// 更新连接状态显示
function updateConnectionStatus(status, message) {
    connectionStatus.className = `connection-status status-${status}`;
    connectionStatus.textContent = message;
    
    switch(status) {
        case 'connected':
            isConnected = true;
            connectBtn.disabled = true;
            disconnectBtn.disabled = false;
            sendBtn.disabled = false;
            wsUrlInput.disabled = true;
            break;
        case 'disconnected':
            isConnected = false;
            connectBtn.disabled = false;
            disconnectBtn.disabled = true;
            sendBtn.disabled = true;
            wsUrlInput.disabled = false;
            loading.classList.remove('show');
            break;
        case 'connecting':
            isConnected = false;
            connectBtn.disabled = true;
            disconnectBtn.disabled = true;
            sendBtn.disabled = true;
            wsUrlInput.disabled = true;
            break;
    }
}

// 连接WebSocket
function connectWebSocket() {
    const wsUrl = wsUrlInput.value.trim();
    
    if (!wsUrl) {
        alert('请输入WebSocket服务器地址');
        return;
    }

    updateConnectionStatus('connecting', '正在连接WebSocket服务器...');

    try {
        websocket = new WebSocket(wsUrl);

        websocket.onopen = function(event) {
            console.log('WebSocket连接已建立');
            updateConnectionStatus('connected', '✅ 已连接到WebSocket服务器');
            
            // 显示连接成功的提示
            responseBox.value = '✅ WebSocket连接成功！\n\n现在可以输入问题并发送给大模型了。\n\n提示：\n• 请确保大模型服务正常运行\n• 输入您的问题后点击"发送问题"按钮\n• 等待大模型处理并返回结果';
        };

        websocket.onmessage = function(event) {
            console.log('收到消息:', event.data);
            loading.classList.remove('show');
            
            // 将接收到的消息追加到响应框
            if (responseBox.value === '✅ WebSocket连接成功！\n\n现在可以输入问题并发送给大模型了。\n\n提示：\n• 请确保大模型服务正常运行\n• 输入您的问题后点击"发送问题"按钮\n• 等待大模型处理并返回结果') {
                responseBox.value = ''; // 清除初始提示
            }
            
            const timestamp = new Date().toLocaleTimeString();
            responseBox.value += `\n\n🤖 [${timestamp}] 大模型回复：\n${event.data}`;
            console.log(event.data)
            // 自动滚动到底部
            responseBox.scrollTop = responseBox.scrollHeight;
        };

        websocket.onclose = function(event) {
            console.log('WebSocket连接已关闭', event);
            updateConnectionStatus('disconnected', '❌ WebSocket连接已断开');
            
            if (event.wasClean) {
                responseBox.value += '\n\n📡 连接已正常关闭';
            } else {
                responseBox.value += '\n\n📡 连接异常断开，可能原因：服务器关闭、网络问题等';
            }
        };

        websocket.onerror = function(error) {
            console.error('WebSocket错误:', error);
            updateConnectionStatus('disconnected', '❌ WebSocket连接错误');
            loading.classList.remove('show');
            
            responseBox.value += '\n\n⚠️ 连接发生错误，请检查：\n• WebSocket服务器是否运行\n• 地址是否正确\n• 网络连接是否正常';
        };

    } catch (error) {
        console.error('连接失败:', error);
        updateConnectionStatus('disconnected', '❌ 连接失败：' + error.message);
        alert('连接失败：' + error.message);
    }
}

// 断开WebSocket连接
function disconnectWebSocket() {
    if (websocket) {
        websocket.close();
        websocket = null;
    }
    updateConnectionStatus('disconnected', '❌ 已断开WebSocket连接');
}

// 发送消息
function sendMessage() {
    if (!isConnected) {
        alert('请先连接WebSocket服务器');
        return;
    }

    const message = questionBox.value.trim();
    if (!message) {
        alert('请输入要发送的问题');
        return;
    }

    try {
        console.log('发送消息:', message);
        websocket.send(message);
        
        // 显示发送的消息
        if (responseBox.value === '' || responseBox.value.includes('WebSocket连接成功')) {
            responseBox.value = '';
        }
        
        const timestamp = new Date().toLocaleTimeString();
        responseBox.value += `\n\n👤 [${timestamp}] 您的问题：\n${message}`;
        
        // 清空输入框
        questionBox.value = '';
        
        // 显示加载状态
        loading.classList.add('show');
        
        // 自动滚动到底部
        responseBox.scrollTop = responseBox.scrollHeight;
        
    } catch (error) {
        console.error('发送消息失败:', error);
        alert('发送消息失败：' + error.message);
        loading.classList.remove('show');
    }
}

// 清空问题
function clearQuestion() {
    questionBox.value = '';
    questionBox.focus();
}

// 清空回复
function clearResponse() {
    if (confirm('确定要清空大模型的回复吗？')) {
        responseBox.value = '';
    }
}

// 监听回车键发送消息
questionBox.addEventListener('keydown', function(event) {
    if (event.ctrlKey && event.key === 'Enter') {
        sendMessage();
    }
});

// 页面加载完成后聚焦到问题输入框
window.addEventListener('load', function() {
    questionBox.focus();
});

// WebSocket URL输入框回车连接
wsUrlInput.addEventListener('keydown', function(event) {
    if (event.key === 'Enter') {
        connectWebSocket();
    }
});