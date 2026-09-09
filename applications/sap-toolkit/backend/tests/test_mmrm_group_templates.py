import json
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
TEMPLATE_ROOT = ROOT_DIR / "scripts" / "phase2" / "模板代码"

TRIAL_GROUP = "试验组 (N=n1)"
CONTROL_GROUP = "对照组 (N=n1)"
MULTI_GROUP_COLUMNS = ["组别1 (N=n1)", "组别2 (N=n1)", CONTROL_GROUP]


def load_template(template_code: str) -> dict:
    template_path = TEMPLATE_ROOT / template_code / f"{template_code}.json"
    if not template_path.is_file():
        raise AssertionError(f"缺少模板文件: {template_path}")
    with template_path.open(encoding="utf-8") as f:
        return json.load(f)


def all_rows(template: dict) -> list[dict]:
    return [row for section in template["sections"] for row in section["rows"]]


class MmrmGroupTemplateTests(unittest.TestCase):
    def test_two_group_event_frequency_template_uses_trial_control_headers(self):
        template = load_template("E_G2_FREQ3")
        data_columns = [column["name"] for column in template["columns"][1:]]

        self.assertEqual(
            data_columns,
            [
                TRIAL_GROUP,
                TRIAL_GROUP,
                CONTROL_GROUP,
                CONTROL_GROUP,
                "合计 (N=n1)",
                "合计 (N=n1)",
                "P值",
            ],
        )
        for row in all_rows(template):
            self.assertNotIn("组别1 (N=n1)", row.get("applies_to", []))
            self.assertNotIn("组别2 (N=n1)", row.get("applies_to", []))

    def test_g2_mmrm_templates_are_two_group_trial_control_templates(self):
        for template_code in ("F_G2_MMRM_P2", "F_G2_MMRM_02_P2"):
            with self.subTest(template_code=template_code):
                template = load_template(template_code)
                data_columns = [column["name"] for column in template["columns"][2:]]

                self.assertEqual(template["code"], template_code)
                self.assertEqual(data_columns, [TRIAL_GROUP, CONTROL_GROUP])
                for row in all_rows(template):
                    self.assertEqual(len(row["data_values"]), 2)
                    self.assertTrue(set(row.get("applies_to", [])) <= set(data_columns))

    def test_g3_mmrm_templates_preserve_the_existing_three_arm_layout(self):
        for template_code in ("F_G3_MMRM_P2", "F_G3_MMRM_02_P2"):
            with self.subTest(template_code=template_code):
                template = load_template(template_code)
                data_columns = [column["name"] for column in template["columns"][2:]]

                self.assertEqual(template["code"], template_code)
                self.assertEqual(data_columns, MULTI_GROUP_COLUMNS)
                for row in all_rows(template):
                    self.assertEqual(len(row["data_values"]), 3)
                    self.assertTrue(set(row.get("applies_to", [])) <= set(data_columns))


if __name__ == "__main__":
    unittest.main()
