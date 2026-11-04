"""Prepare immutable offline fixtures. Production parsing never imports this tool."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from pypdf import PdfReader, PdfWriter


def prepare(source: Path, output: Path, manifest: Path) -> dict:
    source, output = source.resolve(), output.resolve()
    if source.is_relative_to(output):
        raise ValueError("样本目录必须独立于原件目录，不能覆盖或混入原资料")
    if output.exists() and any(output.iterdir()):
        raise ValueError("样本目录非空；请指定新的目录，保留已有核对记录")
    expected = json.loads(manifest.read_text(encoding="utf-8"))
    with source.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    if digest != expected["source_sha256"]:
        raise ValueError("原件摘要与固定样本清单不同，未提取任何页面")
    with PdfReader(source) as reader:
        if len(reader.pages) != expected["source_page_count"]:
            raise ValueError("原件页数与固定样本清单不同")
        output.mkdir(parents=True, exist_ok=True)
        combined = PdfWriter()
        mapping = []
        try:
            for index, sample in enumerate(expected["samples"]):
                source_index = sample["source_page"] - 1
                page = reader.pages[source_index]
                name = f"sample-{index + 1:02d}-page-{source_index + 1}.pdf"
                writer = PdfWriter()
                try:
                    writer.add_page(page)
                    writer.write(output / name)
                finally:
                    writer.close()
                combined.add_page(page)
                mapping.append(
                    {
                        "sample_index": index,
                        "source_page_index": source_index,
                        "source_page": source_index + 1,
                        "file": name,
                        "file_sha256": hashlib.sha256((output / name).read_bytes()).hexdigest(),
                        "checks": sample["checks"],
                        "review_status": "pending_manual_review",
                    }
                )
            combined.write(output / "fixed-ten-pages.pdf")
        finally:
            combined.close()
    result = {
        "schema_version": 1,
        "source_sha256": digest,
        "source_page_count": expected["source_page_count"],
        "samples": mapping,
        "bundle_file": "fixed-ten-pages.pdf",
        "bundle_sha256": hashlib.sha256((output / "fixed-ten-pages.pdf").read_bytes()).hexdigest(),
        "review_status": "pending_manual_review",
        "production_page_filter": False,
    }
    (output / "manifest.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / "核对清单.md").write_text(
        "# 固定样本人工核对清单\n\n仅固定样本，尚未核对 OCR 或数学质量。页码为原 PDF 物理页序。\n\n"
        + "\n".join(
            f"- [ ] 第 {row['source_page']} 页：{'；'.join(row['checks'])}" for row in mapping
        )
        + "\n",
        encoding="utf-8",
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--manifest", type=Path, default=Path(__file__).with_name("knowledge_sample_manifest.json")
    )
    args = parser.parse_args()
    result = prepare(args.source, args.output, args.manifest)
    print(
        json.dumps(
            {
                "samples": len(result["samples"]),
                "output": str(args.output),
                "review_status": result["review_status"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
