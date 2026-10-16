from typing import Literal, Optional
from pydantic import BaseModel, Field

ActionType = Literal["navigate", "click", "type", "press_key", "wait", "ask_user", "finish", "tool", "upload",
                   "scroll", "select", "reload"]

class AgentAction(BaseModel):
    thought: str = Field(description="Raciocínio conciso sobre o que vê e o que fará a seguir")
    action_type: ActionType
    url: Optional[str] = None
    element_id: Optional[int] = None
    text_content: Optional[str] = None
    reason: Optional[str] = None
    tool: Optional[str] = Field(default=None, description="Nome da ferramenta local (ex.: fs.read_file)")
    args: Optional[dict] = Field(default=None, description="Argumentos da ferramenta, validados pelo params_model")
