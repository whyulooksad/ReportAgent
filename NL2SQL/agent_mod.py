# agent_mod.py
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
import logging, traceback, json
import agent as agent_mod
import uvicorn

app = FastAPI()
logging.basicConfig(level=logging.INFO)

class QueryRequest(BaseModel):
    query: str

class QueryResponse(BaseModel):
    output: str

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/nl2sql", response_model=QueryResponse)
async def nl2sql(req: QueryRequest, request: Request):
    try:
        q = (req.query or "").strip()
        if not q:
            raise HTTPException(status_code=400, detail="query is empty")
        logging.info(f"[nl2sql] input: {q}")

        result = agent_mod.invoke(q)  # 调用 NL2SQL 逻辑

        # --- 统一把返回折叠成字符串 ---
        if isinstance(result, dict):
            out = result.get("output") or result.get("sql") or result.get("text") or json.dumps(result, ensure_ascii=False)
        else:
            out = str(result)
        logging.info(f"[nl2sql] output preview: {out[:200]}")
        return QueryResponse(output=out)

    except HTTPException:
        raise
    except Exception as e:
        tb = traceback.format_exc()
        logging.error(f"[nl2sql] ERROR: {e}\n{tb}")
        # 返回精简的错误类型+信息，控制台有完整栈
        raise HTTPException(status_code=500, detail=f"Agent error: {e.__class__.__name__}: {str(e)[:400]}")

if __name__ == "__main__":
    logging.info("Starting FastAPI server on http://0.0.0.0:8001 ...")
    uvicorn.run("agent_mod:app", host="0.0.0.0", port=8001, reload=True)
    logging.info("Server started successfully and is running on port 8001.")


