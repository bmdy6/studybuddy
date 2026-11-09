"""错题本 feature：错题原子写入（同生同题累加）+ 去重指纹。

无下游（底层域），被 exams（批改落错题）+ learning（诊断读错题）依赖。
迁移期 error_book 本身已全量迁入 features/，引用方逐步改新路径。
"""
