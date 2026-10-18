"""Reviewed workflow metadata and explicit, owner-scoped personal templates."""
from functools import lru_cache
from io import BytesIO
import json
from pathlib import Path, PurePosixPath
import zipfile

ROOT = Path(__file__).resolve().parent


@lru_cache(maxsize=1)
def registry() -> dict[str, dict]:
    rows = json.loads((ROOT / 'adaptations.json').read_text(encoding='utf-8'))
    return {row['name']: row for row in rows}


def canonical_name(value: str) -> str:
    from .loader import builtin_names
    normalized = (value or '').strip().lower().replace('-', '_')
    # Preserve native names and personal skills; source aliases never shadow them.
    if normalized in builtin_names():
        return normalized
    for row in registry().values():
        if row['adaptation'] == 'builtin' and value.strip().lower() == row['source_name']:
            return row['name']
    return normalized


def builtin_resources(name: str) -> list[str]:
    folder = ROOT / name / 'references'
    if not folder.is_dir():
        return []
    return sorted(p.relative_to(ROOT / name).as_posix() for p in folder.rglob('*.md') if p.is_file())


def read_builtin_resource(name: str, path: str, user_id: int | None) -> bytes | None:
    from .loader import builtin_names, disabled_builtin_names
    wanted = canonical_name(name)
    if wanted not in builtin_names() or wanted in disabled_builtin_names(user_id):
        return None
    relative = PurePosixPath(path)
    if not path or '\\' in path or ':' in path or relative.is_absolute() or '..' in relative.parts:
        raise ValueError('Недопустимый путь ресурса.')
    base = (ROOT / wanted).resolve()
    target = (base / path).resolve()
    if not target.is_relative_to(base) or target.suffix.lower() not in {'.md', '.txt', '.json', '.csv', '.py'}:
        raise ValueError('Недопустимый текстовый ресурс.')
    if not target.is_file() or target.stat().st_size > 1024 * 1024:
        return None
    return target.read_bytes()


def templates() -> list[dict]:
    return [{k: row[k] for k in ('name', 'title', 'description', 'triggers')}
            for row in registry().values() if row['adaptation'] == 'template']


def install_template(user_id: int, name: str) -> dict:
    from app.services.skill_packages import import_package
    row = registry().get(name)
    if not row or row['adaptation'] != 'template':
        raise ValueError('Шаблон не найден.')
    # Deliberately use the same import validator, owner storage and quota as user packages.
    buf = BytesIO()
    with zipfile.ZipFile(buf, 'w') as archive:
        archive.writestr('SKILL.md', (ROOT / 'templates' / name / 'SKILL.md').read_bytes())
    return import_package(user_id, buf.getvalue(), name + '.zip')
