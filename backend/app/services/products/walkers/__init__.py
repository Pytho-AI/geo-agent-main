"""The format walkers — IBL's exporter.py / xlsx_exporter.py FORMAT
ported (build-log cont 36u/36v step 4). The HTML layer is DEAD: the
DOCX lane walks SPEC + structured_content directly into python-docx;
PPTX is python-pptx native as IBL had it; XLSX is openpyxl native as
IBL had it. Zero per-product branches anywhere — every dispatch reads
shape / header_fields / row_fields / paragraph_fields / matrix_spec /
group_by from the schema. No importer markers of any kind (read-back
is agentic; the SDT/defined-name/hidden-slide machinery did not port).
"""
from .common import artifact_filename_base  # noqa: F401
from .docx import render_docx  # noqa: F401
from .pptx import render_pptx  # noqa: F401
from .xlsx import render_xlsx  # noqa: F401

__all__ = ["render_docx", "render_pptx", "render_xlsx",
           "artifact_filename_base"]
