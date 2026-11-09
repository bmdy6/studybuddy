from app.features.memory.retrieval import search_workspace_memory
from app.features.p2.schemas import StudyPlanItemInput
from app.features.p2 import study_plan
from app.models.note import Note

def test_search_workspace_memory_hits_tag_and_fts(db):
    # 造 2 笔记 1 错题
    n1 = Note(student_id=2, title="定语从句", content="定语从句讲解", knowledge_tags=["定语从句", "英语"], status="confirmed", mode="study")
    n2 = Note(student_id=2, title="一般过去时", content="一般过去时", knowledge_tags=["一般过去时"], status="confirmed", mode="study")
    db.add_all([n1, n2])
    db.commit()
    hits = search_workspace_memory(db, student_id=2, query="定语从句", k=5)
    assert any(h["type"] == "note" and "定语从句" in h["title"] for h in hits)
    assert hits[0]["score"] > 0

def test_create_relation_and_list(db):
    from app.features.memory.relations import create_relations, list_relations
    rows = create_relations(db, 2, [{"source_type": "note", "source_id": 1, "target_type": "error_book", "target_id": 2, "relation": "related_to"}])
    assert len(rows) == 1
    listed = list_relations(db, 2, source_type="note", source_id=1)
    assert len(listed) >= 1
