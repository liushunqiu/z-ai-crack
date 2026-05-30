#!/usr/bin/env python3
"""Z.ai pure-HTTP-first API client.

Goal:
  - 手动登录只做一次：python3 login.py login
  - 后续优先直接走 HTTP API。
  - X-Signature / captcha 都通过可替换接口提供，不再硬编码在业务逻辑里。

Usage:
  python3 zaibot_api.py "你的问题"
  python3 zaibot_api.py --no-browser "hello"       # 绝不打开浏览器，缺 captcha/signature 就直接报错
  python3 zaibot_api.py --allow-stale-signature "hello"
  python3 zaibot_api.py                              # interactive

Signature sources, priority:
  1. ZAIBOT_HMAC_SECRET env -> local formula
  2. zaibot_signature_cache.json (<=5 min by default)
  3. captured_request.json latest request (fallback / stale mode)

Captcha sources:
  1. zaibot_captcha_cache.json (<=4 min)
  2. if server says captcha is required and browser is allowed, call get_captcha.py logic
"""
from __future__ import annotations

import argparse
import sys
import subprocess
import time

from zaibot_core import (
    ChatSession,
    ZaibotAPIError,
    ZaibotError,
    ZaibotHTTPError,
    classify_error,
    is_retriable_error,
    load_captcha_cache,
    post_chat,
)


def _try_protocol_captcha() -> str | None:
    """Try the no-browser captcha minting path.

    Current protocol module has fully reproduced Aliyun OpenAPI signing and
    InitCaptchaV3. It will return a token only after FeiLin deviceToken is also
    reproduced; until then we fall back to Chrome unless --no-browser is set.
    """
    try:
        proc = subprocess.run(
            ["node", "captcha_protocol.js", "mint"],
            cwd=str(__import__("pathlib").Path(__file__).parent),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=45,
        )
        if proc.returncode == 0:
            raw = proc.stdout.strip().splitlines()[-1].strip()
            if raw and not raw.startswith("{"):
                return raw
        if proc.stderr:
            print(f"[*] 纯协议验证码暂不可用: {proc.stderr.strip().splitlines()[-1]}", file=sys.stderr)
    except FileNotFoundError:
        print("[*] 未找到 node，跳过纯协议验证码尝试", file=sys.stderr)
    except Exception as e:
        print(f"[*] 纯协议验证码尝试失败: {e}", file=sys.stderr)
    return None


def _get_fresh_captcha_or_raise(no_browser: bool, captcha_session=None) -> str:
    captcha = _try_protocol_captcha()
    if captcha:
        return captcha
    if no_browser:
        raise ZaibotError(
            "服务端需要 captcha_verify_param，但 --no-browser 禁止打开浏览器。\n"
            "已完成 Aliyun OpenAPI 纯协议签名与 InitCaptchaV3；剩余 FeiLin deviceToken "
            "仍需继续还原，所以当前 --no-browser 无法自动生成最终 securityToken。"
        )

    # Persistent session: retry up to 3 times, don't fall through to one-shot
    # browser (launching a second Camoufox conflicts with the existing one).
    if captcha_session:
        for attempt in range(3):
            print(f"[*] 使用持久浏览器获取 captcha (attempt {attempt + 1}/3)...", file=sys.stderr)
            try:
                return captcha_session.get_captcha()
            except Exception as sess_err:
                print(f"[!] 持久浏览器获取失败: {sess_err}", file=sys.stderr)
                if attempt < 2:
                    time.sleep(2)
        raise ZaibotError("持久浏览器获取 captcha 失败，已重试 3 次")

    # No persistent session: launch one-shot Camoufox
    print("[*] 启动 Camoufox 获取 captcha_verify_param...", file=sys.stderr)
    try:
        from captcha_service import get_captcha_verify_param
        captcha = get_captcha_verify_param()
    except Exception as svc_err:
        print(f"[!] Camoufox 验证码失败: {svc_err}", file=sys.stderr)
        try:
            from auto_captcha import get_auto_captcha
            captcha = get_auto_captcha()
        except Exception as auto_err:
            print(f"[!] 自动验证码失败: {auto_err}", file=sys.stderr)
            from get_captcha import get_captcha
            captcha = get_captcha()
    if not captcha:
        raise ZaibotError("获取 captcha_verify_param 失败")
    return captcha


def ask(prompt: str, *, model: str = "GLM-5.1", stream: bool = True, no_browser: bool = False, allow_stale_signature: bool = False, with_captcha: bool = False, captcha_session=None, chat_session: ChatSession | None = None, max_retries: int = 2) -> str:
    """Send a prompt to the API.

    Args:
        captcha_session: Optional CaptchaSession for persistent browser reuse.
        chat_session: Optional ChatSession for conversation continuity.
        max_retries: Max retry attempts for retriable errors (default 2).
    """
    captcha = None

    last_error = None
    for attempt in range(max_retries + 1):
        try:
            return post_chat(
                prompt,
                model=model,
                stream=stream,
                captcha_verify_param=captcha,
                allow_stale_signature=allow_stale_signature,
                echo=stream,
                session=chat_session,
            )
        except (ZaibotHTTPError, ZaibotAPIError) as e:
            kind = e.kind if isinstance(e, ZaibotAPIError) else classify_error(e.status, e.body)
            last_error = e
            # Print actual error details for debugging
            if isinstance(e, ZaibotHTTPError):
                print(f"[!] API 失败 (attempt {attempt + 1}/{max_retries + 1}): HTTP {e.status} {kind}", file=sys.stderr)
                print(f"[!] Response: {e.body[:500]}", file=sys.stderr)
            else:
                print(f"[!] API 失败 (attempt {attempt + 1}/{max_retries + 1}): {kind}", file=sys.stderr)
                print(f"[!] Response: {e.body[:500]}", file=sys.stderr)

            # Signature errors are never retriable — need manual fix
            if "X-Signature" in kind or "签名" in kind:
                raise ZaibotError(
                    "X-Signature 已失效或参数不匹配。处理方式：\n"
                    "  1) 运行 python3 capture_signature.py 捕获新签名；或\n"
                    "  2) 设置 ZAIBOT_HMAC_SECRET 后走本地签名；或\n"
                    "  3) 临时加 --allow-stale-signature 使用 captured_request.json 最新样本。"
                ) from e

            # Token/login errors are not retriable
            if "token" in kind or "login" in kind:
                raise ZaibotError("登录态已失效，请运行 python3 login.py login 重新登录") from e

            # For retriable errors, get fresh captcha and retry
            if is_retriable_error(kind):
                # Captcha errors: keep chat_id for continuity
                # Other retriable errors: reset chat_id
                if "captcha" not in kind and "验证码" not in kind:
                    if chat_session:
                        chat_session.chat_id = None

                try:
                    captcha = _get_fresh_captcha_or_raise(no_browser, captcha_session=captcha_session)
                except Exception as captcha_err:
                    print(f"[!] 获取新 captcha 失败: {captcha_err}", file=sys.stderr)
                    if attempt < max_retries:
                        continue
                    raise

                if attempt < max_retries:
                    print(f"[*] 重试中...", file=sys.stderr)
                    continue

            # Non-retriable or exhausted retries
            raise ZaibotError(f"请求失败: {kind}") from last_error

    raise ZaibotError(f"请求失败，已重试 {max_retries} 次") from last_error


def interactive(args: argparse.Namespace) -> None:
    from captcha_service import CaptchaSession

    print("Z.ai API interactive. Ctrl-D/Ctrl-C 退出。", file=sys.stderr)

    headless = not args.no_headless
    captcha_sess = None
    if not args.no_browser:
        try:
            captcha_sess = CaptchaSession(headless=headless)
            captcha_sess.start()
        except Exception as e:
            print(f"[!] 持久浏览器启动失败，回退到按需启动: {e}", file=sys.stderr)
            captcha_sess = None

    # Chat session for conversation continuity
    chat_sess = ChatSession(model=args.model)
    print(f"[*] 会话模式: 所有消息在同一个聊天中", file=sys.stderr)

    try:
        while True:
            try:
                prompt = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print(file=sys.stderr)
                return
            if not prompt:
                continue
            try:
                ask(
                    prompt,
                    model=args.model,
                    stream=not args.no_stream,
                    no_browser=args.no_browser,
                    allow_stale_signature=args.allow_stale_signature,
                    with_captcha=args.with_captcha,
                    captcha_session=captcha_sess,
                    chat_session=chat_sess,
                )
            except Exception as e:
                print(f"[x] {e}", file=sys.stderr)
    finally:
        if captcha_sess:
            print("[*] 关闭持久浏览器...", file=sys.stderr)
            captcha_sess.close()


def _single_shot(prompt: str, args: argparse.Namespace) -> int:
    """Single-prompt mode: use persistent session to keep browser alive during API call."""
    from captcha_service import CaptchaSession

    headless = not args.no_headless
    captcha_sess = None
    if not args.no_browser:
        try:
            captcha_sess = CaptchaSession(headless=headless)
            captcha_sess.start()
        except Exception as e:
            print(f"[!] 持久浏览器启动失败: {e}", file=sys.stderr)
            captcha_sess = None

    # Create chat session if --chat-id is provided
    chat_sess = None
    if args.chat_id:
        chat_sess = ChatSession(model=args.model)
        chat_sess.chat_id = args.chat_id

    try:
        ask(
            prompt,
            model=args.model,
            stream=not args.no_stream,
            no_browser=args.no_browser,
            allow_stale_signature=args.allow_stale_signature,
            with_captcha=args.with_captcha,
            captcha_session=captcha_sess,
            chat_session=chat_sess,
        )
        return 0
    except Exception as e:
        print(f"[x] {e}", file=sys.stderr)
        return 1
    finally:
        if captcha_sess:
            captcha_sess.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="Z.ai HTTP API client")
    ap.add_argument("prompt", nargs="*", help="prompt text")
    ap.add_argument("--model", default="GLM-5.1")
    ap.add_argument("--no-stream", action="store_true", help="request non-stream response")
    ap.add_argument("--no-browser", action="store_true", help="never open browser for captcha fallback")
    ap.add_argument("--no-headless", action="store_true", help="run browser in visible mode (more stable captcha)")
    ap.add_argument("--with-captcha", action="store_true", help="include cached captcha on first attempt if available")
    ap.add_argument("--allow-stale-signature", action="store_true", help="allow stale captured_request signature fallback")
    ap.add_argument("--chat-id", default=None, help="continue an existing chat by ID")
    args = ap.parse_args()

    prompt = " ".join(args.prompt).strip()
    if not prompt:
        interactive(args)
        return 0

    print(f"[*] {prompt}", file=sys.stderr)
    if args.chat_id:
        print(f"[*] 继续会话: {args.chat_id}", file=sys.stderr)
    return _single_shot(prompt, args)


if __name__ == "__main__":
    raise SystemExit(main())
