"""真实链路冒烟：登录 → 建库 → 上传并入库（bge-m3）→ 混合检索 + 重排。

需要后端已在 127.0.0.1:8000 运行、Redis 已启动。
用法：uv run python scripts/smoke_live.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

BASE = "http://127.0.0.1:8000"
DOC = """# 导数与微分

## 导数的定义

函数 $f(x)$ 在点 $x_0$ 处的导数定义为差商的极限，刻画函数在该点的瞬时变化率。

## 求导法则

幂函数求导法则：$(x^n)' = n x^{n-1}$。乘积法则与商法则用于复合结构求导。

## 隐函数求导

方程两边同时对 $x$ 求导，再解出 $y'$，这是隐函数求导的基本方法。

## 导数应用

导数可用于判断单调性、求极值与最值，也可用于近似计算。
"""


def main() -> None:
    c = httpx.Client(base_url=BASE, timeout=120.0)

    login = c.post("/api/auth/login", json={"account": "teacher", "password": "123123", "role": "teacher"})
    login.raise_for_status()
    headers = {"Authorization": f"Bearer {login.json()['token']}"}
    print("登录成功:", login.json()["user"]["display_name"])

    bank = c.post("/api/banks", json={"name": "冒烟测试题库"}, headers=headers)
    bank.raise_for_status()
    bank_id = bank.json()["id"]
    print("建库成功:", bank.json()["code"], bank_id)

    up = c.post(
        f"/api/banks/{bank_id}/documents",
        files={"file": ("derivative.md", DOC.encode("utf-8"), "text/markdown")},
        headers=headers,
    )
    up.raise_for_status()
    doc_id = up.json()["document_id"]
    print("上传成功:", doc_id)

    for _ in range(30):
        status = c.get(f"/api/banks/{bank_id}/documents/{doc_id}", headers=headers).json()
        print("入库状态:", status["status"], status["stage"], f'{status["progress"]}%')
        if status["status"] in ("ready", "failed"):
            break
        time.sleep(2)
    if status["status"] != "ready":
        raise SystemExit(f"入库失败: {status.get('error_message')}")

    search = c.post(
        f"/api/banks/{bank_id}/search",
        json={"query": "隐函数求导", "mode": "hybrid_rerank", "top_k": 3},
        headers=headers,
    )
    search.raise_for_status()
    data = search.json()
    print("稠密命中:", len(data["dense"]), "稀疏命中:", len(data["sparse"]), "重排结果:", len(data["reranked"]))
    for hit in data["reranked"]:
        print(f"  score={hit.get('score', 0):.4f} {hit['text'][:60]}...")

    # DeepSeek 密钥未配置时应明确拒绝生成
    gen = c.post(
        "/api/generate/start",
        json={
            "bank_id": bank_id,
            "document_id": doc_id,
            "types": [{"type": "single", "count": 2}],
            "difficulty": "中",
            "scope": "隐函数求导",
            "source_mode": "variant_data",
            "existing_stems": [],
        },
        headers=headers,
    )
    if gen.status_code == 400 and gen.json()["detail"]["code"] == "DEEPSEEK_KEY_MISSING":
        print("出题前置校验正确: 未配置 DeepSeek 密钥返回 DEEPSEEK_KEY_MISSING")
    else:
        print("出题接口返回:", gen.status_code, gen.text[:200])

    cleanup = c.delete(f"/api/banks/{bank_id}", headers=headers)
    print("清理测试题库:", cleanup.status_code)


if __name__ == "__main__":
    main()
