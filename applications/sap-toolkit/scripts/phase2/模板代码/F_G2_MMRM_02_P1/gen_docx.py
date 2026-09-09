"""Render the two-group MMRM model-statistics shell with visit interaction."""

from scripts.phase2.mmrm_utils import generate_mmrm_docx


def generate_docx(filled_data: dict, output_path) -> None:
    generate_mmrm_docx(filled_data, output_path)
