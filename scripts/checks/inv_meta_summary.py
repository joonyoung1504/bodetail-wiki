"""INV-META-SUMMARY: .md 파일 frontmatter에 summary 필드가 없으면 경고(비차단)."""
import _common as c


def check(entries):
    warnings = []
    for status, old, new in entries:
        if status.startswith("D"):
            continue
        target = new or old
        if not target.endswith(".md"):
            continue
        content = c.get_staged_content(target)
        if content is None:
            continue
        if not c.has_summary_field(content):
            warnings.append(target)
    return warnings
