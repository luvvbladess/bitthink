"""Portable SKILL.md packages. Imports are data, never executable code."""
from io import BytesIO
from pathlib import PurePosixPath
import re
import time
import zipfile
import yaml
from sqlalchemy import select, delete
from app.db.engine import SyncSessionLocal
from app.db.models import UserSkill, SkillResource
from computer_skills.store import validate_payload, MAX_SKILLS

MAX_PACKAGE = 10 * 1024 * 1024


def safe_path(name: str) -> str:
    path = PurePosixPath(name)
    if not name or len(name) > 240 or "\\" in name or ":" in name or path.is_absolute() or ".." in path.parts:
        raise ValueError("В архиве недопустимый путь.")
    return path.as_posix()


def parse_package(data: bytes, filename: str) -> tuple[dict, dict[str, bytes]]:
    if len(data) > MAX_PACKAGE:
        raise ValueError("Пакет должен быть не больше 10 МБ.")
    resources = {}
    if filename.lower().endswith(".zip"):
        try:
            with zipfile.ZipFile(BytesIO(data)) as archive:
                files = [i for i in archive.infolist() if not i.is_dir()]
                if len(files) > 100 or sum(i.file_size for i in files) > MAX_PACKAGE:
                    raise ValueError("В архиве слишком много файлов или больше 10 МБ распакованных данных.")
                for info in files:
                    name = safe_path(info.filename)
                    if name in resources or (info.external_attr >> 16) & 0o170000 == 0o120000:
                        raise ValueError("Дубли файлов и символьные ссылки не поддерживаются.")
                    resources[name] = archive.read(info)
            raw = resources.pop("SKILL.md")
        except (zipfile.BadZipFile, KeyError, RuntimeError) as exc:
            raise ValueError("Нужен ZIP с SKILL.md в корне.") from exc
    elif filename.lower().endswith(".md"):
        raw = data
    else:
        raise ValueError("Загрузите .md или .zip.")
    try:
        text = raw.decode("utf-8-sig")
        match = re.match(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", text, re.S)
        if not match:
            raise ValueError("SKILL.md должен начинаться с YAML-полей name и description.")
        meta = yaml.safe_load(match.group(1))
        if not isinstance(meta, dict) or not isinstance(meta.get("name"), str) or not isinstance(meta.get("description"), str):
            raise ValueError("В YAML нужны текстовые name и description.")
        if len(match.group(2).strip()) > 64000:
            raise ValueError("Инструкции скила должны быть до 64 000 символов.")
        payload = validate_payload(name=meta["name"], description=meta["description"],
            title=str(meta.get("title") or meta["name"]), body=match.group(2), triggers=str(meta.get("triggers") or ""))
        return payload, resources
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError("Проверьте UTF-8 и YAML-заголовок SKILL.md.") from exc


def import_package(user_id: int, data: bytes, filename: str) -> dict:
    payload, resources = parse_package(data, filename)
    with SyncSessionLocal() as session:
        row = session.scalar(select(UserSkill).where(UserSkill.user_id == user_id, UserSkill.name == payload["name"]))
        if row:
            raise ValueError("Скил с таким именем уже существует. Переименуйте пакет перед импортом.")
        if len(session.scalars(select(UserSkill.id).where(UserSkill.user_id == user_id)).all()) >= MAX_SKILLS:
            raise ValueError("Достигнут лимит своих скилов.")
        row = UserSkill(user_id=user_id, **payload, enabled=True, created_at=int(time.time()), updated_at=int(time.time()))
        session.add(row)
        for path, content in resources.items():
            session.add(SkillResource(user_id=user_id, skill_name=row.name, path=path, content=content))
        session.commit()
        return {**payload, "enabled": True, "origin": "custom", "updated_at": row.updated_at,
                "resource_count": len(resources)}


def resource_names(user_id: int, name: str) -> list[str]:
    with SyncSessionLocal() as session:
        return list(session.scalars(select(SkillResource.path).where(
            SkillResource.user_id == user_id, SkillResource.skill_name == name)))


def read_resource(user_id: int, name: str, path: str) -> bytes | None:
    safe_path(path)
    with SyncSessionLocal() as session:
        skill = session.scalar(select(UserSkill).where(UserSkill.user_id == user_id, UserSkill.name == name, UserSkill.enabled.is_(True)))
        if not skill:
            return None
        return session.scalar(select(SkillResource.content).where(
            SkillResource.user_id == user_id, SkillResource.skill_name == name, SkillResource.path == path))


def export_package(user_id: int, name: str) -> bytes | None:
    with SyncSessionLocal() as session:
        row = session.scalar(select(UserSkill).where(UserSkill.user_id == user_id, UserSkill.name == name))
        if not row:
            return None
        metadata = yaml.safe_dump({"name": row.name, "title": row.title, "description": row.description,
                                   "triggers": row.triggers}, allow_unicode=True, sort_keys=False)
        output = BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("SKILL.md", "---\n" + metadata + "---\n\n" + row.body)
            for asset in session.scalars(select(SkillResource).where(
                    SkillResource.user_id == user_id, SkillResource.skill_name == name)):
                archive.writestr(asset.path, asset.content)
        return output.getvalue()
