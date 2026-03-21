"""CapCut 프로젝트를 ZIP으로 패키징."""

import zipfile
from pathlib import Path


def zip_capcut_project(project_dir: Path, output_path: Path) -> Path:
    """CapCut 프로젝트 폴더를 ZIP으로 압축한다."""
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in project_dir.rglob("*"):
            if file.is_file():
                arcname = file.relative_to(project_dir.parent)
                zf.write(file, arcname)
    return output_path
