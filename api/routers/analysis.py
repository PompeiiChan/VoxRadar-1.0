# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1
#

from fastapi import APIRouter, HTTPException
from typing import Optional

from tools.analysis_agent import generate_feedback_report, generate_feedback_report_from_paths
from ..services.crawler_manager import crawler_manager

router = APIRouter(prefix="/analysis", tags=["analysis"])


@router.post("/run")
async def run_analysis(platform: str = "xhs", crawler_type: str = "search") -> dict:
    """
    仅使用现有 JSONL 数据生成 AI 分析报告，不重新爬取
    """
    # 广播开始事件到日志队列
    entry = crawler_manager._create_log_entry("[EVENT] " + '{"stage":"report","status":"start"}', level="info")
    await crawler_manager._push_log(entry)

    out_path: Optional[str] = generate_feedback_report(platform=platform, crawler_type=crawler_type)
    rel_path = ""
    if out_path:
        # 将绝对路径转换为相对 data/ 路径，供前端下载
        import os
        try:
            idx = out_path.rfind("data/")
            rel_path = out_path[idx + len("data/"):] if idx != -1 else out_path
        except Exception:
            rel_path = out_path

        # 广播保存事件与友好日志
        entry2 = crawler_manager._create_log_entry(f"[AnalysisAgent] Report saved: {out_path}", level="success")
        await crawler_manager._push_log(entry2)
        entry3 = crawler_manager._create_log_entry("[EVENT] " + f'{{"stage":"report","status":"saved","path":"{out_path}"}}', level="info")
        await crawler_manager._push_log(entry3)
    else:
        entry_err = crawler_manager._create_log_entry("[AnalysisAgent] Report generation failed (empty content or missing API key)", level="error")
        await crawler_manager._push_log(entry_err)

    return {"ok": True, "path": rel_path}

@router.post("/run_paths")
async def run_analysis_from_paths(
    comments_path: str,
    contents_path: str,
    out_dir: Optional[str] = None,
) -> dict:
    """
    直接使用提供的 JSONL 文件路径生成 AI 分析报告
    - comments_path: 评论数据 JSONL 路径
    - contents_path: 帖子内容 JSONL 路径
    - out_dir: 报告输出目录（可选），默认写入 data/xhs/reports
    """
    if not comments_path or not contents_path:
        raise HTTPException(status_code=400, detail="comments_path 和 contents_path 为必填参数")

    # 广播开始事件到日志队列
    entry = crawler_manager._create_log_entry("[EVENT] " + '{"stage":"report","status":"start"}', level="info")
    await crawler_manager._push_log(entry)

    # 默认输出目录：/Users/.../data/xhs/reports
    default_out_dir = "/Users/pompeiichan/Desktop/评论区爬虫/data/xhs/reports"
    out_path: Optional[str] = generate_feedback_report_from_paths(
        comments_path=comments_path,
        contents_path=contents_path,
        out_dir=out_dir or default_out_dir,
    )

    rel_path = ""
    if out_path:
        import os
        try:
            idx = out_path.rfind("data/")
            rel_path = out_path[idx + len("data/"):] if idx != -1 else out_path
        except Exception:
            rel_path = out_path

        entry2 = crawler_manager._create_log_entry(f"[AnalysisAgent] Report saved: {out_path}", level="success")
        await crawler_manager._push_log(entry2)
        entry3 = crawler_manager._create_log_entry("[EVENT] " + f'{{"stage":"report","status":"saved","path":"{out_path}"}}', level="info")
        await crawler_manager._push_log(entry3)
    else:
        entry_err = crawler_manager._create_log_entry("[AnalysisAgent] Report generation failed (empty content or missing API key)", level="error")
        await crawler_manager._push_log(entry_err)

    return {"ok": True, "path": rel_path}
