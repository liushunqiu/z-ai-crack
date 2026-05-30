#!/bin/bash
# 恢复 Codex CLI 原始配置

CODEX_CONFIG="$HOME/.codex/config.toml"
BACKUP="$CODEX_CONFIG.bak"

if [ -f "$BACKUP" ]; then
    cp "$BACKUP" "$CODEX_CONFIG"
    echo "✅ 已恢复 Codex CLI 原始配置"
    echo "   从: $BACKUP"
else
    echo "❌ 未找到备份文件: $BACKUP"
fi
