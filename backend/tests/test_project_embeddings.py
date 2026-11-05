"""Access boundaries, lifecycle races and latency guarantees of optional retrieval."""
from concurrent.futures import ThreadPoolExecutor
import threading
import time
from uuid import uuid4

import pytest
from sqlalchemy import select, func
from app.db.engine import SyncSessionLocal
from app.db.project_models import Project, ProjectEntry, ProjectChunk, ProjectRevision
from app.services import project_embeddings as embeddings, project_memory as memory
from app.services.project_policy import scope


def vector(position=0):
    return tuple(1. if n == position else 0. for n in range(embeddings.DIMENSIONS))


@pytest.fixture
def project(monkeypatch):
    uid, pid = 987123, uuid4().hex
    with SyncSessionLocal() as session:
        session.add(Project(id=pid, user_id=uid, name='Retrieval fixture', created_at=1))
        session.commit()
    monkeypatch.setattr(embeddings, 'enabled', lambda: True)
    monkeypatch.setattr(embeddings, 'schedule', lambda *args: None)
    monkeypatch.setattr(embeddings, 'query_vector', lambda *args: vector())
    return uid, pid


def add(project, title, body, *, kind='file', embedded=True, position=0):
    uid, pid = project
    item = memory.save(uid, pid, title, body, kind)
    if embedded:
        with SyncSessionLocal() as session:
            for row in session.scalars(select(ProjectChunk).where(ProjectChunk.entry_id == item['id'])):
                row.embedding, row.embedding_model = embeddings.pack(vector(position)), embeddings.MODEL_VERSION
            session.commit()
    return item


def test_semantic_retrieval_has_current_citation_and_rejects_foreign_owner(project):
    item = add(project, 'Протокол', 'Передать результат клиенту пятнадцатого декабря.')
    uid, pid = project
    rows = memory.search(uid, pid, 'Когда сдаём работу заказчику?')
    assert rows[0]['id'] == item['id']
    assert rows[0]['citation_url'] == f"#project/{pid}/{item['id']}/1/0"
    with pytest.raises(ValueError):
        memory.search(uid+1, pid, 'Когда сдаём работу заказчику?')


def test_policy_filters_apply_before_network_and_ranking(project, monkeypatch):
    excluded = add(project, 'Скрытая запись', 'Закрытые договорённости.')
    visible = add(project, 'Открытая запись', 'Разрешённые сведения.')
    uid, pid = project
    with scope({'project_id':pid, 'entry_ids':[visible['id']], 'include_memory':True}):
        assert [r['id'] for r in memory.search(uid,pid,'Иные формулировки')] == [visible['id']]
    def unexpected(*args):
        raise AssertionError('No request is allowed for an empty permitted corpus')
    monkeypatch.setattr(embeddings, 'query_vector', unexpected)
    with scope({'project_id':pid, 'entry_ids':[], 'include_memory':True}):
        assert memory.search(uid,pid,'Иные формулировки') == []
    assert excluded['id'] != visible['id']


def test_memory_opt_out_and_unaccepted_suggestions_are_not_candidates(project):
    add(project, 'Заметка', 'Данные памяти.', kind='note')
    add(project, 'Решение', 'Данные решения.', kind='decision')
    add(project, 'Предложение', 'Непринятый текст.', kind='suggestion')
    visible = add(project, 'Файл', 'Содержимое файла.')
    uid,pid=project
    with scope({'project_id':pid,'entry_ids':None,'include_memory':False}):
        assert [r['id'] for r in memory.search(uid,pid,'Иные формулировки')] == [visible['id']]


def test_update_restore_and_delete_remove_old_vectors(project):
    uid,pid=project
    item=add(project,'Версия','Исходный текст.')
    assert memory.search(uid,pid,'Перефразировка')
    memory.save(uid,pid,'Версия','Новая редакция.',entry_id=item['id'],expected_revision=1)
    with SyncSessionLocal() as session:
        row=session.scalar(select(ProjectChunk).where(ProjectChunk.entry_id==item['id']))
        assert row.embedding is None
    assert memory.search(uid,pid,'Перефразировка') == []
    memory.restore(uid,pid,item['id'],1,2)
    assert memory.detail(uid,pid,item['id'])['revision']==3
    memory.remove(uid,pid,item['id'])
    with SyncSessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(ProjectChunk).where(ProjectChunk.entry_id==item['id']))==0
    assert not memory.search(uid,pid,'Исходный')


def test_index_result_cannot_attach_to_replaced_or_deleted_chunks(project, monkeypatch):
    uid,pid=project
    item=add(project,'Исходник','Начальный текст.',embedded=False)
    def replacing(texts, **kwargs):
        memory.save(uid,pid,'Исходник','Исправленный текст.',entry_id=item['id'],expected_revision=1)
        return [vector() for _ in texts]
    monkeypatch.setattr(embeddings,'embed',replacing)
    assert embeddings.index_project(uid,pid,[item['id']])==0
    with SyncSessionLocal() as session:
        assert session.scalar(select(ProjectChunk.embedding).where(ProjectChunk.entry_id==item['id'])) is None
    def deleting(texts, **kwargs):
        memory.remove(uid,pid,item['id'])
        return [vector() for _ in texts]
    monkeypatch.setattr(embeddings,'embed',deleting)
    assert embeddings.index_project(uid,pid,[item['id']])==0


def test_deleted_during_query_is_not_returned(project, monkeypatch):
    uid,pid=project
    item=add(project,'Исходник','Начальный текст.')
    def deleting(*args):
        memory.remove(uid,pid,item['id'])
        return vector()
    monkeypatch.setattr(embeddings,'query_vector',deleting)
    assert memory.search(uid,pid,'Начальный')==[]


def test_edited_during_query_cannot_return_stale_lexical_or_semantic(project, monkeypatch):
    uid,pid=project
    item=add(project,'Материал','Начальный текст.')
    def editing(*args):
        memory.save(uid,pid,'Материал','Актуальная редакция.',entry_id=item['id'],expected_revision=1)
        return vector()
    monkeypatch.setattr(embeddings,'query_vector',editing)
    assert memory.search(uid,pid,'Начальный')==[]


def test_exact_identifier_keeps_priority_over_similar_components(project):
    other=add(project,'Кабели','Заказ PO-8743 с предоплатой.')
    correct=add(project,'Крепёж','Заказ PO-8742 с оплатой после доставки.')
    uid,pid=project
    assert memory.search(uid,pid,'Когда отправят PO-8742?')[0]['id']==correct['id']
    assert correct['id']!=other['id']


def test_disabled_empty_unindexed_and_failed_provider_keep_lexical(project, monkeypatch):
    uid,pid=project
    add(project,'Инструкция','Совпадение слова кварц.',embedded=False)
    expected=memory._lexical_search(uid,pid,'кварц',3)
    assert memory.search(uid,pid,'кварц',3)==expected
    monkeypatch.setattr(embeddings,'enabled',lambda:False)
    assert memory.search(uid,pid,'кварц',3)==expected
    assert memory.search(uid,pid,'',3)==memory._lexical_search(uid,pid,'',3)
    monkeypatch.setattr(embeddings,'enabled',lambda:True)
    add(project,'Дополнение','Иное содержимое.')
    monkeypatch.setattr(embeddings,'query_vector',lambda *args:None)
    assert memory.search(uid,pid,'кварц',3)==expected


def test_real_wall_clock_deadline_and_late_result_cache(monkeypatch):
    # The transport may ignore its own timeout; the caller still returns promptly.
    release=threading.Event()
    uid,pid=987124,uuid4().hex
    monkeypatch.setattr(embeddings,'QUERY_DEADLINE',.04)
    def slow(texts,**kwargs):
        release.wait(2)
        return [vector()]
    monkeypatch.setattr(embeddings,'embed',slow)
    start=time.monotonic()
    assert embeddings.query_vector(uid,pid,'Вопрос') is None
    assert time.monotonic()-start < .2
    release.set()
    for _ in range(100):
        with embeddings._lock:
            done=not any(k[:2]==(uid,pid) for k in embeddings._inflight)
        if done:break
        time.sleep(.005)
    assert done
    assert embeddings.query_vector(uid,pid,'Вопрос')==vector()


def test_saturated_pool_returns_without_enqueuing(monkeypatch):
    semaphore=threading.BoundedSemaphore(1)
    semaphore.acquire()
    monkeypatch.setattr(embeddings,'_query_slots',semaphore)
    start=time.monotonic()
    assert embeddings.query_vector(0,uuid4().hex,'Новый вопрос') is None
    assert time.monotonic()-start < .05


def test_invalid_vectors_and_bad_response_indices_are_rejected(monkeypatch):
    for value in ([0.]*1024, [float('nan')]*1024, [1.], [True]*1024):
        with pytest.raises(ValueError):embeddings.pack(value)
    class Response:
        def raise_for_status(self):pass
        def json(self):return {'data':[{'index':1,'embedding':vector()}]}
    class Client:
        def post(self,*args,**kwargs):return Response()
    monkeypatch.setattr(embeddings,'_http_client',lambda:Client())
    with pytest.raises(ValueError):embeddings.embed(['test'])


def test_project_deletion_clears_all_vectors(project):
    uid,pid=project
    item=add(project,'Материал','Текст с вектором.')
    memory.delete_project(uid,pid)
    with SyncSessionLocal() as session:
        assert not session.scalar(select(ProjectChunk).where(ProjectChunk.entry_id==item['id']))
