from fastapi import FastAPI
from pydantic import BaseModel
import asyncio

# OpenAI Agents SDK import (설치 필요: pip install openai-agents)
from agents import Agent, LocalShellTool, Runner

app = FastAPI()

# 1. Agent 정의 (LocalShellTool 추가)
agent = Agent(
    name="Shell Agent",
    instructions="You are an agent that can run shell commands on behalf of the user.",
    tools=[LocalShellTool()],
)

# 2. 요청 모델 정의
class CommandRequest(BaseModel):
    user_input: str

# 3. API 엔드포인트
@app.post("/run-shell")
async def run_shell(req: CommandRequest):
    result = await Runner.run(agent, req.user_input)
    return {"result": result.final_output}

# 4. 로컬 테스트용 엔트리포인트 (선택)
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("openai_agents_shell_api_example:app", host="0.0.0.0", port=8000, reload=True) 