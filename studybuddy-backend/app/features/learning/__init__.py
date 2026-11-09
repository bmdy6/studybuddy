"""学习域 feature：诊断（diagnosis）+ 学习地图（map）+ 学习流（flow）+ 学习进度（progress）。

依赖方向：learning -> error_book（诊断/学习流读错题本，经 error_book.service 公开函数）。
diagnosis_service 原含 get_error_book/get_error_book_by_subject（错题读），已移入
error_book/service.py（约束 #6 增内聚，与 upsert 写接口成对），本文件只留 get_diagnosis。
"""
