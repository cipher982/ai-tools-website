import pydantic


class AITool(pydantic.BaseModel):
    url: str
    name: str
    categories: list[str]
    summary: str
    discovered_at: str
    last_updated: str
