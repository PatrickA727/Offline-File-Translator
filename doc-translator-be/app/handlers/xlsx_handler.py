import zipfile
import shutil
import os
from lxml import etree
from pathlib import Path
from app.models.schemas import TextNode

NS = {
    "ss": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "xdr": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
}


def _parse_xml(path: Path) -> etree._ElementTree:
    parser = etree.XMLParser(remove_blank_text=False, strip_cdata=False)
    return etree.parse(str(path), parser)


def _save_xml(tree: etree._ElementTree, path: Path) -> None:
    tree.write(
        str(path),
        xml_declaration=True,
        encoding="UTF-8",
        standalone=True,
    )


class XlsxHandler:
    """
    Extract translatable text from .xlsx files and write translations back
    while preserving most formatting.
    """

    def __init__(self, file_path: str):
        self.file_path = Path(file_path)
        self.work_dir = self.file_path.parent / f"{self.file_path.stem}_work"

        # Unzip the xlsx into a working directory
        os.makedirs(self.work_dir, exist_ok=True)
        with zipfile.ZipFile(self.file_path, "r") as zf:
            zf.extractall(self.work_dir)

    def extract_nodes(self) -> list[TextNode]:
        nodes: list[TextNode] = []
        node_id = 0

        sst_path = self.work_dir / "xl" / "sharedStrings.xml"
        if sst_path.exists():
            tree = _parse_xml(sst_path)
            root = tree.getroot()
            for si_idx, si in enumerate(root.findall("ss:si", NS)):
                t_elem = si.find("ss:t", NS)
                if t_elem is not None and t_elem.text and t_elem.text.strip():
                    nodes.append(TextNode(
                        id=node_id,
                        text=t_elem.text,
                        location={
                            "type": "shared_string",
                            "index": si_idx,
                            "sub_type": "simple",
                        },
                    ))
                    node_id += 1
                else:
                    for r_idx, r_elem in enumerate(si.findall("ss:r", NS)):
                        rt = r_elem.find("ss:t", NS)
                        if rt is not None and rt.text and rt.text.strip():
                            nodes.append(TextNode(
                                id=node_id,
                                text=rt.text,
                                location={
                                    "type": "shared_string",
                                    "index": si_idx,
                                    "sub_type": "rich",
                                    "run_idx": r_idx,
                                },
                            ))
                            node_id += 1

        sheets_dir = self.work_dir / "xl" / "worksheets"
        if sheets_dir.exists():
            for sheet_file in sorted(sheets_dir.glob("sheet*.xml")):
                tree = _parse_xml(sheet_file)
                root = tree.getroot()
                for row in root.findall(".//ss:row", NS):
                    for cell in row.findall("ss:c", NS):
                        if cell.get("t") == "inlineStr":
                            is_elem = cell.find("ss:is", NS)
                            if is_elem is not None:
                                t_elem = is_elem.find("ss:t", NS)
                                if t_elem is not None and t_elem.text and t_elem.text.strip():
                                    nodes.append(TextNode(
                                        id=node_id,
                                        text=t_elem.text,
                                        location={
                                            "type": "inline_string",
                                            "sheet_file": sheet_file.name,
                                            "cell_ref": cell.get("r", ""),
                                        },
                                    ))
                                    node_id += 1

        wb_path = self.work_dir / "xl" / "workbook.xml"
        if wb_path.exists():
            tree = _parse_xml(wb_path)
            root = tree.getroot()
            for sheet_idx, sheet in enumerate(root.findall(".//ss:sheet", NS)):
                name = sheet.get("name", "")
                if name and name.strip():
                    nodes.append(TextNode(
                        id=node_id,
                        text=name,
                        location={
                            "type": "sheet_name",
                            "sheet_idx": sheet_idx,
                        },
                    ))
                    node_id += 1

        drawings_dir = self.work_dir / "xl" / "drawings"
        if drawings_dir.exists():
            for drawing_file in sorted(drawings_dir.glob("*.xml")):
                tree = _parse_xml(drawing_file)
                root = tree.getroot()
                for t_idx, t_elem in enumerate(root.findall(".//a:t", NS)):
                    if t_elem.text and t_elem.text.strip():
                        nodes.append(TextNode(
                            id=node_id,
                            text=t_elem.text,
                            location={
                                "type": "drawing_text",
                                "drawing_file": drawing_file.name,
                                "text_idx": t_idx,
                            },
                        ))
                        node_id += 1

        xl_dir = self.work_dir / "xl"
        for comment_file in sorted(xl_dir.glob("comments*.xml")):
            tree = _parse_xml(comment_file)
            root = tree.getroot()
            for t_idx, t_elem in enumerate(root.findall(".//ss:t", NS)):
                if t_elem.text and t_elem.text.strip():
                    nodes.append(TextNode(
                        id=node_id,
                        text=t_elem.text,
                        location={
                            "type": "comment_text",
                            "comment_file": comment_file.name,
                            "text_idx": t_idx,
                        },
                    ))
                    node_id += 1

        return nodes

    def apply_translations(self, translations: dict[int, str]) -> None:
        nodes = self.extract_nodes()

        sst_path = self.work_dir / "xl" / "sharedStrings.xml"
        sst_nodes = [n for n in nodes if n.id in translations and n.location["type"] == "shared_string"]
        if sst_nodes and sst_path.exists():
            tree = _parse_xml(sst_path)
            root = tree.getroot()
            si_elements = root.findall("ss:si", NS)

            for node in sst_nodes:
                loc = node.location
                si = si_elements[loc["index"]]

                if loc["sub_type"] == "simple":
                    t_elem = si.find("ss:t", NS)
                    if t_elem is not None:
                        t_elem.text = translations[node.id]
                elif loc["sub_type"] == "rich":
                    r_elements = si.findall("ss:r", NS)
                    rt = r_elements[loc["run_idx"]].find("ss:t", NS)
                    if rt is not None:
                        rt.text = translations[node.id]

            _save_xml(tree, sst_path)

        inline_nodes = [n for n in nodes if n.id in translations and n.location["type"] == "inline_string"]
        sheets_by_file: dict[str, list[TextNode]] = {}
        for node in inline_nodes:
            fname = node.location["sheet_file"]
            sheets_by_file.setdefault(fname, []).append(node)

        sheets_dir = self.work_dir / "xl" / "worksheets"
        for sheet_filename, sheet_nodes in sheets_by_file.items():
            sheet_path = sheets_dir / sheet_filename
            tree = _parse_xml(sheet_path)
            root = tree.getroot()

            cell_translations = {n.location["cell_ref"]: translations[n.id] for n in sheet_nodes}

            for row in root.findall(".//ss:row", NS):
                for cell in row.findall("ss:c", NS):
                    ref = cell.get("r", "")
                    if ref in cell_translations:
                        is_elem = cell.find("ss:is", NS)
                        if is_elem is not None:
                            t_elem = is_elem.find("ss:t", NS)
                            if t_elem is not None:
                                t_elem.text = cell_translations[ref]

            _save_xml(tree, sheet_path)

        sheet_name_nodes = [n for n in nodes if n.id in translations and n.location["type"] == "sheet_name"]
        if sheet_name_nodes:
            wb_path = self.work_dir / "xl" / "workbook.xml"
            tree = _parse_xml(wb_path)
            root = tree.getroot()
            sheet_elements = root.findall(".//ss:sheet", NS)

            for node in sheet_name_nodes:
                sheet_elements[node.location["sheet_idx"]].set("name", translations[node.id])

            _save_xml(tree, wb_path)

        drawing_nodes = [n for n in nodes if n.id in translations and n.location["type"] == "drawing_text"]
        drawings_by_file: dict[str, list[TextNode]] = {}
        for node in drawing_nodes:
            fname = node.location["drawing_file"]
            drawings_by_file.setdefault(fname, []).append(node)

        drawings_dir = self.work_dir / "xl" / "drawings"
        for drawing_filename, d_nodes in drawings_by_file.items():
            drawing_path = drawings_dir / drawing_filename
            tree = _parse_xml(drawing_path)
            root = tree.getroot()
            all_t = root.findall(".//a:t", NS)

            for node in d_nodes:
                t_elem = all_t[node.location["text_idx"]]
                t_elem.text = translations[node.id]

            _save_xml(tree, drawing_path)

        comment_nodes = [n for n in nodes if n.id in translations and n.location["type"] == "comment_text"]
        comments_by_file: dict[str, list[TextNode]] = {}
        for node in comment_nodes:
            fname = node.location["comment_file"]
            comments_by_file.setdefault(fname, []).append(node)

        xl_dir = self.work_dir / "xl"
        for comment_filename, c_nodes in comments_by_file.items():
            comment_path = xl_dir / comment_filename
            tree = _parse_xml(comment_path)
            root = tree.getroot()
            all_t = root.findall(".//ss:t", NS)

            for node in c_nodes:
                t_elem = all_t[node.location["text_idx"]]
                t_elem.text = translations[node.id]

            _save_xml(tree, comment_path)

    def save(self, output_path: str) -> None:
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root_dir, dirs, files in os.walk(self.work_dir):
                for file in files:
                    file_path = Path(root_dir) / file
                    arcname = file_path.relative_to(self.work_dir)
                    zf.write(file_path, arcname)

        shutil.rmtree(self.work_dir, ignore_errors=True)