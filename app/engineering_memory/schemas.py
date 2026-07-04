from typing import Any, Optional

from pydantic import BaseModel


class GitHubCommitInput(BaseModel):
    id: Optional[str] = None
    message: Optional[str] = None
    timestamp: Optional[str] = None
    url: Optional[str] = None
    author: Optional[dict[str, Any]] = None
    added: list[str] = []
    removed: list[str] = []
    modified: list[str] = []


class GitHubRepositoryInput(BaseModel):
    full_name: Optional[str] = None
    name: Optional[str] = None
    html_url: Optional[str] = None


class GitHubEngineeringMemoryInput(BaseModel):
    repository: Optional[GitHubRepositoryInput] = None
    ref: Optional[str] = None
    before: Optional[str] = None
    after: Optional[str] = None
    commits: list[GitHubCommitInput] = []
    head_commit: Optional[GitHubCommitInput] = None
    sender: Optional[dict[str, Any]] = None
    raw_event: dict[str, Any] = {}
