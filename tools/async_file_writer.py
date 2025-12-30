# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/tools/async_file_writer.py
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
import csv
import json
import os
import pathlib
from typing import Dict, List
import aiofiles
import config
from tools.utils import utils
from tools.words import AsyncWordCloudGenerator

class AsyncFileWriter:
    def __init__(self, platform: str, crawler_type: str):
        self.lock = asyncio.Lock()
        self.platform = platform
        self.crawler_type = crawler_type
        self.wordcloud_generator = AsyncWordCloudGenerator() if config.ENABLE_GET_WORDCLOUD else None
        self._jsonl_prefix: str | None = None

    def _get_file_path(self, file_type: str, item_type: str) -> str:
        base_path = f"data/{self.platform}/{file_type}"
        
        # 如果是 JSONL，并且有关键词，则按关键词创建子文件夹
        if file_type == "jsonl":
            from datetime import datetime
            from var import request_keyword_var, source_keyword_var, request_start_time_var
            
            # 1. 确定目录：如果有关键词，建立子文件夹
            kw = request_keyword_var.get() or source_keyword_var.get()
            if kw and kw.strip():
                # 安全清理关键词，避免路径非法字符
                safe_kw = "".join(c for c in kw if c.isalnum() or c in (' ', '-', '_')).strip()
                if safe_kw:
                    base_path = f"data/{self.platform}/{file_type}/{safe_kw}"
            
            pathlib.Path(base_path).mkdir(parents=True, exist_ok=True)
            
            # 2. 确定批次前缀（仅初始化一次）：关键词 + 任务开始时间（HH:MM_MM/DD）
            if not self._jsonl_prefix:
                # 获取任务开始时间（可能含有无效文件名字符）
                raw_ts = request_start_time_var.get()
                if not raw_ts or not raw_ts.strip():
                    now = datetime.now()
                    hh = str(now.hour).zfill(2)
                    mm = str(now.minute).zfill(2)
                    mon = str(now.month).zfill(2)
                    day = str(now.day).zfill(2)
                    raw_ts = f"{hh}:{mm}_{mon}/{day}"
                # 转换为合法文件名：替换 ":" 和 "/" 为 "-"
                safe_ts = raw_ts.replace(":", "-").replace("/", "-")
                base_kw = os.path.basename(base_path.rstrip("/"))
                prefix_kw = base_kw if base_kw not in ("jsonl", "") else "generic"
                self._jsonl_prefix = f"{prefix_kw}_{safe_ts}"
            # 3. 文件名：<prefix>_<item_type>.jsonl
            file_name = f"{self._jsonl_prefix}_{item_type}.{file_type}"
        else:
            pathlib.Path(base_path).mkdir(parents=True, exist_ok=True)
            file_name = f"{self.crawler_type}_{item_type}_{utils.get_current_date()}.{file_type}"
            
        return f"{base_path}/{file_name}"

    async def write_to_csv(self, item: Dict, item_type: str):
        file_path = self._get_file_path('csv', item_type)
        async with self.lock:
            file_exists = os.path.exists(file_path)
            async with aiofiles.open(file_path, 'a', newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(f, fieldnames=item.keys())
                if not file_exists or await f.tell() == 0:
                    await writer.writeheader()
                await writer.writerow(item)

    async def write_single_item_to_json(self, item: Dict, item_type: str):
        file_path = self._get_file_path('json', item_type)
        async with self.lock:
            existing_data = []
            if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
                    try:
                        content = await f.read()
                        if content:
                            existing_data = json.loads(content)
                        if not isinstance(existing_data, list):
                            existing_data = [existing_data]
                    except json.JSONDecodeError:
                        existing_data = []

            existing_data.append(item)

            async with aiofiles.open(file_path, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(existing_data, ensure_ascii=False, indent=4))

    async def write_to_jsonl(self, item: Dict, item_type: str):
        file_path = self._get_file_path('jsonl', item_type)
        async with self.lock:
            async with aiofiles.open(file_path, 'a', encoding='utf-8') as f:
                line = json.dumps(item, ensure_ascii=False)
                await f.write(line + "\n")

    async def generate_wordcloud_from_comments(self):
        """
        Generate wordcloud from comments data
        Only works when ENABLE_GET_WORDCLOUD and ENABLE_GET_COMMENTS are True
        """
        if not config.ENABLE_GET_WORDCLOUD or not config.ENABLE_GET_COMMENTS:
            return

        if not self.wordcloud_generator:
            return

        try:
            # Read comments from JSON/JSONL file
            comments_json_path = self._get_file_path('json', 'comments')
            comments_jsonl_path = self._get_file_path('jsonl', 'comments')
            comments_data = []
            if os.path.exists(comments_jsonl_path) and os.path.getsize(comments_jsonl_path) > 0:
                async with aiofiles.open(comments_jsonl_path, 'r', encoding='utf-8') as f:
                    async for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                            if isinstance(obj, dict):
                                comments_data.append(obj)
                        except json.JSONDecodeError:
                            continue
            elif os.path.exists(comments_json_path) and os.path.getsize(comments_json_path) > 0:
                async with aiofiles.open(comments_json_path, 'r', encoding='utf-8') as f:
                    content = await f.read()
                    if content:
                        arr = json.loads(content)
                        if isinstance(arr, list):
                            comments_data = arr
                        elif isinstance(arr, dict):
                            comments_data = [arr]
            else:
                utils.logger.info(f"[AsyncFileWriter.generate_wordcloud_from_comments] No comments file found at {comments_json_path} or {comments_jsonl_path}")
                return

            # Filter comments data to only include 'content' field
            # Handle different comment data structures across platforms
            filtered_data = []
            for comment in comments_data:
                if isinstance(comment, dict):
                    # Try different possible content field names
                    content_text = comment.get('content') or comment.get('comment_text') or comment.get('text') or ''
                    if content_text:
                        filtered_data.append({'content': content_text})

            if not filtered_data:
                utils.logger.info(f"[AsyncFileWriter.generate_wordcloud_from_comments] No valid comment content found")
                return

            # Generate wordcloud
            words_base_path = f"data/{self.platform}/words"
            pathlib.Path(words_base_path).mkdir(parents=True, exist_ok=True)
            words_file_prefix = f"{words_base_path}/{self.crawler_type}_comments_{utils.get_current_date()}"

            utils.logger.info(f"[AsyncFileWriter.generate_wordcloud_from_comments] Generating wordcloud from {len(filtered_data)} comments")
            await self.wordcloud_generator.generate_word_frequency_and_cloud(filtered_data, words_file_prefix)
            utils.logger.info(f"[AsyncFileWriter.generate_wordcloud_from_comments] Wordcloud generated successfully at {words_file_prefix}")

        except Exception as e:
            utils.logger.error(f"[AsyncFileWriter.generate_wordcloud_from_comments] Error generating wordcloud: {e}")
