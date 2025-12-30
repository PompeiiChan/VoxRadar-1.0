# -*- coding: utf-8 -*-
from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

from ..services.settings_manager import settings_manager

router = APIRouter(prefix="/settings", tags=["settings"])


class LMSettingsIn(BaseModel):
    api_key: Optional[str] = Field(default=None)
    api_base: Optional[str] = Field(default=None)
    model: Optional[str] = Field(default=None)
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(default=None, ge=1, le=8192)

class AccountSettingsIn(BaseModel):
    username: Optional[str] = Field(default=None, max_length=64)
    email: Optional[str] = Field(default=None, max_length=128)
    avatar_url: Optional[str] = Field(default=None, max_length=256)

class PromptIn(BaseModel):
    text: Optional[str] = Field(default=None)


@router.get("/lm")
async def get_lm_settings() -> Dict[str, Any]:
    lm = settings_manager.get_lm()
    return {
        "api_key_masked": settings_manager.mask_key(lm.get("api_key") or ""),
        "api_base": lm.get("api_base"),
        "model": lm.get("model"),
        "temperature": lm.get("temperature"),
        "max_tokens": lm.get("max_tokens"),
    }


@router.post("/lm")
async def set_lm_settings(payload: LMSettingsIn) -> Dict[str, Any]:
    settings_manager.set_lm(
        api_key=payload.api_key,
        api_base=payload.api_base,
        model=payload.model,
        temperature=payload.temperature,
        max_tokens=payload.max_tokens,
    )
    lm = settings_manager.get_lm()
    return {
        "ok": True,
        "api_key_masked": settings_manager.mask_key(lm.get("api_key") or ""),
        "api_base": lm.get("api_base"),
        "model": lm.get("model"),
        "temperature": lm.get("temperature"),
        "max_tokens": lm.get("max_tokens"),
    }

@router.get("/account")
async def get_account_settings() -> Dict[str, Any]:
    acc = settings_manager.get_account()
    return {
        "username": acc.get("username") or "",
        "email": acc.get("email") or "",
        "avatar_url": acc.get("avatar_url") or "",
    }

@router.post("/account")
async def set_account_settings(payload: AccountSettingsIn) -> Dict[str, Any]:
    settings_manager.set_account(
        username=payload.username,
        email=payload.email,
        avatar_url=payload.avatar_url,
    )
    acc = settings_manager.get_account()
    return {
        "ok": True,
        "username": acc.get("username") or "",
        "email": acc.get("email") or "",
        "avatar_url": acc.get("avatar_url") or "",
    }

@router.get("/prompt")
async def get_prompt_settings() -> Dict[str, Any]:
    return {"text": settings_manager.get_prompt()}

@router.post("/prompt")
async def set_prompt_settings(payload: PromptIn) -> Dict[str, Any]:
    settings_manager.set_prompt(payload.text)
    return {"ok": True, "text": settings_manager.get_prompt()}
