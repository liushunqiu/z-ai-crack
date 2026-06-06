#!/bin/bash
# 启动 Z.ai Bridge 服务

cd "$(dirname "$0")"

# 加载 .env 配置文件
if [ -f .env ]; then
    set -a
    source .env
    set +a
    echo "[config] 已加载 .env"
else
    echo "[config] 未找到 .env，使用默认配置"
    echo "[config] 提示: cp .env.example .env 创建配置文件"
fi

# 激活虚拟环境
source "../.venv/bin/activate"

# 安装依赖
pip install -q -r requirements.txt 2>/dev/null

# 检查 zaibot token
if [ ! -f "../zaibot/zaibot_token.txt" ] && [ ! -f "../zaibot/zaibot_state.json" ]; then
    echo "[warn] zaibot token not found. Run 'cd ../zaibot && python3 login.py login' first."
fi

# 显示当前配置
echo "============================================"
echo " Z.ai Bridge"
echo "============================================"
echo " Host:     ${ZAIBOT_HOST:-127.0.0.1}:8001"
echo " Path:     $([ "$ZAIBOT_USE_PURE_HTTP" = "1" ] && echo 'Pure HTTP (urllib)' || echo 'DOM Fetch (Camoufox)')"
echo " Proxy:    ${ZAIBOT_PROXY:-无}"
echo " HMAC:     $([ -n "$ZAIBOT_HMAC_SECRET" ] && echo '已配置' || echo 'captured fallback')"
echo " Admin:    http://${ZAIBOT_HOST:-127.0.0.1}:8001/admin"
echo "============================================"

python3 server.py
