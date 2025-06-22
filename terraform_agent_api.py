import os
import mlflow
mlflow.openai.autolog()
from fastapi import FastAPI
from pydantic import BaseModel
from agents import Agent, function_tool, Runner, WebSearchTool
from agents.mcp import MCPServerStdio
import subprocess
import git
from typing import Dict, List
# import python_gitlab  # 실제 사용시 필요

# --- 기본 Repo/Branch 정보 ---
DEFAULT_REPO_URL = "https://gitlab.com/xxx/yyy.git"  # 실제 사용시 수정
DEFAULT_BRANCH = "main"
REPO_LOCAL_ROOT = os.path.expanduser("~/terraform")


# --- MCP Sequential Thinking 서버 연결 ---
mcp_server_sequential_thinking = MCPServerStdio(
    params={
        "command": "npx",
        "args": [
            "-y",
            "@smithery/cli@latest",
            "run",
            "@smithery-ai/server-sequential-thinking",
            "--key",
            "42600f9f-e75b-4323-9525-0b018540c4de"
        ]
    }
)

# --- MCP Terraform 서버 연결 ---
mcp_server_terraform = MCPServerStdio(
    params={
        "command": "npx",
        "args": [
            "-y",
            "@smithery/cli@latest",
            "run",
            "@hashicorp/terraform-mcp-server",
            "--key",
            "42600f9f-e75b-4323-9525-0b018540c4de"
        ]
    }
)

# --- MCP Filesystem 서버 연결 ---
filesystem_mcp_server = MCPServerStdio(
    params={
        "command": "npx",
        "args": [
            "-y",
            "@modelcontextprotocol/server-filesystem",
            REPO_LOCAL_ROOT
        ]
    }
)

# --- FunctionTool 구현 ---
@function_tool
def prepare_repo_for_task(
    repo_url: str = DEFAULT_REPO_URL,
    base_branch: str = DEFAULT_BRANCH,
    new_branch: str = "agent-task"
) -> str:
    """
    지정된 repo를 $HOME/terraform 하위에 clone(이미 있으면 pull)하고,
    main 브랜치를 최신으로 갱신 후, 새로운 브랜치로 체크아웃하여 작업 디렉토리 경로를 반환합니다.
    """
    os.makedirs(REPO_LOCAL_ROOT, exist_ok=True)
    repo_name = os.path.splitext(os.path.basename(repo_url))[0]
    repo_dir = os.path.join(REPO_LOCAL_ROOT, repo_name)
    if not os.path.exists(repo_dir):
        repo = git.Repo.clone_from(repo_url, repo_dir, branch=base_branch)
    else:
        repo = git.Repo(repo_dir)
        repo.git.checkout(base_branch)
        repo.remotes.origin.pull()
    # 항상 최신 main에서 새 브랜치 생성
    repo.git.checkout("-B", new_branch)
    return repo_dir

@function_tool
def terraform_plan(repo_dir: str) -> str:
    """terraform plan 실행 결과 요약 반환"""
    subprocess.run(["terraform", "init"], cwd=repo_dir, capture_output=True, text=True)
    plan = subprocess.run(["terraform", "plan"], cwd=repo_dir, capture_output=True, text=True)
    return plan.stdout

@function_tool
def terraform_apply(repo_dir: str, user_confirm: bool) -> str:
    """사용자 confirm 후 terraform apply 실행"""
    if not user_confirm:
        return "User did not confirm apply."
    result = subprocess.run(["terraform", "apply", "-auto-approve"], cwd=repo_dir, capture_output=True, text=True)
    return result.stdout if result.returncode == 0 else result.stderr

@function_tool
def create_merge_request(repo_dir: str, branch_name: str, gitlab_token: str, project_id: int) -> str:
    """새 브랜치로 checkout, 커밋, MR 생성 (예시)"""
    # TODO: 실제 python-gitlab 연동 필요
    return f"(예시) {branch_name} 브랜치에서 MR 생성됨"

# --- Agent 정의 ---
agent = Agent(
    name="Terraform DevOps Agent",
    instructions=(
        "You are an expert Terraform DevOps agent. Your primary goal is to manage AWS infrastructure by modifying Terraform code in a GitLab repository.\n\n"
        f"**Default Repository**: Always use `{DEFAULT_REPO_URL}` (main branch) unless the user specifies otherwise.\n\n"
        "**Core Workflow for ANY Task**:\n"
        "1.  **Prepare Workspace**: ALWAYS start by using the `prepare_repo_for_task` tool. This sets up a clean, up-to-date branch for the task.\n"
        "2.  **Analyze Code**: Use the **Filesystem MCP tools** (`listFiles`, `readFile`) to thoroughly understand the existing code structure in the workspace. Identify relevant files and existing resource definitions before making any changes.\n"
        "3.  **Plan Changes**: Use the **Sequential Thinking MCP** to reason through the necessary code modifications step-by-step.\n"
        "4.  **Modify Code**: Use the **Filesystem MCP tools** (`writeFile`, `patchFile`) to apply the planned modifications to the Terraform files.\n"
        "5.  **Verify with Plan**: Run the `terraform_plan` tool to validate your changes and see the execution plan. Summarize the plan for the user.\n"
        "6.  **Confirm & Apply**: NEVER run `terraform_apply` without explicit confirmation from the user.\n"
        "7.  **Create Merge Request**: After a successful apply, use the `create_merge_request` tool to finalize the task.\n\n"
        "**Error Handling**: If you encounter errors (e.g., from `terraform_plan`), use `WebSearchTool` to find solutions from the official Terraform documentation or other reliable sources, then correct the code and try again."
    ),
    tools=[prepare_repo_for_task, terraform_plan, terraform_apply, create_merge_request, WebSearchTool()],
    mcp_servers=[mcp_server_sequential_thinking, mcp_server_terraform, filesystem_mcp_server],
)

# --- 사용자별 history 캐시 ---
user_histories: Dict[str, List[dict]] = {}

def is_new_task(user_input: str) -> bool:
    # 간단한 규칙 기반 예시 (실전에서는 LLM 활용 가능)
    keywords = ["새로", "추가", "만들", "생성", "삭제", "초기화"]
    return any(k in user_input for k in keywords)

# --- FastAPI 서버 ---
app = FastAPI()

class CommandRequest(BaseModel):
    user_id: str  # 사용자 식별자(세션/토큰 등)
    user_input: str

@app.post("/terraform-agent")
async def terraform_agent(req: CommandRequest):
    history = user_histories.get(req.user_id, [])
    # 새로운 작업 판단
    if is_new_task(req.user_input):
        history = []  # history 초기화
    # history + user_input을 Agent에 전달
    result = await Runner.run(agent, req.user_input, history=history)
    # history에 user/agent 발화 추가
    history.append({"role": "user", "content": req.user_input})
    history.append({"role": "agent", "content": result.final_output})
    user_histories[req.user_id] = history
    return {"result": result.final_output}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("terraform_agent_api:app", host="0.0.0.0", port=8000, reload=True) 