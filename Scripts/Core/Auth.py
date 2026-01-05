"""
认证信息模型
"""
from pydantic import BaseModel


class AuthInfo(BaseModel):
    """认证信息模型"""
    token: str
    name: str

