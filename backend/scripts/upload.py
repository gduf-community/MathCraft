"""命令行入库：uv run python scripts/upload.py <文件路径> [--kb kb-math]"""
import sys
from argparse import ArgumentParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from services.ingestion import ingest_file  # noqa: E402


def main():
    ap = ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--kb", default="kb-math")
    args = ap.parse_args()
    path = Path(args.file)
    if not path.exists():
        sys.exit(f"文件不存在：{path}")
    result = ingest_file(args.kb, path, doc_name=path.name)
    print(f"入库完成：{result}")


if __name__ == "__main__":
    main()
