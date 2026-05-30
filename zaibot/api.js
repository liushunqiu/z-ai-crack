#!/usr/bin/env node
/**
 * Z.ai API 客户端
 * 读取 zaibot_token.txt 然后用 Bearer Token 调 API
 *
 * 用法:
 *   node api.js "你好，请介绍一下你自己"
 */
const fs = require("fs");
const path = require("path");

const TOKEN_FILE = path.join(__dirname, "zaibot_token.txt");

async function main() {
  if (!fs.existsSync(TOKEN_FILE)) {
    console.error("[x] 未找到 token 文件，请先运行 python3 login.py 登录");
    process.exit(1);
  }

  const token = fs.readFileSync(TOKEN_FILE, "utf-8").trim();
  const prompt = process.argv[2] || "你好，请简单介绍一下自己";

  const res = await fetch("https://chat.z.ai/api/chat/completions", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model: "glm-5.1",
      messages: [{ role: "user", content: prompt }],
      stream: false,
    }),
  });

  const data = await res.json();
  const reply = data?.choices?.[0]?.message?.content;
  console.log(reply || JSON.stringify(data, null, 2));
}

main().catch(console.error);
