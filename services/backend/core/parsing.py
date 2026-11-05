"""确定性的文字提取；锚点始终指向不可变原件，不推断 Word 页码。"""

import csv
import io
import re
import time
import zipfile
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from importlib.metadata import version
from pathlib import PurePath

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException
from pypdf import PdfReader
from pypdf.errors import PdfReadError

PARSER_VERSION = f"text-v1/pypdf-{version('pypdf')}/xml-{version('defusedxml')}"
CSV_FIELDS = ["experiment", "metric", "value", "unit", "conditions"]
CHUNK_SIZE = 4000
MAX_TEXT = 1_000_000
WORD = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class ParseFailure(Exception):
    def __init__(self, code, message, retryable=False):
        self.code, self.message, self.retryable = code, message, retryable
        super().__init__(code)


class ParsingStopped(Exception):
    pass


@dataclass
class ParsedDocument:
    chunks: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    coverage: str = "text"
    characters: int = 0

    def add(self, text, anchor, heading_level=0):
        if not text.strip():
            return
        self.characters += len(text)
        if self.characters > MAX_TEXT or len(self.chunks) >= 10000:
            raise ParseFailure("text_limit", "提取文字超过处理上限，请拆分材料。")
        for start in range(0, len(text), CHUNK_SIZE):
            if len(self.chunks) >= 10000:
                raise ParseFailure("text_limit", "提取片段超过处理上限，请拆分材料。")
            self.chunks.append(
                {
                    "ordinal": len(self.chunks) + 1,
                    "text": text[start : start + CHUNK_SIZE],
                    "anchor": {**anchor, "start": start, "end": min(start + CHUNK_SIZE, len(text))},
                    "heading_level": heading_level,
                }
            )


def paragraph_text_nodes(node):
    if node.tag in [f"{WORD}drawing", f"{WORD}pict", f"{WORD}del"]:
        return
    yield node
    for child in node:
        yield from paragraph_text_nodes(child)


def parse_document(data, name, checkpoint=lambda progress: True):
    result = ParsedDocument()

    last_check = 0.0

    def check(progress):
        nonlocal last_check
        now = time.monotonic()
        if progress not in (5, 90) and now - last_check < 1:
            return
        if not checkpoint(progress):
            raise ParsingStopped()
        last_check = now

    suffix = PurePath(name).suffix.lower()
    try:
        check(5)
        if suffix == ".pdf":
            reader = PdfReader(io.BytesIO(data), strict=True)
            if reader.is_encrypted:
                raise ParseFailure("encrypted_pdf", "不支持加密 PDF。")
            labels = reader.page_labels
            blank = []
            for index, page in enumerate(reader.pages):
                check(10 + int(75 * index / max(1, len(reader.pages))))
                content = page.get_contents()
                if content and len(content.get_data()) > 2 * 1024 * 1024:
                    raise ParseFailure("pdf_page_limit", "PDF 单页内容过大，请拆分或简化文件。")
                text = page.extract_text() or ""
                if not text.strip():
                    blank.append(index + 1)
                result.add(text, {"kind": "pdf", "page": index + 1, "page_label": labels[index]})
            if blank:
                result.coverage = "partial"
                result.warnings.append(
                    f"有 {len(blank)} 页未提取到文字，可能为空白页或扫描页；未执行 OCR。"
                )
            result.warnings.append("按 PDF 文件页序定位；页码标签不保证等于纸面印刷页码。")
        elif suffix == ".docx":
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if archive.getinfo("word/document.xml").file_size > 10 * 1024 * 1024:
                    raise ParseFailure("docx_limit", "DOCX 正文结构过大，请拆分材料。")
                root = ElementTree.fromstring(archive.read("word/document.xml"))
                body = root.find(f"{WORD}body")
                if body is None:
                    raise ParseFailure("docx_body_missing", "DOCX 未包含正文。")
                styles = {}
                if "word/styles.xml" in archive.namelist():
                    if archive.getinfo("word/styles.xml").file_size > 2 * 1024 * 1024:
                        raise ParseFailure("docx_limit", "DOCX 样式结构过大。")
                    for style in ElementTree.fromstring(archive.read("word/styles.xml")):
                        style_name = style.find(f"{WORD}name")
                        if style_name is not None:
                            styles[style.get(f"{WORD}styleId")] = style_name.get(f"{WORD}val", "")
                paragraphs = body.findall(f"{WORD}p")
                for index, paragraph in enumerate(paragraphs):
                    check(10 + int(75 * index / max(1, len(paragraphs))))
                    parts = []
                    for element in paragraph_text_nodes(paragraph):
                        if element.tag == f"{WORD}t":
                            parts.append(element.text or "")
                        elif element.tag == f"{WORD}tab":
                            parts.append("\t")
                        elif element.tag in [f"{WORD}br", f"{WORD}cr"]:
                            parts.append("\n")
                    style = paragraph.find(f"{WORD}pPr/{WORD}pStyle")
                    style_id = style.get(f"{WORD}val", "") if style is not None else ""
                    heading = re.fullmatch(
                        r"(?:heading|标题)\s*([1-9])", styles.get(style_id, style_id), re.I
                    )
                    result.add(
                        "".join(parts),
                        {"kind": "docx", "paragraph": index + 1},
                        int(heading.group(1)) if heading else 0,
                    )
                if (
                    any(child.tag not in [f"{WORD}p", f"{WORD}sectPr"] for child in body)
                    or root.findall(f".//{WORD}drawing")
                    or any("officeDocument/2006/math" in node.tag for node in root.iter())
                ):
                    result.coverage = "partial"
                    result.warnings.append(
                        "仅提取正文顶层段落与标题；表格、图片、公式及嵌套结构需查看原件。"
                    )
        elif suffix == ".csv":
            reader = csv.reader(io.StringIO(data.decode("utf-8-sig")), strict=True)
            header = next(reader)
            if header != CSV_FIELDS:
                raise ParseFailure(
                    "csv_schema", "CSV 列须依次为 experiment,metric,value,unit,conditions。"
                )
            line_start = reader.line_num + 1
            for index, row in enumerate(reader):
                check(min(85, 10 + index // 100))
                if len(row) != len(CSV_FIELDS) or any(len(value) > 2000 for value in row):
                    raise ParseFailure("csv_row", f"CSV 第 {index + 1} 条记录字段数量或长度不符。")
                fields = dict(zip(CSV_FIELDS, row, strict=True))
                if not fields["experiment"].strip() or not fields["metric"].strip():
                    raise ParseFailure("csv_row", f"CSV 第 {index + 1} 条记录缺少实验或指标名称。")
                try:
                    if len(fields["value"]) > 256 or not Decimal(fields["value"]).is_finite():
                        raise InvalidOperation
                except InvalidOperation:
                    raise ParseFailure(
                        "csv_value", f"CSV 第 {index + 1} 条记录的 value 必须为有限数值。"
                    ) from None
                result.add(
                    "\n".join(f"{key}: {value}" for key, value in fields.items()),
                    {
                        "kind": "csv",
                        "record": index + 1,
                        "line_start": line_start,
                        "line_end": reader.line_num,
                        "fields": fields,
                    },
                )
                line_start = reader.line_num + 1
        elif suffix == ".txt":
            lines = data.decode("utf-8-sig").splitlines()
            for index, text in enumerate(lines):
                check(10 + int(75 * index / max(1, len(lines))))
                result.add(text, {"kind": "txt", "line": index + 1})
        else:
            raise ParseFailure("unsupported_format", "文件格式不受支持。")
        if not result.chunks:
            raise ParseFailure(
                "no_text", "未提取到可用文字；扫描件需先提供文字版，当前不支持 OCR。"
            )
        check(90)
        return result
    except (ParseFailure, ParsingStopped):
        raise
    except (
        ValueError,
        KeyError,
        TypeError,
        IndexError,
        zipfile.BadZipFile,
        ElementTree.ParseError,
        DefusedXmlException,
        PdfReadError,
        csv.Error,
        StopIteration,
    ):
        raise ParseFailure("invalid_document", "原件结构无法解析，请检查文件后重新上传。") from None
