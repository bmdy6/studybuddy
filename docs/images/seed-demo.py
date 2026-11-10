"""README screenshots only: run in a NEW disposable MySQL database after init_db.py.
No model is called. Every message and assessment below is hand-authored fixture data.
"""
import json
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
from app.database import SessionLocal
from app.models import User,ChatSession,ChatMessage,StudyPlanDraft
from app.models.p2 import StudentAttribute,StudyPlan,StudyPlanItem,StudyPlanItemAttempt
from app.utils.security import hash_password,create_access_token
from app.config import settings
assert settings.DB_HOST=='127.0.0.1' and settings.DB_NAME=='readme_demo_test', 'Disposable README database only'
with SessionLocal() as db:
    assert db.query(User).count()==0, 'Fresh database required'
    user=User(username='readme_student',display_name='演示同学',password_hash=hash_password('synthetic-demo-only'),role='student')
    db.add(user);db.flush()
    db.add(StudentAttribute(student_id=user.id,source='manual',snapshot={'grade':'七年级','weak_subjects':['数学'],'subject_sources':{}}))
    main=ChatSession(user_id=user.id,student_id=user.id,role_at_create='student',primary_student_id=user.id,title='今天的分数练习',session_type='main')
    db.add(main);db.flush()
    items=[{'title':'同分母分数相加','target':'先保留分母，再把分子相加','minutes':15},{'title':'异分母分数练习','target':'先通分，再计算','minutes':20}]
    draft=StudyPlanDraft(student_id=user.id,created_by=user.id,chat_session_id=main.id,draft_data={'title':'分数加法 · 两步练习','focus':'先理解，再解释自己的做法','planned_date':date.today().isoformat(),'items':items},expires_at=datetime.now(timezone.utc).replace(tzinfo=None)+timedelta(days=2))
    db.add(draft);db.flush()
    output=dict(draft.draft_data,drafted=True,draft_id=draft.id,revision=1,chat_session_id=main.id,created_at=datetime.now(timezone.utc).isoformat())
    db.add_all([
      ChatMessage(session_id=main.id,role='user',content='今天想练习分数加法，帮我安排两个短任务。'),
      ChatMessage(session_id=main.id,role='assistant',content='这是预填的演示计划，请先查看任务，再确认创建。',tool_calls=[{'id':'demo-draft','function':{'name':'draft_study_plan','arguments':'{}'}}]),
      ChatMessage(session_id=main.id,role='tool',content=json.dumps(output,ensure_ascii=False),tool_result={'tool_call_id':'demo-draft'}),
      ChatMessage(session_id=main.id,role='assistant',content='先练同分母，再练通分。确认后会生成正式计划。')])
    plan=StudyPlan(student_id=user.id,created_by=user.id,title='分数加法 · 昨日练习',focus='保留作答，接着练习',planned_date=date.today())
    db.add(plan);db.flush()
    taskitem=StudyPlanItem(plan_id=plan.id,title=items[0]['title'],target=items[0]['target'],minutes=15,status='in_progress')
    db.add(taskitem);db.flush()
    task=ChatSession(user_id=user.id,student_id=user.id,role_at_create='student',title='任务 · 同分母分数相加',session_type='task',plan_id=plan.id,plan_item_id=taskitem.id)
    db.add(task);db.flush()
    db.add_all([
      ChatMessage(session_id=task.id,role='assistant',content='**同分母分数相加**\n\n试一试：$\\frac{1}{5}+\\frac{2}{5}$ 等于多少？请解释为什么分母不变。\n\n（预填演示讲解，不是模型实时回复。）'),
      ChatMessage(session_id=task.id,role='user',content='等于 3/5。把同样大小的五分之一合在一起，所以分母还是 5。'),
      ChatMessage(session_id=task.id,role='assistant',content='**作答记录（预填演示）**\n\n已保留你的答案和解释。下一次从「用图解释分母为什么不变」接着练习。\n\n这份演示判定仅展示记录结构，不代表已经掌握。')])
    db.add(StudyPlanItemAttempt(plan_item_id=taskitem.id,student_id=user.id,assessment='needs_retry',evidence_summary='学生回答 3/5，并解释单位分数大小不变（虚构作答）',reason='预填演示，继续核对理解',next_start='用图解释分母为什么不变'))
    db.commit()
    token=create_access_token(user.id,user.role)
    target=Path(__file__).parent
    for name,session_id,is_task in [('plan',main.id,False),('task',task.id,True)]:
      state={'token':token,'role':'student','displayName':'演示同学','userId':user.id,'children':[],'activeChildId':None,'mode':'study','authVersion':1,'recentAccounts':[]}
      nav={'sessionId':session_id,'activeTaskSessionId':task.id if is_task else None,'mainSessionId':main.id if is_task else None}
      browser={'cookies':[],'origins':[{'origin':'http://127.0.0.1:15173','localStorage':[{'name':'studybuddy-auth','value':json.dumps({'state':state,'version':0},ensure_ascii=False)},{'name':f'studybuddy-nav-{user.id}','value':json.dumps(nav)}]}]}
      (target/f'{name}-state.private.json').write_text(json.dumps(browser,ensure_ascii=False))
    print(json.dumps({'user':user.id,'main':main.id,'task':task.id,'draft':draft.id,'plan':plan.id,'item':taskitem.id}))
