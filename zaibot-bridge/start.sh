#!/bin/bash
# 启动 Z.ai Bridge 服务

cd "$(dirname "$0")"

# 激活虚拟环境
source "../.venv/bin/activate"

# 安装依赖
pip install -q -r requirements.txt 2>/dev/null

# 检查 zaibot token
if [ ! -f "../zaibot/zaibot_token.txt" ] && [ ! -f "../zaibot/zaibot_state.json" ]; then
    echo "Warning: zaibot token not found. Please run 'cd ../zaibot && python3 login.py login' first."
fi

# 启动服务
# 环境变量说明:
#   ZAIBOT_HOST        - 绑定地址 (默认 127.0.0.1, 如需远程访问请改为 0.0.0.0)
#   ZAIBOT_ADMIN_KEY   - Admin API 密钥 (未设置时仅允许本机访问 /admin/*)
#   ZAIBOT_CORS_ORIGINS - CORS 允许来源 (默认 *, 多来源用逗号分隔)
echo "Starting Z.ai Bridge on port 8001..."
python3 server.py
