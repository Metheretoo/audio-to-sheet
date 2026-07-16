from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse
import httpx
import json
import asyncio

app = FastAPI()

LM_STUDIO_URL = "http://127.0.0.1:1234/v1/chat/completions"


# ----------------------------
# STREAM OpenAI-compatible
# ----------------------------
async def stream_openai(body):

    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream(
            "POST",
            LM_STUDIO_URL,
            json=body,
            headers={"Content-Type": "application/json"},
        ) as r:

            # buffer JSON line-based (OpenAI style SSE)
            async for line in r.aiter_lines():

                if not line:
                    continue

                # LM Studio peut envoyer "data: {...}" ou brut JSON
                if line.startswith("data: "):
                    line = line[6:]

                if line == "[DONE]":
                    yield "data: [DONE]\n\n"
                    break

                try:
                    chunk = json.loads(line)
                except Exception:
                    continue

                # Extraction OpenAI delta format
                try:
                    delta = chunk["choices"][0].get("delta", {})
                    content = delta.get("content", "")

                    if content:
                        payload = {
                            "id": chunk.get("id", "chatcmpl-proxy"),
                            "object": "chat.completion.chunk",
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {
                                        "content": content
                                    },
                                    "finish_reason": None
                                }
                            ]
                        }

                        yield f"data: {json.dumps(payload)}\n\n"

                except Exception:
                    continue

    # fin propre OpenAI
    yield "data: [DONE]\n\n"


# ----------------------------
# ROUTE PRINCIPALE
# ----------------------------
@app.post("/v1/chat/completions")
async def chat_completions(request: Request):

    body = await request.json()

    stream = body.get("stream", False)

    if stream:
        return StreamingResponse(
            stream_openai(body),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            }
        )

    # NON STREAM fallback
    async with httpx.AsyncClient(timeout=None) as client:
        r = await client.post(LM_STUDIO_URL, json=body)
        return JSONResponse(content=r.json())


# ----------------------------
# HEALTHCHECK
# ----------------------------
@app.get("/health")
def health():
    return {"status": "ok"}