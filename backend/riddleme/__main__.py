"""python -m riddleme 启动出题智能体服务（默认 127.0.0.1:8000）。"""
import argparse

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="RiddleMe 出题智能体服务")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="开发模式热重载")
    args = parser.parse_args()
    uvicorn.run("riddleme.main:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
