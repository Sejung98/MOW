"""PyInstaller를 이용해 Windows/Mac 실행 파일을 생성하는 스크립트."""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
ENTRY_FILE = PROJECT_ROOT / "inventory_app.py"
THEME_FILE = PROJECT_ROOT / "theme.json"


def ensure_pyinstaller() -> None:
    """PyInstaller 설치 여부를 검사한다."""

    if shutil.which("pyinstaller") is None:
        raise SystemExit("PyInstaller가 설치되어 있지 않습니다. 'pip install pyinstaller' 명령으로 설치하세요.")


def build(target: str, onefile: bool = False) -> None:
    """선택한 OS용 실행 파일을 생성한다."""

    ensure_pyinstaller()
    if not ENTRY_FILE.exists():
        raise SystemExit("inventory_app.py 파일을 찾을 수 없습니다.")

    add_data_sep = ";" if target == "windows" else ":"
    add_data = f"{THEME_FILE}{add_data_sep}." if THEME_FILE.exists() else None

    name = "MOWInventory" if target == "windows" else "MOWInventoryMac"
    cmd = [
        "pyinstaller",
        "--noconfirm",
        f"--name={name}",
        "--windowed",
    ]
    if onefile or target == "windows":
        cmd.append("--onefile")
    if add_data:
        cmd.extend(["--add-data", add_data])
    cmd.append(str(ENTRY_FILE))

    print("실행 명령:", " ".join(cmd))
    subprocess.run(cmd, check=True)
    dist_dir = PROJECT_ROOT / "dist"
    if dist_dir.exists():
        print(f"생성된 실행 파일은 {dist_dir.resolve()} 폴더에서 확인할 수 있습니다.")


def main() -> None:
    parser = argparse.ArgumentParser(description="MOW 데스크톱 실행 파일 생성기")
    parser.add_argument("--target", choices=["windows", "mac"], required=True, help="패키징할 OS")
    parser.add_argument(
        "--onefile",
        action="store_true",
        help="Mac에서도 단일 실행 파일(.app)이 아닌 하나의 바이너리로 묶고 싶을 때 사용",
    )
    args = parser.parse_args()

    try:
        build(target=args.target, onefile=args.onefile)
    except subprocess.CalledProcessError as exc:  # pragma: no cover
        raise SystemExit(exc.returncode) from exc


if __name__ == "__main__":
    main()
