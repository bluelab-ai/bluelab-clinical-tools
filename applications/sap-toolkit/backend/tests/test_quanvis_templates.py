import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from docx import Document


ROOT_DIR = Path(__file__).resolve().parents[2]
TEMPLATE_ROOT = ROOT_DIR / "scripts" / "phase2" / "模板代码"
REMOVED_METRICS = (
    "较基线变化率",
    "与0比较",
)
STATISTIC_ROWS = ("统计方法", "检验统计量", "P值")


def load_module(module_path: Path):
    spec = importlib.util.spec_from_file_location(module_path.stem, module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def render_template_cells(template_code: str) -> list[str]:
    template_dir = TEMPLATE_ROOT / template_code
    with (template_dir / f"{template_code}.json").open(encoding="utf-8") as f:
        semantic = json.load(f)
    with (template_dir / "填充数据.json").open(encoding="utf-8") as f:
        data = json.load(f)

    fill_module = load_module(template_dir / "fill_template.py")
    filled = fill_module.fill_template(semantic, data["projects"], data["visits"])

    with tempfile.TemporaryDirectory() as temp_dir:
        output_path = Path(temp_dir) / "table.docx"
        docx_module = load_module(template_dir / "gen_docx.py")
        docx_module.generate_docx(filled, output_path)
        doc = Document(output_path)
        return [cell.text for cell in doc.tables[0]._cells]


class QuanvisTemplateTests(unittest.TestCase):
    def test_single_group_semantic_includes_change_from_baseline_section(self):
        semantic_path = TEMPLATE_ROOT / "F_G1_QUANVIS" / "F_G1_QUANVIS.json"
        with semantic_path.open(encoding="utf-8") as f:
            semantic = json.load(f)

        self.assertEqual(
            [section["type"] for section in semantic["sections"]],
            ["indicator_group", "visit_group", "change_group"],
        )

    def test_single_group_document_has_no_inference_rows(self):
        normalized_texts = [text.strip() for text in render_template_cells("F_G1_QUANVIS")]

        self.assertIn("基线", normalized_texts)
        self.assertIn("治疗期", normalized_texts)
        self.assertIn("治疗期较基线变化值", normalized_texts)
        for statistic_row in STATISTIC_ROWS:
            self.assertNotIn(statistic_row, normalized_texts)
        self.assertFalse(any(term in text for term in REMOVED_METRICS for text in normalized_texts))

    def test_multi_group_documents_include_statistics_for_baseline_visit_and_change(self):
        for template_code in ("F_G2_QUANVIS", "F_G3_QUANVIS"):
            with self.subTest(template_code=template_code):
                cell_texts = render_template_cells(template_code)
                normalized_texts = [text.strip() for text in cell_texts]

                self.assertIn("基线", normalized_texts)
                self.assertIn("治疗期", normalized_texts)
                self.assertIn("治疗期较基线变化值", normalized_texts)
                for statistic_row in STATISTIC_ROWS:
                    self.assertEqual(normalized_texts.count(statistic_row), 9)
                self.assertEqual(normalized_texts.count("-"), 9)
                self.assertEqual(normalized_texts.count("x.xxx"), 18)
                self.assertFalse(any(term in text for term in REMOVED_METRICS for text in normalized_texts))


if __name__ == "__main__":
    unittest.main()
