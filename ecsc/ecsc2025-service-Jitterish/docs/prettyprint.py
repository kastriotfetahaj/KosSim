import re
from pathlib import Path

CSS = """
.collection {
    color: #77f;
}
"""


class PrettyPrinter:
    def run(self, text: str) -> str:
        text = self.mark_constants(text)
        text = self.mark_idents(text)
        text = self.mark_keywords(text)
        text = self.mark_comments(text)
        text = self.mark_ops(text)
        return self.to_doc(text)

    def mark_idents(self, text: str) -> str:
        text = re.sub(r'\b(query|func)\s+(\w+)\b', r'\1 <span class="ident">\2</span>', text)
        return re.sub(r'\b(on)\s+(\w+)\b', r'\1 <span class="collection">\2</span>', text)

    def mark_keywords(self, text: str) -> str :
        return re.sub(r'\b(query|on|filter|map|reduce|limit|return|if|while|func)\b', r'<span class="keyword">\1</span>', text)

    def mark_comments(self, text: str) -> str:
        return re.sub(r'(//.*)[\n$]', '<span class="comment">\\1</span>\n', text)

    def mark_constants(self, text: str) -> str:
        text = re.sub(r'("[\w\s\.]+")', r'<span class="constant">\1</span>', text)
        text = re.sub(r'\b(true|false|null|\d+|undefined)\b', r'<span class="constant">\1</span>', text)
        return text

    def mark_ops(self, text: str) -> str:
        text = re.sub(r'\b(len|defined)\b', r'<span class="op">\1</span>', text)
        return text

    def to_doc(self, text: str) -> str:
        return '<html><head><style>'+CSS+'</style></head><body><pre>' + text + '</pre></body></html>'


def main() -> None:
    text = Path('script.qry').read_text()
    html = PrettyPrinter().run(text)
    Path('script.html').write_text(html)


if __name__ == '__main__':
    main()
