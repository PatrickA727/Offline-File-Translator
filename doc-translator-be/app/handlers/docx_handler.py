import zipfile
import shutil
import os
from lxml import etree
from pathlib import Path
from app.models.schemas import TextNode

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
}


def _parse_xml(path: Path) -> etree._ElementTree:
    """Parse XML preserving everything — namespaces, comments, processing instructions."""
    parser = etree.XMLParser(remove_blank_text=False, strip_cdata=False)
    return etree.parse(str(path), parser)


def _save_xml(tree: etree._ElementTree, path: Path) -> None:
    """Write XML back preserving original declaration and formatting."""
    tree.write(
        str(path),
        xml_declaration=True,
        encoding="UTF-8",
        standalone=True,
    )

TEXT_FILES = [
    "word/document.xml",       # Body, tables, text boxes, TOC
    "word/comments.xml",       # Comments
    "word/footnotes.xml",      # Footnotes
    "word/endnotes.xml",       # Endnotes
]

# Pattern for header/footer
HEADER_FOOTER_PATTERNS = [
    "word/header*.xml",
    "word/footer*.xml",
]


class DocxHandler:
    """
    Extract translatable text from .docx files and write translations back
    while preserving as much formatting as possible.
    """

    def __init__(self, file_path: str):
        self.file_path = Path(file_path)
        self.work_dir = self.file_path.parent / f"{self.file_path.stem}_work"

        os.makedirs(self.work_dir, exist_ok=True)
        with zipfile.ZipFile(self.file_path, "r") as zf:
            zf.extractall(self.work_dir)

    def _get_text_files(self) -> list[Path]:
        files: list[Path] = []

        for rel_path in TEXT_FILES:
            full_path = self.work_dir / rel_path
            if full_path.exists():
                files.append(full_path)

        word_dir = self.work_dir / "word"
        if word_dir.exists():
            for pattern in HEADER_FOOTER_PATTERNS:
                glob_pattern = Path(pattern).name
                for match in sorted(word_dir.glob(glob_pattern)):
                    if match not in files:
                        files.append(match)

        return files

    def extract_nodes(self) -> list[TextNode]:
        nodes: list[TextNode] = []
        node_id = 0

        for xml_file in self._get_text_files():
            tree = _parse_xml(xml_file)
            root = tree.getroot()

            for t_idx, t_elem in enumerate(root.findall(".//w:t", NS)):
                if t_elem.text and t_elem.text.strip():
                    rel_path = str(xml_file.relative_to(self.work_dir))
                    nodes.append(TextNode(
                        id=node_id,
                        text=t_elem.text,
                        location={
                            "type": "word_text",
                            "file": rel_path,
                            "text_idx": t_idx,
                        },
                    ))
                    node_id += 1

        doc_path = self.work_dir / "word" / "document.xml"
        if doc_path.exists():
            tree = _parse_xml(doc_path)
            root = tree.getroot()
            for t_idx, t_elem in enumerate(root.findall(".//a:t", NS)):
                if t_elem.text and t_elem.text.strip():
                    nodes.append(TextNode(
                        id=node_id,
                        text=t_elem.text,
                        location={
                            "type": "drawing_text",
                            "file": "word/document.xml",
                            "text_idx": t_idx,
                        },
                    ))
                    node_id += 1

        return nodes

    def apply_translations(self, translations: dict[int, str]) -> None:
        """Write translated text back into the XML files."""
        nodes = self.extract_nodes()

        word_nodes_by_file: dict[str, list[TextNode]] = {}
        drawing_nodes_by_file: dict[str, list[TextNode]] = {}

        for node in nodes:
            if node.id not in translations:
                continue
            if node.location["type"] == "word_text":
                word_nodes_by_file.setdefault(node.location["file"], []).append(node)
            elif node.location["type"] == "drawing_text":
                drawing_nodes_by_file.setdefault(node.location["file"], []).append(node)

        for rel_path, file_nodes in word_nodes_by_file.items():
            xml_path = self.work_dir / rel_path
            tree = _parse_xml(xml_path)
            root = tree.getroot()
            all_t = root.findall(".//w:t", NS)

            for node in file_nodes:
                t_elem = all_t[node.location["text_idx"]]
                t_elem.text = translations[node.id]
                t_elem.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")

            _save_xml(tree, xml_path)

        for rel_path, file_nodes in drawing_nodes_by_file.items():
            xml_path = self.work_dir / rel_path
            tree = _parse_xml(xml_path)
            root = tree.getroot()
            all_t = root.findall(".//a:t", NS)

            for node in file_nodes:
                t_elem = all_t[node.location["text_idx"]]
                t_elem.text = translations[node.id]

            _save_xml(tree, xml_path)

    def save(self, output_path: str) -> None:
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root_dir, dirs, files in os.walk(self.work_dir):
                for file in files:
                    file_path = Path(root_dir) / file
                    arcname = file_path.relative_to(self.work_dir)
                    zf.write(file_path, arcname)

        shutil.rmtree(self.work_dir, ignore_errors=True)