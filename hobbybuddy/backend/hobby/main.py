"""hobbybuddy 兴趣空间后端入口。

复用底座 app.core.ai_service（LLM 调用）；自己的 auth/chat/hobby 域。
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from hobby.auth_router import router as auth_router
from hobby.chat_router import router as chat_router

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)

app = FastAPI(title="趣爱好 hobbybuddy", version="0.1.0")

# 第一版前端联调跨端口（client 5173/5174/5175 → 后端 8002）需要 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:5175",
        "http://127.0.0.1:5175",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(chat_router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
