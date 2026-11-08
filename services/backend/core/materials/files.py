import csv
import io
import zipfile
from pathlib import PurePath

from defusedxml import ElementTree
from pypdf import PdfReader
from rest_framework.exceptions import ValidationError

MAX_FILE_SIZE = 20 * 1024 * 1024


MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".csv": "text/csv",
    ".txt": "text/plain",
}


def media_type(name):
    if not name or any(c in name for c in "/\\") or any(ord(c) < 32 for c in name):
        raise ValidationError("文件名不能包含路径或控制字符。")
    result = MEDIA_TYPES.get(PurePath(name).suffix.lower())
    if result is None:
        raise ValidationError("仅支持 PDF、DOCX、UTF-8 CSV 和 TXT。")
    return result


def validate_file(data, name):
    if not data or len(data) > MAX_FILE_SIZE:
        raise ValidationError("文件不能为空且不能超过 20 MB。")
    suffix = PurePath(name).suffix.lower()
    media_type(name)
    try:
        if suffix == ".pdf":
            if not data.startswith(b"%PDF-"):
                raise ValueError
            reader = PdfReader(io.BytesIO(data), strict=True)
            if reader.is_encrypted or not 0 < len(reader.pages) <= 2000:
                raise ValueError
        elif suffix == ".docx":
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                entries = archive.infolist()
                if (
                    len(entries) > 5000
                    or sum(item.file_size for item in entries) > 100 * 1024 * 1024
                ):
                    raise ValueError
                if archive.testzip() is not None or "[Content_Types].xml" not in archive.namelist():
                    raise ValueError
                content_types = ElementTree.fromstring(archive.read("[Content_Types].xml"))
                if not any(
                    item.attrib.get("PartName") == "/word/document.xml"
                    and item.attrib.get("ContentType")
                    == (
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
                    )
                    for item in content_types
                ):
                    raise ValueError
                relationships = ElementTree.fromstring(archive.read("_rels/.rels"))
                if not any(
                    item.attrib.get("Target") in ["word/document.xml", "/word/document.xml"]
                    and item.attrib.get("Type", "").endswith("/officeDocument")
                    and item.attrib.get("TargetMode", "Internal") == "Internal"
                    for item in relationships
                ):
                    raise ValueError
                root = ElementTree.fromstring(archive.read("word/document.xml"))
                if (
                    root.tag
                    != "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}document"
                ):
                    raise ValueError
        else:
            text = data.decode("utf-8-sig")
            if "\0" in text:
                raise ValueError
            if suffix == ".csv":
                rows = csv.reader(io.StringIO(text), strict=True)
                header = next(rows)
                if not header or any(not item.strip() for item in header):
                    raise ValueError
                for count, row in enumerate(rows):
                    if len(row) != len(header) or count >= 100000:
                        raise ValueError
    except Exception:
        raise ValidationError("文件损坏、类型不符、内容超限或格式不受支持。") from None
