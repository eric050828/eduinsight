"""Re-index all course materials using the new markdown pipeline.

After upgrading the upload flow to convert PDFs/PPTX → Markdown with
anchor metadata, existing demo data uses the legacy `[file p.N]` tags
which don't carry anchors. Run this once after a /demo/reset to:

  1. Re-process every PDF in `_sim_materials/` for the 5 demo courses
  2. Cache `.md` under `_materials_md/{course}/{filename}.md`
  3. Re-index chunks with anchor metadata so citations can jump

Usage:
    uv run python scripts/reindex_materials_md.py
"""

from __future__ import annotations

from pathlib import Path

from litemem import Memory

from eduinsight.config import settings
from eduinsight.documents import to_markdown
from eduinsight.rag import CourseRAG


# Map course id → list of source PDFs to (re)index
MATERIALS = {
    "ds101": [
        "_sim_materials/ds101_week01_intro_arrays.pdf",
        "_sim_materials/ds101_week04_trees_traversal.pdf",
        "_sim_materials/ds101_week08_sorting.pdf",
    ],
    "mk201": ["_sim_materials/mk201_marketing_management.pdf"],
    "chm301": ["_sim_materials/chm301_pchem_thermo.pdf"],
    "eng201": ["_sim_materials/eng201_academic_writing.pdf"],
    "ipr101": ["_sim_materials/ipr101_patent_law.pdf"],
}


def main() -> None:
    mem = Memory(settings.memory_db_path)
    rag = CourseRAG(mem)

    md_root = Path("_materials_md")
    md_root.mkdir(parents=True, exist_ok=True)

    for course_id, files in MATERIALS.items():
        # Wipe existing course material chunks (keep student memories)
        existing = mem.list(f"course:{course_id}", category="course_material")
        if existing:
            # We can't selectively remove just course_material from Lite-Mem's API,
            # so we rely on the dedicated course UID never holding student facts.
            # Forget the whole course namespace.
            mem.forget(f"course:{course_id}")
            print(f"  cleared {len(existing)} old chunks for {course_id}")

        course_md_dir = md_root / course_id
        course_md_dir.mkdir(parents=True, exist_ok=True)

        for path_str in files:
            p = Path(path_str)
            if not p.exists():
                print(f"  skip missing: {p}")
                continue
            parsed = to_markdown(p)
            parsed.filename = p.name
            for c in parsed.chunks:
                c.source = p.name

            # Cache markdown for the /materials/{file}/markdown endpoint
            (course_md_dir / f"{p.name}.md").write_text(parsed.markdown, encoding="utf-8")

            n = rag.index_markdown(course_id, parsed)
            print(f"  {course_id}/{p.name}: md {len(parsed.markdown)} bytes, {n} chunks")


if __name__ == "__main__":
    main()
