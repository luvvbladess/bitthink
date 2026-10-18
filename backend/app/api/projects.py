import asyncio
from typing import Literal
from urllib.parse import urlsplit
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from app.auth import get_current_user
from app.core.repository import repo
from app.services import project_memory as memory
from app.services import project_results as results
from fastapi.responses import Response, FileResponse
from app.services import project_assets

router = APIRouter()


class Create(BaseModel):
    name: str = Field(min_length=1, max_length=160)


class Attach(BaseModel):
    project_id: str | None = Field(default=None, max_length=32)


class Entry(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    body: str = Field(min_length=1, max_length=60000)
    kind: Literal["note", "decision", "source"] = "note"
    source_url: str = Field(default="", max_length=2048)

    @field_validator("source_url")
    @classmethod
    def public_url(cls, value):
        if value:
            p = urlsplit(value)
            if p.scheme not in {"http", "https"} or not p.hostname or p.username or p.password:
                raise ValueError("Нужна ссылка http(s) без пароля.")
        return value


class Publish(BaseModel):
    conversation_id: str = Field(min_length=1, max_length=64)
    document_id: int
    entry_id: str | None = Field(default=None, max_length=32)
    expected_revision: int | None = Field(default=None, ge=1)

    @model_validator(mode='after')
    def revision_pair(self):
        if bool(self.entry_id) != (self.expected_revision is not None):
            raise ValueError('Для обновления документа нужны запись и её версия.')
        return self


class UpdateEntry(Entry):
    kind: Literal["note", "decision", "source", "file"] = "note"
    expected_revision: int = Field(ge=1)
    body: str = Field(min_length=1, max_length=2_000_000)

    @model_validator(mode='after')
    def body_limit(self):
        if self.kind != 'file' and len(self.body) > 60000:
            raise ValueError('Заметка может содержать до 60 000 символов.')
        return self


class Restore(BaseModel):
    revision: int = Field(ge=1)
    expected_revision: int = Field(ge=1)


class ResolveSuggestion(BaseModel):
    accept: bool
    expected_revision: int = Field(ge=1)


class ResultInput(BaseModel):
    spec: dict
    expected_revision: int | None = Field(default=None, ge=1)


async def call(fn, user, *args):
    uid = await repo.ensure_user(user)
    try: return await asyncio.to_thread(fn, uid, *args)
    except ValueError as exc: raise HTTPException(409 if "уже изменена" in str(exc) else 404 if "не найден" in str(exc) else 400, str(exc)) from exc


@router.get("")
async def projects(user: str = Depends(get_current_user)):
    return await call(memory.list_projects, user)


@router.post("")
async def create(data: Create, user: str = Depends(get_current_user)):
    if not data.name.strip(): raise HTTPException(400, "Укажите название проекта.")
    return await call(memory.create, user, data.name)


@router.get("/chat/{cid}")
async def attached(cid: str, user: str = Depends(get_current_user)):
    return await call(memory.attached, user, cid)


@router.patch('/{pid}')
async def rename_project(pid: str, data: Create, user: str = Depends(get_current_user)):
    return await call(memory.rename_project, user, pid, data.name)


@router.delete('/{pid}')
async def delete_project(pid: str, user: str = Depends(get_current_user)):
    return await call(memory.delete_project, user, pid)


@router.put("/chat/{cid}")
async def attach(cid: str, data: Attach, user: str = Depends(get_current_user)):
    return await call(memory.attach, user, cid, data.project_id)


@router.get("/chat/{cid}/documents")
async def documents(cid: str, user: str = Depends(get_current_user)):
    return await call(memory.documents, user, cid)


@router.get("/{pid}/entries")
async def entries(pid: str, q: str = "", user: str = Depends(get_current_user)):
    if len(q) > 500: raise HTTPException(400, "Слишком длинный запрос.")
    return await call(memory.search, user, pid, q)


@router.get('/{pid}/suggestions')
async def suggestions(pid: str, user: str = Depends(get_current_user)):
    return await call(memory.suggestions, user, pid)


@router.get('/{pid}/workspace')
async def workspace(pid: str, user: str = Depends(get_current_user)):
    return await call(memory.workspace, user, pid)


@router.post('/{pid}/results')
async def result_create(pid: str, data: ResultInput, user: str = Depends(get_current_user)):
    return await call(results.save, user, pid, data.spec)


@router.get('/{pid}/results/{eid}')
async def result_read(pid: str, eid: str, revision: int | None = None, user: str = Depends(get_current_user)):
    return await call(results.read, user, pid, eid, revision)


@router.put('/{pid}/results/{eid}')
async def result_update(pid: str, eid: str, data: ResultInput, user: str = Depends(get_current_user)):
    if data.expected_revision is None: raise HTTPException(400,'Нужна версия результата.')
    return await call(results.save, user, pid, data.spec, eid, data.expected_revision)


@router.get('/{pid}/results/{eid}/export/{format}')
async def result_export(pid: str, eid: str, format: Literal['xlsx','docx','pptx'], user: str = Depends(get_current_user)):
    content,mime = await call(results.export, user, pid, eid, format)
    return Response(content, media_type=mime, headers={'Content-Disposition':f'attachment; filename="result.{format}"'})


@router.get('/{pid}/entries/{eid}/original')
async def original(pid: str, eid: str, user: str = Depends(get_current_user)):
    path,name = await call(project_assets.original,user,pid,eid)
    return FileResponse(path,filename=name)


@router.post('/{pid}/suggestions/{eid}')
async def resolve_suggestion(pid: str, eid: str, data: ResolveSuggestion, user: str = Depends(get_current_user)):
    return await call(memory.resolve_suggestion, user, pid, eid, data.accept, data.expected_revision)


@router.post("/{pid}/entries")
async def save(pid: str, data: Entry, user: str = Depends(get_current_user)):
    if not data.title.strip() or not data.body.strip(): raise HTTPException(400, "Заполните название и текст.")
    return await call(memory.save, user, pid, data.title, data.body, data.kind, data.source_url)


@router.delete("/{pid}/entries/{eid}")
async def delete(pid: str, eid: str, user: str = Depends(get_current_user)):
    await call(memory.remove, user, pid, eid)
    return {"ok": True}


@router.get("/{pid}/entries/{eid}")
async def detail(pid: str, eid: str, user: str = Depends(get_current_user)):
    return await call(memory.detail, user, pid, eid)


@router.put("/{pid}/entries/{eid}")
async def update(pid: str, eid: str, data: UpdateEntry, user: str = Depends(get_current_user)):
    if not data.title.strip() or not data.body.strip(): raise HTTPException(400, "Заполните название и текст.")
    return await call(memory.save, user, pid, data.title.strip(), data.body, data.kind, data.source_url, eid, data.expected_revision)


@router.get("/{pid}/entries/{eid}/history")
async def history(pid: str, eid: str, user: str = Depends(get_current_user)):
    return await call(memory.history, user, pid, eid)


@router.get("/{pid}/entries/{eid}/versions/{number}")
async def version(pid: str, eid: str, number: int, user: str = Depends(get_current_user)):
    return await call(memory.detail, user, pid, eid, number)


@router.post("/{pid}/entries/{eid}/restore")
async def restore(pid: str, eid: str, data: Restore, user: str = Depends(get_current_user)):
    return await call(memory.restore, user, pid, eid, data.revision, data.expected_revision)


@router.post("/{pid}/documents")
async def publish(pid: str, data: Publish, user: str = Depends(get_current_user)):
    return await call(memory.publish_document, user, pid, data.conversation_id, data.document_id, data.entry_id, data.expected_revision)
