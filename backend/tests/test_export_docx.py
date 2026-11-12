"""Word 导出边界：认证、下载契约、公式及答案解析的可见性与顺序。"""

from io import BytesIO
from urllib.parse import unquote
from xml.etree import ElementTree
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
}


def _payload() -> dict[str, object]:
    return {
        "title": "中文函数练习卷",
        "type_order": ["compute"],
        "questions": [
            {
                "type": "compute",
                "stem": "求函数 $x^2$ 的导数，并计算：$$\n\\frac{1}{2}\n$$",
                "answer": "导数结果为 $2x$",
                "analysis": "使用幂函数求导法则",
            },
            {
                "type": "compute",
                "stem": "第二题：计算常数的导数",
                "answer": "常数导数为零",
                "analysis": "根据导数定义计算",
            },
        ],
    }


def _document(content: bytes) -> ElementTree.Element:
    with ZipFile(BytesIO(content)) as archive:
        assert archive.testzip() is None
        assert "[Content_Types].xml" in archive.namelist()
        return ElementTree.fromstring(archive.read("word/document.xml"))


def _paragraphs(document: ElementTree.Element) -> list[str]:
    return [
        "".join(paragraph.itertext())
        for paragraph in document.findall("w:body/w:p", NS)
    ]


def test_docx_export_requires_login(client: TestClient) -> None:
    """合法请求体也不能绕过登录校验取得文件。"""
    response = client.post("/api/export/docx", json=_payload())

    assert response.status_code == 401
    assert "content-disposition" not in response.headers


def test_docx_download_preserves_chinese_and_editable_math(
    client: TestClient, teacher: dict[str, str],
) -> None:
    """以真实下载结果检查中文文件名、缓存约束及可编辑的原生公式。"""
    response = client.post("/api/export/docx", json=_payload(), headers=teacher)

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert response.headers["cache-control"] == "no-store"
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment; filename*=UTF-8''")
    assert unquote(disposition.split("UTF-8''", 1)[1]) == "中文函数练习卷.docx"

    document = _document(response.content)
    text = "\n".join(_paragraphs(document))
    assert "中文函数练习卷" in text
    assert "求函数" in text
    assert "第二题：计算常数的导数" in text
    assert "$" not in text
    assert "\\frac" not in text
    superscript = document.find(".//m:oMath//m:sSup", NS)
    assert superscript is not None
    assert superscript.findtext("m:e//m:t", namespaces=NS) == "x"
    assert superscript.findtext("m:sup//m:t", namespaces=NS) == "2"
    fraction = document.find(".//m:oMath//m:f", NS)
    assert fraction is not None
    assert fraction.findtext("m:num//m:t", namespaces=NS) == "1"
    assert fraction.findtext("m:den//m:t", namespaces=NS) == "2"


@pytest.mark.parametrize("include_answer,include_analysis", [
    (True, False), (False, True), (False, False),
])
def test_docx_answer_and_analysis_can_be_hidden_independently(
    client: TestClient, teacher: dict[str, str],
    include_answer: bool, include_analysis: bool,
) -> None:
    """关闭答案或解析时，对应内容不能泄漏进交付的文档。"""
    body = _payload()
    body.update(include_answer=include_answer, include_analysis=include_analysis)
    response = client.post("/api/export/docx", json=body, headers=teacher)

    assert response.status_code == 200, response.text
    text = "\n".join(_paragraphs(_document(response.content)))
    assert ("导数结果为" in text) is include_answer
    assert ("常数导数为零" in text) is include_answer
    assert ("答案：" in text) is include_answer
    assert ("使用幂函数求导法则" in text) is include_analysis
    assert ("根据导数定义计算" in text) is include_analysis
    assert ("解析：" in text) is include_analysis
    assert "第二题：计算常数的导数" in text


def test_docx_end_placement_keeps_all_questions_before_solutions(
    client: TestClient, teacher: dict[str, str],
) -> None:
    """文末集中模式须先列完题目，再按题号列出答案与解析。"""
    body = _payload()
    body["placement"] = "end"
    response = client.post("/api/export/docx", json=body, headers=teacher)

    assert response.status_code == 200, response.text
    paragraphs = _paragraphs(_document(response.content))
    second_question = paragraphs.index("2. 第二题：计算常数的导数")
    answer_heading = paragraphs.index("参考答案")
    first_answer = next(i for i, text in enumerate(paragraphs) if "导数结果为" in text)
    second_answer = paragraphs.index("2. 常数导数为零")
    analysis_heading = paragraphs.index("解析")
    first_analysis = paragraphs.index("1. 使用幂函数求导法则")
    second_analysis = paragraphs.index("2. 根据导数定义计算")
    assert second_question < answer_heading < first_answer < second_answer
    assert second_answer < analysis_heading < first_analysis < second_analysis
