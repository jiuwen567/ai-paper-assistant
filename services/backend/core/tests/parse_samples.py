"""公开可重建的自制测试文件，不包含真实论文。"""

import io
import zipfile

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


def pdf_sample(blank=False):
    writer = PdfWriter()
    for text in ["Self-authored introduction", "Self-authored result"]:
        page = writer.add_blank_page(width=300, height=300)
        if not blank:
            font = DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type1"),
                    NameObject("/BaseFont"): NameObject("/Helvetica"),
                }
            )
            page[NameObject("/Resources")] = DictionaryObject(
                {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
            )
            stream = DecodedStreamObject()
            stream.set_data(f"BT /F1 12 Tf 20 220 Td ({text}) Tj ET".encode())
            page[NameObject("/Contents")] = stream
    writer.set_page_label(0, 1, style="/r")
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def docx_sample():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-'
            'officedocument.wordprocessingml.document.main+xml"/></Types>',
        )
        archive.writestr(
            "_rels/.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Target="word/document.xml" Type="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships/officeDocument"/></Relationships>',
        )
        archive.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body><w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'
            "<w:r><w:t>自制标题</w:t></w:r></w:p><w:p/>"
            "<w:p><w:r><w:t>自制正文</w:t></w:r><w:r><w:tab/><w:t>尾部</w:t></w:r></w:p>"
            "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>表格内容</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
            "</w:body></w:document>",
        )
    return output.getvalue()


CSV_SAMPLE = (
    b'experiment,metric,value,unit,conditions\ntrial,accuracy,0.9,ratio,"line one\nline two"\n'
)
