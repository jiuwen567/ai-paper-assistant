import io
import zipfile
from datetime import UTC

from docx import Document
from docx.enum.section import WD_SECTION_START
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor

from core.common.errors import ParseFailure
from core.exports.templates import LayoutInput
from core.materials.files import MAX_FILE_SIZE


class ExportStopped(Exception):
    pass


def field(paragraph, instruction, cached):
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    begin.set(qn("w:dirty"), "true")
    paragraph.add_run()._r.append(begin)
    code = OxmlElement("w:instrText")
    code.set(qn("xml:space"), "preserve")
    code.text = " " + instruction + " "
    paragraph.add_run()._r.append(code)
    separator = OxmlElement("w:fldChar")
    separator.set(qn("w:fldCharType"), "separate")
    paragraph.add_run()._r.append(separator)
    paragraph.add_run(str(cached))
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    paragraph.add_run()._r.append(end)


def font(style, latin, chinese, size, bold=False):
    style.font.name = latin
    style.font.size = Pt(size)
    style.font.bold = bold
    style.font.color.rgb = RGBColor(0, 0, 0)
    fonts = style.element.get_or_add_rPr().get_or_add_rFonts()
    for attribute in ("asciiTheme", "hAnsiTheme", "eastAsiaTheme", "cstheme"):
        fonts.attrib.pop(qn("w:" + attribute), None)
    fonts.set(qn("w:eastAsia"), chinese)


def setup(document, layout):
    normal = document.styles["Normal"]
    font(normal, layout["latin_font"], layout["body_font"], layout["body_size_pt"])
    normal.paragraph_format.line_spacing = layout["line_spacing"]
    normal.paragraph_format.first_line_indent = Pt(
        layout["body_size_pt"] * layout["first_line_chars"]
    )
    normal.paragraph_format.space_after = Pt(0)
    normal.paragraph_format.widow_control = True
    title = document.styles["Title"]
    font(title, layout["latin_font"], layout["heading_font"], layout["title_size_pt"], True)
    title.paragraph_format.first_line_indent = Pt(0)
    for level in range(1, 10):
        style = document.styles[f"Heading {level}"]
        font(
            style,
            layout["latin_font"],
            layout["heading_font"],
            layout["heading_sizes_pt"][level - 1],
            True,
        )
        style.paragraph_format.first_line_indent = Pt(0)
        style.paragraph_format.keep_with_next = True
        style.paragraph_format.space_before = Pt(12)
        style.paragraph_format.space_after = Pt(6)
    caption = document.styles["Caption"]
    font(caption, layout["latin_font"], layout["body_font"], layout["caption_size_pt"])
    caption.font.italic = False
    caption.paragraph_format.first_line_indent = Pt(0)
    for name in ["Header", "Footer"]:
        style = document.styles[name]
        font(style, layout["latin_font"], layout["body_font"], layout["header_size_pt"])
        style.paragraph_format.first_line_indent = Pt(0)
    for section in document.sections:
        section.page_width, section.page_height = (
            Mm(layout["page_width_mm"]),
            Mm(layout["page_height_mm"]),
        )
        section.top_margin, section.bottom_margin = (
            Mm(layout["margin_top_mm"]),
            Mm(layout["margin_bottom_mm"]),
        )
        section.left_margin, section.right_margin = (
            Mm(layout["margin_left_mm"]),
            Mm(layout["margin_right_mm"]),
        )
        section.header_distance = section.footer_distance = Mm(12)
    update = OxmlElement("w:updateFields")
    update.set(qn("w:val"), "true")
    document.settings.element.append(update)


def bookmark(paragraph, number):
    start = OxmlElement("w:bookmarkStart")
    start.set(qn("w:id"), str(number))
    start.set(qn("w:name"), f"paper_reference_{number}")
    paragraph._p.append(start)
    end = OxmlElement("w:bookmarkEnd")
    end.set(qn("w:id"), str(number))
    paragraph._p.append(end)


def reference_link(paragraph, number):
    link = OxmlElement("w:hyperlink")
    link.set(qn("w:anchor"), f"paper_reference_{number}")
    run = OxmlElement("w:r")
    props = OxmlElement("w:rPr")
    superscript = OxmlElement("w:vertAlign")
    superscript.set(qn("w:val"), "superscript")
    props.append(superscript)
    run.append(props)
    text = OxmlElement("w:t")
    text.text = f"[{number}]"
    run.append(text)
    link.append(run)
    paragraph._p.append(link)


def render_word(content, created_at, checkpoint=lambda progress: True):
    serializer = LayoutInput(data=content["template"]["layout"])
    if not serializer.is_valid():
        raise ParseFailure("export_template_invalid", "快照中的模板规则无效，不能生成文件。")
    layout = serializer.validated_data
    document = Document()
    setup(document, layout)
    props = document.core_properties
    props.title = content["title"]
    props.author = content["author"]
    props.last_modified_by = ""
    props.created = props.modified = created_at.astimezone(UTC).replace(tzinfo=None)
    props.subject = (
        f"稿件 v{content['manuscript_version']} · 模板 {content['template']['code']} "
        f"v{content['template']['number']}"
    )
    props.comments = ""
    paragraph = document.add_paragraph(content["title"], style="Title")
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if content["author"]:
        paragraph = document.add_paragraph(content["author"])
        paragraph.paragraph_format.first_line_indent = Pt(0)
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    document.add_page_break()
    paragraph = document.add_paragraph("目录", style="Title")
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph = document.add_paragraph()
    paragraph.paragraph_format.first_line_indent = Pt(0)
    field(
        paragraph, f'TOC \\o "1-{layout["toc_levels"]}" \\h \\z \\u', "请在 Word 中更新整个目录。"
    )
    section = document.add_section(WD_SECTION_START.NEW_PAGE)
    section.header.is_linked_to_previous = False
    section.footer.is_linked_to_previous = False
    section.header.paragraphs[0].text = layout["header_text"].replace("{title}", content["title"])
    section.header.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    field(footer, "PAGE", 1)
    page_number = OxmlElement("w:pgNumType")
    page_number.set(qn("w:start"), "1")
    section._sectPr.append(page_number)
    for index, block in enumerate(content["blocks"]):
        if index % 20 == 0 and not checkpoint(
            10 + int(55 * index / max(1, len(content["blocks"])))
        ):
            raise ExportStopped()
        caption = block["caption"]
        if caption:
            paragraph = document.add_paragraph(style="Caption")
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            label, sequence = ("图", "Figure") if caption["kind"] == "figure" else ("表", "Table")
            paragraph.add_run(label + " ")
            field(paragraph, f"SEQ {sequence} \\* ARABIC", caption["number"])
            paragraph.add_run(" " + block["text"])
            paragraph.paragraph_format.keep_with_next = caption["kind"] == "table"
        else:
            paragraph = document.add_paragraph(
                block["text"],
                style=f"Heading {block['heading_level']}" if block["heading_level"] else "Normal",
            )
            if not block["heading_level"]:
                paragraph.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        for number in dict.fromkeys(c["number"] for c in block["references"]):
            reference_link(paragraph, number)
    if content["references"]:
        document.add_heading("参考文献", level=1)
        for reference in content["references"]:
            paragraph = document.add_paragraph()
            paragraph.paragraph_format.first_line_indent = Pt(0)
            bookmark(paragraph, reference["number"])
            paragraph.add_run(f"[{reference['number']}] {reference['text']}")
    document.add_heading("AI 使用说明", level=1)
    # 作者核实的正文保留空行和显式换行，不让模型代写说明。
    document.add_paragraph(content["disclosure"]["text"])
    external = content["disclosure"]["external_uses"]
    if external:
        document.add_heading("作者补充的系统外使用", level=2)
        labels = {
            "tool": "工具",
            "purpose": "用途",
            "scope": "范围",
            "used_at": "时间",
            "note": "说明",
        }
        for item in external:
            document.add_paragraph(
                "；".join(f"{label}：{item[key]}" for key, label in labels.items() if item.get(key))
            )
    buffer = io.BytesIO()
    document.save(buffer)
    # ZIP 默认写入当前时间。统一为快照时间，重试生成相同字节和摘要。
    result = io.BytesIO()
    stamp = created_at.astimezone(UTC)
    date_time = (
        max(1980, stamp.year),
        stamp.month,
        stamp.day,
        stamp.hour,
        stamp.minute,
        stamp.second // 2 * 2,
    )
    with (
        zipfile.ZipFile(buffer) as source,
        zipfile.ZipFile(result, "w", compression=zipfile.ZIP_DEFLATED) as target,
    ):
        for name in sorted(source.namelist()):
            info = zipfile.ZipInfo(name, date_time)
            info.compress_type = zipfile.ZIP_DEFLATED
            target.writestr(info, source.read(name))
    data = result.getvalue()
    if len(data) > MAX_FILE_SIZE:
        raise ParseFailure("export_size_limit", "导出文件超过 20 MB，请缩小交付范围。")
    return data
