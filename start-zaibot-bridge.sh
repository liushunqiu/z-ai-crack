#!/bin/bash
# 一键启动 zaibot-bridge 并配置 Codex CLI

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BRIDGE_DIR="$SCRIPT_DIR/zaibot-bridge"
VENV_DIR="$SCRIPT_DIR/.venv"
CODEX_CONFIG="$HOME/.codex/config.toml"

echo "=== Z.ai Bridge 启动器 ==="

# 1. 检查 zaibot token
echo "[1/4] 检查 Z.ai 登录状态..."
if [ ! -f "$SCRIPT_DIR/zaibot/zaibot_token.txt" ] && [ ! -f "$SCRIPT_DIR/zaibot/zaibot_state.json" ]; then
    echo "❌ 未找到 Z.ai 登录信息"
    echo "   请先运行: cd $SCRIPT_DIR/zaibot && python3 login.py login"
    exit 1
fi
echo "✅ Z.ai 登录信息存在"

# 2. 激活虚拟环境并安装依赖
echo "[2/4] 检查依赖..."
source "$VENV_DIR/bin/activate"
cd "$BRIDGE_DIR"
pip install -q -r requirements.txt 2>/dev/null
echo "✅ 依赖已就绪"

# 3. 备份并更新 Codex 配置
echo "[3/4] 配置 Codex CLI..."
if [ -f "$CODEX_CONFIG" ]; then
    cp "$CODEX_CONFIG" "$CODEX_CONFIG.bak"
    echo "   已备份原配置到 $CODEX_CONFIG.bak"
fi

cat > "$CODEX_CONFIG" << 'EOF'
model_provider = "custom"
model = "GLM-5.1"
disable_response_storage = true
model_reasoning_effort = "medium"

[model_providers]
[model_providers.custom]
name = "custom"
wire_api = "responses"
requires_openai_auth = true
base_url = "http://localhost:8001/v1"

[projects]
[updates]
check = false
EOF
echo "✅ Codex CLI 配置已更新"

# 4. 启动服务
echo "[4/4] 启动 zaibot-bridge..."
echo ""
echo "=========================================="
echo "  Z.ai Bridge 即将启动在端口 8001"
echo "  Codex CLI 已配置为使用 Z.ai"
echo "=========================================="
echo ""
echo "使用方式:"
echo "  codex              # 交互模式"
echo "  codex '你的提示'   # 单次执行"
echo ""
echo "按 Ctrl+C 停止服务"
echo ""

python3 server.py
