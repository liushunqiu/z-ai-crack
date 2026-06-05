#!/usr/bin/env python3
"""
网络诊断工具 - 检测 chat.z.ai 的连接状态
用于诊断登录超时和网络问题
"""
import sys
import time
import urllib.request
import urllib.error

def check_dns():
    """检查 DNS 解析"""
    print("[1] 检查 DNS 解析...")
    try:
        import socket
        ip = socket.gethostbyname("chat.z.ai")
        print(f"    ✓ chat.z.ai 解析到: {ip}")
        return True
    except Exception as e:
        print(f"    ✗ DNS 解析失败: {e}")
        return False

def check_tcp():
    """检查 TCP 连接"""
    print("[2] 检查 TCP 连接...")
    import socket
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        result = sock.connect_ex(("chat.z.ai", 443))
        sock.close()
        if result == 0:
            print("    ✓ TCP 连接成功 (443 端口)")
            return True
        else:
            print(f"    ✗ TCP 连接失败: 错误码 {result}")
            return False
    except Exception as e:
        print(f"    ✗ TCP 连接异常: {e}")
        return False

def check_https():
    """检查 HTTPS 连接"""
    print("[3] 检查 HTTPS 连接...")
    try:
        req = urllib.request.Request(
            "https://chat.z.ai/",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        start_time = time.time()
        with urllib.request.urlopen(req, timeout=30) as resp:
            elapsed = time.time() - start_time
            status = resp.status
            print(f"    ✓ HTTPS 连接成功: 状态码 {status}, 耗时 {elapsed:.2f}s")
            return True
    except urllib.error.HTTPError as e:
        print(f"    ⚠ HTTP 错误: {e.code} {e.reason}")
        return True  # 能连接上，只是返回错误
    except urllib.error.URLError as e:
        print(f"    ✗ 连接失败: {e.reason}")
        return False
    except Exception as e:
        print(f"    ✗ 连接异常: {e}")
        return False

def check_api():
    """检查 API 连接"""
    print("[4] 检查 API 连接...")
    try:
        req = urllib.request.Request(
            "https://chat.z.ai/api/v1/auths/",
            headers={"Accept": "application/json"},
        )
        start_time = time.time()
        with urllib.request.urlopen(req, timeout=30) as resp:
            elapsed = time.time() - start_time
            print(f"    ✓ API 连接成功: 耗时 {elapsed:.2f}s")
            return True
    except urllib.error.HTTPError as e:
        print(f"    ⚠ API 错误: {e.code} {e.reason}")
        return True  # 能连接上，只是返回错误
    except urllib.error.URLError as e:
        print(f"    ✗ API 连接失败: {e.reason}")
        return False
    except Exception as e:
        print(f"    ✗ API 连接异常: {e}")
        return False

def check_latency():
    """检查延迟"""
    print("[5] 检查延迟...")
    results = []
    for i in range(3):
        try:
            req = urllib.request.Request(
                "https://chat.z.ai/",
                headers={"User-Agent": "Mozilla/5.0"},
            )
            start_time = time.time()
            with urllib.request.urlopen(req, timeout=30) as resp:
                elapsed = time.time() - start_time
                results.append(elapsed)
        except Exception:
            pass

    if results:
        avg_latency = sum(results) / len(results)
        min_latency = min(results)
        max_latency = max(results)
        print(f"    ✓ 平均延迟: {avg_latency:.2f}s (最小: {min_latency:.2f}s, 最大: {max_latency:.2f}s)")

        if avg_latency > 10:
            print("    ⚠ 延迟较高，可能导致登录超时")
        return True
    else:
        print("    ✗ 无法测试延迟")
        return False

def main():
    print("=" * 50)
    print("  chat.z.ai 网络诊断工具")
    print("=" * 50)
    print()

    results = []
    results.append(("DNS 解析", check_dns()))
    results.append(("TCP 连接", check_tcp()))
    results.append(("HTTPS 连接", check_https()))
    results.append(("API 连接", check_api()))
    results.append(("延迟测试", check_latency()))

    print()
    print("=" * 50)
    print("  诊断结果")
    print("=" * 50)

    all_ok = True
    for name, ok in results:
        status = "✓ 正常" if ok else "✗ 异常"
        print(f"  {name}: {status}")
        if not ok:
            all_ok = False

    print()
    if all_ok:
        print("  ✓ 网络连接正常，可以尝试登录")
    else:
        print("  ✗ 网络连接异常，建议：")
        print("    1. 检查网络连接")
        print("    2. 尝试使用 VPN 或代理")
        print("    3. 稍后重试")

    print()
    return 0 if all_ok else 1

if __name__ == "__main__":
    sys.exit(main())
