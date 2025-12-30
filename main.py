# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/main.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1
#

# 声明：本代码仅供学习和研究目的使用。使用者应遵守以下原则：
# 1. 不得用于任何商业用途。
# 2. 使用时应遵守目标平台的使用条款和robots.txt规则。
# 3. 不得进行大规模爬取或对平台造成运营干扰。
# 4. 应合理控制请求频率，避免给目标平台带来不必要的负担。
# 5. 不得用于任何非法或不当的用途。
#
# 详细许可条款请参阅项目根目录下的LICENSE文件。
# 使用本代码即表示您同意遵守上述原则和LICENSE中的所有条款。


import asyncio
from typing import Optional, Type
import os
import json
import re
import httpx

import cmd_arg
import config
from database import db
from base.base_crawler import AbstractCrawler
from media_platform.xhs import XiaoHongShuCrawler
from tools.async_file_writer import AsyncFileWriter
from var import crawler_type_var


class CrawlerFactory:
    CRAWLERS: dict[str, Type[AbstractCrawler]] = {
        "xhs": XiaoHongShuCrawler,
    }

    @staticmethod
    def create_crawler(platform: str) -> AbstractCrawler:
        crawler_class = CrawlerFactory.CRAWLERS.get(platform)
        if not crawler_class:
            supported = ", ".join(sorted(CrawlerFactory.CRAWLERS))
            raise ValueError(f"Invalid media platform: {platform!r}. Supported: {supported}")
        return crawler_class()


crawler: Optional[AbstractCrawler] = None


def _flush_excel_if_needed() -> None:
    if config.SAVE_DATA_OPTION != "excel":
        return

    try:
        from store.excel_store_base import ExcelStoreBase

        ExcelStoreBase.flush_all()
        print("[Main] Excel files saved successfully")
    except Exception as e:
        print(f"[Main] Error flushing Excel data: {e}")


async def _generate_wordcloud_if_needed() -> None:
    if config.SAVE_DATA_OPTION != "json" or not config.ENABLE_GET_WORDCLOUD:
        return

    try:
        file_writer = AsyncFileWriter(
            platform=config.PLATFORM,
            crawler_type=crawler_type_var.get(),
        )
        await file_writer.generate_wordcloud_from_comments()
    except Exception as e:
        print(f"[Main] Error generating wordcloud: {e}")


async def main() -> None:
    global crawler

    args = await cmd_arg.parse_cmd()
    if args.init_db:
        await db.init_db(args.init_db)
        print(f"Database {args.init_db} initialized successfully.")
        return

    try:
        from var import request_start_time_var, request_keyword_var
        from datetime import datetime
        now = datetime.now()
        hh = str(now.hour).zfill(2)
        mm = str(now.minute).zfill(2)
        mon = str(now.month).zfill(2)
        day = str(now.day).zfill(2)
        # 原始格式：HH:MM_MM/DD（用于显示）；文件名将进行合法字符转换
        request_start_time_var.set(f"{hh}:{mm}_{mon}/{day}")
        try:
            first_kw = ""
            if getattr(config, "KEYWORDS", ""):
                parts = [i.strip() for i in str(config.KEYWORDS).split(",") if i.strip()]
                if parts:
                    first_kw = parts[0]
            request_keyword_var.set(first_kw)
        except Exception:
            pass
    except Exception:
        pass
    async def _expand_keywords_if_needed() -> None:
        if config.CRAWLER_TYPE != "search":
            return
        api_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("DEEPSEEK_APIKEY") or os.environ.get("DEEPSEEK_KEY")
        if not api_key:
            def _detect_category(s: str) -> str:
                t = s.lower()
                if any(k in t for k in ["app", "软件", "saas", "订阅"]):
                    return "software"
                return "hardware"
            def _heuristic_expand(s: str) -> list[str]:
                c = _detect_category(s)
                if c == "software":
                    return [f"{s} 值不值得订阅", f"{s} 会员价格", f"{s} 续费", f"{s} Bug 反馈", f"{s} 使用体验", f"{s} 功能对比", f"{s} 隐私与权限", f"{s} 更新日志", f"{s} 性价比", f"{s} 替代品"]
                else:
                    return [f"{s} 值不值得买", f"{s} 做工质量", f"{s} 续航评测", f"{s} 售后服务", f"{s} 开箱测评", f"{s} 缺点吐槽", f"{s} 对比评测", f"{s} 真实体验", f"{s} 价格走势", f"{s} 保修政策"]
            items = [i.strip() for i in config.KEYWORDS.split(",") if i.strip()]
            expanded = []
            for it in items:
                expanded.extend(_heuristic_expand(it))
            expanded = expanded[:5]
            merged = list(dict.fromkeys(items + expanded))
            config.KEYWORDS = ",".join(merged)
            return
        base = os.environ.get("DEEPSEEK_API_BASE", "https://api.deepseek.com")
        model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
        items = [i.strip() for i in config.KEYWORDS.split(",") if i.strip()]
        merged_all: list[str] = []
        system_prompt = """你是一名「用户反馈调研专家」，专门负责将一个产品名拆解为
适合在小红书、微博、知乎等社交媒体平台搜索的【真实用户反馈搜索 query】。
你的目标不是做产品介绍，而是帮助我最大程度搜集“真实体验、真实评价、真实吐槽”。

───────────────
【任务】
输入一个【产品名】，生成 5 条可直接用于社交媒体搜索的 query。

───────────────
【边界约束（硬性）】
以下内容在任何情况下都不允许出现在输出中：
- 官方功能介绍式表达
- 宣传、营销、安利语气
- 抽象空泛评价（如：很强、很全面、很专业）
- SEO 关键词堆砌风格
所有 query 必须是「普通用户真的会这样搜索的说法」，自然、口语化。

───────────────
【覆盖分配（6条各占一类，语义不得重复）】
你必须严格生成以下 5 类 query（每类 1 条，共 5 条）：
1) 使用体验：围绕“使用体验/感受/上手体验”
2) 评价决策：围绕“好不好用/值不值得/推荐吗”（任选其一，但要像真实搜索）
3) 缺点吐槽：围绕“缺点/问题/坑/避雷/踩坑”（至少包含其中一个词）
4) 场景人群：围绕“适合谁/适用场景/新手能用吗”
5) 对比替代：围绕“对比/平替/替代/竞品”（至少包含其中一个词）

注意：
- 5 条必须语义互异，禁止同义改写式重复
- 尽量使用社交媒体常见搜索表达（如：真实测评、避雷、踩坑、值不值得、平替、对比）
- 每条尽量短（约 10–18 个字，且必须包含产品名；第1条除外）
- 仅输出JSON，格式：{"queries": ["q1", "q2", ...]}"""
        for kw in items:
            user_prompt = f"""输入产品名：{kw}

请严格按规则输出 5 条 query（每行一条，不要编号，不要解释）。"""
            payload = {"model": model, "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}], "temperature": 0.7}
            queries = []
            try:
                async with httpx.AsyncClient(timeout=20) as client:
                    r = await client.post(f"{base}/chat/completions", headers={"Authorization": f"Bearer {api_key}"}, json=payload)
                data = r.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                obj = None
                try:
                    obj = json.loads(content)
                except Exception:
                    m = re.search(r"\{[\s\S]*\}", content)
                    if m:
                        try:
                            obj = json.loads(m.group(0))
                        except Exception:
                            obj = None
                if isinstance(obj, dict):
                    q = obj.get("queries")
                    if isinstance(q, list):
                        queries = [str(i).strip() for i in q if isinstance(i, str) and i.strip()]
            except Exception:
                queries = []
            combo = [kw] + queries
            for x in combo:
                if x not in merged_all:
                    merged_all.append(x)
        if merged_all:
            config.KEYWORDS = ",".join(merged_all)

    # 初始化任务计划
    try:
        from tools.utils import utils as _u
        import json as _json
        _u.logger.info('[EVENT] ' + _json.dumps({
            "stage":"plan",
            "target_pages": config.CRAWLER_MAX_NOTES_COUNT if hasattr(config, 'CRAWLER_MAX_NOTES_COUNT') else None,
            "per_note_comment_limit": config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES if hasattr(config, 'CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES') else None,
            "concurrency": config.MAX_CONCURRENCY_NUM if hasattr(config, 'MAX_CONCURRENCY_NUM') else None,
            "total_comments": (config.CRAWLER_MAX_NOTES_COUNT or 0) * (config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES or 0) if hasattr(config, 'CRAWLER_MAX_NOTES_COUNT') and hasattr(config, 'CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES') else None
        }))
    except Exception:
        pass

    try:
        from tools.utils import utils as _u
        import json as _json
        _u.logger.info('[EVENT] ' + _json.dumps({"stage":"expand_keywords","status":"start"}))
    except Exception:
        pass
    await _expand_keywords_if_needed()
    try:
        from tools.utils import utils as _u
        import json as _json
        _u.logger.info('[EVENT] ' + _json.dumps({"stage":"expand_keywords","status":"end","count": len([i.strip() for i in config.KEYWORDS.split(',') if i.strip()])}))
    except Exception:
        pass
    crawler = CrawlerFactory.create_crawler(platform=config.PLATFORM)
    try:
        from tools.utils import utils as _u
        import json as _json
        _u.logger.info('[EVENT] ' + _json.dumps({"stage":"crawl","type":"notes","status":"start"}))
    except Exception:
        pass
    await crawler.start()
    try:
        from tools.utils import utils as _u
        import json as _json
        _u.logger.info('[EVENT] ' + _json.dumps({"stage":"crawl","type":"notes","status":"end"}))
    except Exception:
        pass

    _flush_excel_if_needed()

    # Generate wordcloud after crawling is complete
    # Only for JSON save mode
    await _generate_wordcloud_if_needed()
    if config.SAVE_DATA_OPTION in ("json", "jsonl") and getattr(config, "ENABLE_ANALYSIS_AGENT", False):
        try:
            from tools.analysis_agent import generate_feedback_report
            try:
                from tools.utils import utils as _u
                import json as _json
                _u.logger.info('[EVENT] ' + _json.dumps({"stage":"report","status":"start"}))
            except Exception:
                pass
            
            # Debug logging
            try:
                from var import request_keyword_var
                from tools.utils import utils as _u
                kw_val = request_keyword_var.get()
                _u.logger.info(f"[Main] Generating report. Keyword: {kw_val}")
            except Exception:
                pass
                
            generate_feedback_report(platform=config.PLATFORM, crawler_type=crawler_type_var.get())
        except Exception as e:
            print(f"[Main] 分析Agent生成报告失败: {e}")


async def async_cleanup() -> None:
    global crawler
    if crawler:
        if getattr(crawler, "cdp_manager", None):
            try:
                await crawler.cdp_manager.cleanup(force=True)
            except Exception as e:
                error_msg = str(e).lower()
                if "closed" not in error_msg and "disconnected" not in error_msg:
                    print(f"[Main] 清理CDP浏览器时出错: {e}")

        elif getattr(crawler, "browser_context", None):
            try:
                await crawler.browser_context.close()
            except Exception as e:
                error_msg = str(e).lower()
                if "closed" not in error_msg and "disconnected" not in error_msg:
                    print(f"[Main] 关闭浏览器上下文时出错: {e}")

    if config.SAVE_DATA_OPTION in ("db", "sqlite"):
        pass
        # await db.close()

if __name__ == "__main__":
    from tools.app_runner import run

    def _force_stop() -> None:
        c = crawler
        if not c:
            return
        cdp_manager = getattr(c, "cdp_manager", None)
        launcher = getattr(cdp_manager, "launcher", None)
        if not launcher:
            return
        try:
            launcher.cleanup()
        except Exception:
            pass

    run(main, async_cleanup, cleanup_timeout_seconds=15.0, on_first_interrupt=_force_stop)
