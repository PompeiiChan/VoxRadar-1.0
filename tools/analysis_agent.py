import os
import json
import glob
from datetime import datetime
import httpx
import config
from api.services.settings_manager import settings_manager
from tools.utils import utils
import re
from collections import Counter
from tools.crawler_util import match_interact_info_count

def _to_int_count(v) -> int:
    try:
        if isinstance(v, (int, float)):
            return int(v)
        s = str(v or "").strip()
        if not s:
            return 0
        if "万" in s:
            try:
                base = float(s.replace("万", "").strip())
                return int(base * 10000)
            except Exception:
                pass
        return match_interact_info_count(s)
    except Exception:
        return 0

def _load_prompt(default_text: str) -> str:
    txt = settings_manager.get_prompt()
    if txt:
        return txt
    try:
        p = os.path.join("data", "system", "prompt.md")
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                t = f.read()
                if t.strip():
                    return t
    except Exception:
        pass
    return default_text

def _latest_file(dir_path: str, pattern: str) -> str | None:
    files = glob.glob(os.path.join(dir_path, pattern))
    if not files:
        return None
    files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return files[0]

def _latest_pair(dir_path: str, crawler_type: str) -> tuple[str | None, str | None]:
    """
    查找同一批次的 contents/comments 成对文件（递归）：
    - 新命名：<keyword>_<HH-MM>_<MM-DD>_contents.jsonl / ..._comments.jsonl
    - 兼容旧命名：<crawler_type>_contents_*.jsonl / <crawler_type>_comments_*.jsonl
    - 也支持扁平命名：contents.jsonl / comments.jsonl
    在 dir_path 下递归搜索，返回最近修改的一对文件路径。
    """
    cm_candidates: list[str] = []
    ct_candidates: list[str] = []
    for root, _, files in os.walk(dir_path):
        for fn in files:
            if not fn.lower().endswith(".jsonl"):
                continue
            p = os.path.join(root, fn)
            if fn.endswith("_comments.jsonl") or fn == "comments.jsonl" or re.match(rf"{re.escape(crawler_type)}_comments_.*\.jsonl$", fn):
                cm_candidates.append(p)
            if fn.endswith("_contents.jsonl") or fn == "contents.jsonl" or re.match(rf"{re.escape(crawler_type)}_contents_.*\.jsonl$", fn):
                ct_candidates.append(p)
    if not cm_candidates or not ct_candidates:
        return None, None
    def _base_key(fn: str) -> str:
        if fn.endswith("_comments.jsonl"):
            return fn[:-len("_comments.jsonl")]
        if fn.endswith("_contents.jsonl"):
            return fn[:-len("_contents.jsonl")]
        # 兼容扁平命名，使用目录名作为批次键
        return os.path.dirname(fn)
    cm_map = { _base_key(os.path.basename(p)): p for p in cm_candidates }
    ct_map = { _base_key(os.path.basename(p)): p for p in ct_candidates }
    inter_keys = [k for k in cm_map.keys() if k in ct_map]
    if inter_keys:
        inter_keys.sort(key=lambda k: max(os.path.getmtime(cm_map[k]), os.path.getmtime(ct_map[k])), reverse=True)
        k = inter_keys[0]
        return cm_map[k], ct_map[k]
    # 若无法通过同名键配对，退化为按修改时间选择最近的各一个
    cm_candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    ct_candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return (cm_candidates[0] if cm_candidates else None), (ct_candidates[0] if ct_candidates else None)

def _read_jsonl(path: str, limit: int) -> list[dict]:
    items: list[dict] = []
    if not path or not os.path.exists(path):
        return items
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            if len(items) >= limit:
                break
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    items.append(obj)
            except Exception:
                continue
    return items

def _build_contents_index(contents: list[dict]) -> dict[str, dict]:
    index: dict[str, dict] = {}
    for it in contents:
        nid = str(it.get("note_id", "")).strip()
        if not nid or nid in index:
            continue
        index[nid] = {
            "note_url": it.get("note_url", ""),
            "title": it.get("title", "") or it.get("desc", ""),
            "nickname": it.get("nickname", ""),
            "time_iso": it.get("time_iso", ""),
        }
    return index

def _classify(txt: str) -> str:
    t = txt or ""
    pos = ["好用", "方便", "省事", "稳定", "推荐", "喜欢", "满意", "提升效率", "赞", "不错", "可以", "值得"]
    neg = ["不好用", "崩溃", "用不了", "出错", "浪费", "退订", "卸载", "避雷", "糟糕", "垃圾", "坑", "问题", "卡顿", "闪退", "慢", "麻烦", "差", "失望"]
    for w in neg:
        if w in t:
            return "bad"
    for w in pos:
        if w in t:
            return "good"
    return "neutral"

def _top_tokens(items: list[str], topn: int = 5) -> list[str]:
    sw = {"的", "了", "是", "在", "就", "也", "都", "和", "很", "不", "这个", "那个", "我", "你", "他", "她", "它", "呢", "吧", "啊", "嘛"}
    cnt = Counter()
    for t in items:
        for m in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,}", t or ""):
            if m in sw:
                continue
            cnt[m] += 1
    return [w for w, _ in cnt.most_common(topn)]

def _offline_report(comments: list[dict], contents_index: dict[str, dict]) -> str:
    total = len(comments)
    nid_set = set()
    goods = []
    bads = []
    neutrals = []
    for c in comments:
        nid = str(c.get("note_id") or "")
        if nid:
            nid_set.add(nid)
        txt = str(c.get("content") or c.get("content_norm") or c.get("content") or "")
        cl = _classify(txt)
        if cl == "good":
            goods.append(c)
        elif cl == "bad":
            bads.append(c)
        else:
            neutrals.append(c)
    goods.sort(key=lambda o: _to_int_count(o.get("like_count")), reverse=True)
    bads.sort(key=lambda o: _to_int_count(o.get("like_count")), reverse=True)
    def _fmt_quote(arr: list[dict], k: int) -> list[str]:
        out = []
        for it in arr[:k]:
            cid = it.get("comment_id") or it.get("id") or ""
            nid = str(it.get("note_id") or "")
            url = contents_index.get(nid, {}).get("note_url", "")
            txt = str(it.get("content") or it.get("content_norm") or "")
            txt = txt.strip()
            if len(txt) > 120:
                txt = txt[:120] + "..."
            tag = f"[#${cid}]" if cid else ""
            if url:
                out.append(f"- {tag} {txt} （{url}）")
            else:
                out.append(f"- {tag} {txt}")
        return out
    tokens = _top_tokens([str(c.get("content") or c.get("content_norm") or "") for c in comments], topn=5)
    good_quotes = "\n".join(_fmt_quote(goods, 5))
    bad_quotes = "\n".join(_fmt_quote(bads, 5))
    return (
        "# 用户反馈分析报告\n\n"
        "## 1. 核心结论速览\n"
        f"- 数据量：评论 {total} 条，覆盖笔记 {len(nid_set)} 条\n"
        f"- 体验较好样本：{len(goods)} 条；体验不好样本：{len(bads)} 条\n\n"
        "## 2. “体验较好”的场景拆解\n"
        f"{good_quotes or '- 暂无明显“体验较好”的样本'}\n\n"
        "## 3. “体验不好”的场景拆解\n"
        f"{bad_quotes or '- 暂无明显“体验不好”的样本'}\n\n"
        "## 5. 用户故事与卡点\n"
        "- 离线模式生成基础版报告：基于关键词与点赞数的启发式提炼\n"
        "- 若需更详细的场景卡与证据链，请配置有效的模型密钥\n\n"
        "## 6. 高频词 TOP5\n"
        f"- {(' / '.join(tokens) if tokens else '无')}\n"
    )

def generate_feedback_report(platform: str, crawler_type: str) -> str | None:
    # 尝试从 ContextVar 获取关键词，定位子文件夹
    from var import request_keyword_var
    kw = request_keyword_var.get()
    
    base_dir = os.path.join("data", platform)
    target_dir = os.path.join(base_dir, "jsonl")
    
    # 若有关键词，优先进入关键词子目录
    if kw and kw.strip():
        safe_kw = "".join(c for c in kw if c.isalnum() or c in (' ', '-', '_')).strip()
        if safe_kw:
            kw_dir = os.path.join(target_dir, safe_kw)
            if os.path.exists(kw_dir):
                target_dir = kw_dir
    
    utils.logger.info(f"[AnalysisAgent] Searching data in: {target_dir}")

    # 在目标目录下查找 contents.jsonl / comments.jsonl
    # 优先找精确匹配（新逻辑），找不到再回退通配符（兼容旧逻辑）
    comments_path = os.path.join(target_dir, "comments.jsonl")
    contents_path = os.path.join(target_dir, "contents.jsonl")
    if not os.path.exists(comments_path) or not os.path.exists(contents_path):
        cp, tp = _latest_pair(target_dir, crawler_type)
        comments_path = cp or comments_path
        contents_path = tp or contents_path
    if not os.path.exists(comments_path) or not os.path.exists(contents_path):
        utils.logger.warning(f"[AnalysisAgent] Data files not found: {comments_path} or {contents_path}")
        return None
    comments = _read_jsonl(comments_path, config.ANALYSIS_MAX_LINES)
    contents = _read_jsonl(contents_path, config.ANALYSIS_MAX_LINES)
    def __to_int_count(v) -> int:
        try:
            if isinstance(v, (int, float)):
                return int(v)
            s = str(v or "").strip()
            if not s:
                return 0
            if "万" in s:
                try:
                    base = float(s.replace("万", "").strip())
                    return int(base * 10000)
                except Exception:
                    pass
            return match_interact_info_count(s)
        except Exception:
            return 0
    def _minify_comment(obj: dict, content_max_len: int = 260) -> dict:
        cid = obj.get("comment_id") or obj.get("id")
        nid = obj.get("note_id") or obj.get("noteId") or obj.get("note_id_str")
        txt = obj.get("content_norm") or obj.get("content") or ""
        if isinstance(txt, str) and len(txt) > content_max_len:
            txt = txt[:content_max_len]
        like = obj.get("like_count")
        try:
            like = int(like) if like is not None else None
        except Exception:
            like = None
        return {
            "comment_id": cid,
            "note_id": nid,
            "content": txt,
            "created_at_iso": obj.get("created_at_iso") or obj.get("time_iso") or "",
            "like_count": like,
            "source_url": obj.get("source_url") or obj.get("note_url") or ""
        }
    def _sample_comments(items: list[dict], total_limit: int = 200, per_note_limit: int = 5, content_max_len: int = 260) -> list[dict]:
        from collections import defaultdict
        groups = defaultdict(list)
        for it in items:
            nid = str(it.get("note_id") or it.get("noteId") or it.get("note_id_str") or "")
            groups[nid].append(it)
        picked = []
        for nid, arr in groups.items():
            arr.sort(key=lambda o: (__to_int_count(o.get("like_count")), str(o.get("created_at_iso") or "")), reverse=True)
            for it in arr[:per_note_limit]:
                picked.append(it)
                if len(picked) >= total_limit:
                    break
            if len(picked) >= total_limit:
                break
        if len(picked) < total_limit:
            rest = [it for sub in groups.values() for it in sub]
            rest.sort(key=lambda o: (__to_int_count(o.get("like_count")), str(o.get("created_at_iso") or "")), reverse=True)
            for it in rest:
                if len(picked) >= total_limit:
                    break
                if it not in picked:
                    picked.append(it)
        dedup = {}
        out = []
        for it in picked:
            cid = str(it.get("comment_id") or it.get("id") or "")
            if cid and cid in dedup:
                continue
            dedup[cid] = True
            out.append(_minify_comment(it, content_max_len))
        return out
    contents_index = _build_contents_index(contents)
    total_limit = min(config.ANALYSIS_MAX_LINES, 120)
    per_note_limit = 5
    content_max_len = 220
    comments = _sample_comments(comments, total_limit=total_limit, per_note_limit=per_note_limit, content_max_len=content_max_len)
    api_key = settings_manager.get_api_key()
    if (not api_key) or ("dummy" in str(api_key).lower()) or ("test" in str(api_key).lower()):
        utils.logger.warning("[AnalysisAgent] API key not found in settings")
        content = _offline_report(comments, contents_index)
        timestamp_dt = datetime.now().strftime("%Y%m%d%H%M")
        reports_dir = os.path.join(base_dir, "reports")
        os.makedirs(reports_dir, exist_ok=True)
        def _prefix_from_path(p: str) -> str | None:
            bn = os.path.basename(p or "")
            if bn.endswith("_comments.jsonl"):
                return bn[:-len("_comments.jsonl")]
            if bn.endswith("_contents.jsonl"):
                return bn[:-len("_contents.jsonl")]
            return None
        rpfx = _prefix_from_path(comments_path) or _prefix_from_path(contents_path)
        if not rpfx:
            from var import request_keyword_var
            kw = request_keyword_var.get() or ""
            safe_kw = "".join(c for c in kw if c.isalnum() or c in (' ', '-', '_')).strip() or "generic"
            rpfx = f"{safe_kw} {timestamp_dt}"
        out_path = os.path.join(reports_dir, f"{rpfx}_analysis.md")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(content or "")
        utils.logger.info(f"[AnalysisAgent] Report saved: {out_path}")
        try:
            from tools.utils import utils as _u
            import json as _json
            _u.logger.info('[EVENT] ' + _json.dumps({"stage":"report","status":"saved","path": out_path}))
        except Exception:
            pass
        return out_path
    lm = settings_manager.get_lm()
    base = (lm.get("api_base") or "https://api.deepseek.com")
    model = (lm.get("model") or "deepseek-chat")

    PROMPT_TEMPLATE = _load_prompt("""
你是一名资深产品经理 & 用户研究分析师，擅长把社交媒体（小红书/微博/知乎等）的零散用户反馈，
提炼成“以真实场景为主轴、可复核证据链、可行动”的用户反馈分析报告。

====================
【你的目标】
输出一份 Markdown 格式的《用户反馈分析报告》，让我一眼看懂：
1) 产品在哪些【真实场景】下用户觉得“体验较好”
2) 产品在哪些【真实场景】下用户觉得“体验不好”
3) 从用户发帖中提炼出：用户的【具体需求场景】与【需求点】（需求卡）
4) 输出高频词 TOP5（场景词/痛点词/动作词），帮助我快速抓到重点

====================
【input】
输入数据由两部分组成：

1) comments.jsonl：
- 格式：JSON Lines，每行一条评论记录
- 字段：
  - comment_id: 唯一评论ID
  - note_id: 所属笔记ID
  - content_norm: 已规范化的评论文本（若无则使用 content）
  - created_at_iso: ISO8601 时间
  - like_count: 点赞数（整数）
  - source_name: 来源平台（如：小红书）
  - source_url: 原帖链接（用于溯源跳转）
  - highlights: 可选，高亮片段数组。每个元素：
      { start: 整数, end: 整数, label: "使用体验|缺点吐槽|对比替代|…", insight_id: 可选 }
  - tags: 可选，标签数组（如：["使用体验","工作场景"]）
  - sentiment: 可选，{ label: positive|neutral|negative, score: 0.0–1.0 }

2) contents_index.json：
- 格式：字典，键为 note_id
- 值包含：{ note_url, title, nickname, time_iso }

处理规则：
- 始终使用 content_norm（若不存在再使用 content），禁止对文本做额外清洗，以保证与 highlights 偏移一致
- 当数据量较大时，输入已按点赞与时间采样（约 200–300 条），并保证 note_id 的多样性与每帖不超过 10 条评论
- 只基于输入数据进行分析；不得臆造或补充未给出的事实
- 需要溯源时，请引用 comment_id 与原文片段（必要时包含 start/end），并可附带 note_id 与 source_url

【output】
{{用户反馈文本}}

====================
【硬性要求：真实场景下的真实需求】
你提炼“需求”时必须使用以下句式（可微调措辞，但要保留结构要素）：
在【场景/触发】下，【某类用户】为了【完成某件事】，需要【能力/信息/保障】，
否则会【损失/风险/情绪/成本】；他们现在通常用【替代方案/绕路方式】凑合。

====================
【判定标准：体验较好 vs 体验不好（必须按此归类）】
A) “体验较好”判定（满足任意1-2条即可归入）：
- 明确表达好用/省事/稳定/够用/提升效率/推荐/愿意继续用
- 负面较少且不影响完成任务（小毛病但能用）

B) “体验不好”判定（满足任意1条就归入）：
- 明确表达劝退/崩溃/根本用不了/一直出错/浪费时间/退订/卸载/避雷
- 阻断任务完成（做不完、需要返工、结果不可用）
- 强烈负面情绪密集出现

====================
【分析步骤（先做再写，写的时候不必逐条描述过程）】
1) 过滤噪音：剔除明显广告/水评/无关内容（在报告里说明大致规则）
2) 抽取“场景”与“任务”：每条反馈识别用户当时在干什么、要完成什么
3) 按判定标准归类为：还行场景 / 很不好用场景（必要时可中性，但重点还是两类）
4) 对每个场景提炼：成功标准/卡点/代价/替代方案
5) 提炼需求卡：按“场景—任务—痛点—期望”输出，必须带证据链
6) 统计高频词：给出 TOP5（场景词/痛点词/动作词）

====================
【证据链要求（必须执行）】
- 所有关键结论都必须引用至少 2 条用户原话作为证据（短摘录即可）
- 摘录后标注该反馈的编号/ID（如果输入没有ID，就用你在报告中生成的序号如[#12]）
- 不能只写“用户觉得不好用”，必须指出发生在任务链路哪一步、造成什么代价

====================
【output格式（必须是 Markdown，按以下标题结构输出）】

# 用户反馈分析报告

## 1. 核心结论速览
- Top 5 体验较好的场景：（概括“为什么体验较好、解决了用户的什么痛点？”）
- Top 5 体验不好的场景：（概括“为什么不好用？用户的抱怨有哪些？”）
- 体验较好评级总量、体验不好评价总量（给出具体的数字）

## 2. “体验较好”的场景拆解
对每个“体验较好的场景”输出一张场景卡：
- 场景描述（何时何地为何用）
- 典型任务链路（1-2-3步即可）
- 成功标准（用户怎样算满意）
- 当前满足点（产品做对了什么）
- 可放大机会（守住优势/继续提升的方向）

## 3. “体验不好”的场景拆解
对每个“体验不好的场景”输出一张场景卡：
- 场景描述（何时何地为何用）
- 体验不好具体在哪一步（理解/操作/结果/反馈）
- 用户为这个“不好的体验”所付出的代价（时间/出错/情绪/金钱/信任）
- 用户替代方案/绕路方式（用户是如何凑合使用的？）

## 5. 用户故事与卡点
> 目标：把反馈提炼成“用户故事”，并定位用户在任务链路的断点，方便直接转为需求/PRD条目。
> 每条用户故事必须附证据链，避免拍脑袋。
对每条需求输出（建议 Top 5–8 条）：
- **用户故事（一句话）**：作为【用户类型】，我想在【场景】下【完成某任务】，以便【获得某结果/避免某损失】。
- **触发与使用情境**：用户为什么在这个时刻要用？（触发事件/约束条件）
- **关键卡点（断点定位）**：卡在【理解/操作/结果/反馈】哪一步？具体表现是什么？
- **用户代价**：因为这个卡点，用户付出了什么成本（时间/返工/出错/焦虑/钱/信任）
- **需求本体（用户真正要的）**：用户需要的是哪种能力/信息/保障（不要直接跳到功能方案）
- **成功标准（验收口径）**：如果解决了，用户会如何评价/行为会怎样变化？
- **优先级线索**：频次/强度/是否阻断（高/中/低）+ 简短依据
- **证据摘录**：2–4 条代表性用户原话（标注[#编号]）

## 6. 高频词 TOP5
- 场景词 TOP5：xxx / xxx / xxx / xxx / xxx（分别解释对应的场景含义）
- 痛点词 TOP5：xxx / xxx / xxx / xxx / xxx（分别解释对应的痛点含义）
- 动作词 TOP5：xxx / xxx / xxx / xxx / xxx（分别解释对应的真实任务诉求）
""")

    input_data = {
        "comments.jsonl": comments,
        "contents_index.json": contents_index
    }
    
    MAX_PROMPT_CHARS = int(os.environ.get("PROMPT_MAX_CHARS", "80000"))
    def _build_input_blob(ttl: int, pnl: int, cml: int) -> tuple[str, list[dict]]:
        cmts = _sample_comments(comments, total_limit=ttl, per_note_limit=pnl, content_max_len=cml)
        blob = json.dumps({"comments.jsonl": cmts, "contents_index.json": contents_index}, ensure_ascii=False)
        return blob, cmts
    blob, cmts = _build_input_blob(total_limit, per_note_limit, content_max_len)
    while len(blob) > MAX_PROMPT_CHARS and (total_limit > 60 or per_note_limit > 2 or content_max_len > 180):
        if per_note_limit > 2:
            per_note_limit -= 1
        elif total_limit > 60:
            total_limit = max(60, total_limit - 30)
        elif content_max_len > 180:
            content_max_len -= 20
        blob, cmts = _build_input_blob(total_limit, per_note_limit, content_max_len)
    final_prompt = PROMPT_TEMPLATE.replace("{{用户反馈文本}}", blob)
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": final_prompt}],
        "temperature": float(lm.get("temperature") or 0.1),
        "max_tokens": int(lm.get("max_tokens") or 4000),
    }
    
    try:
        from tools.utils import utils as _u
        import json as _json
        try:
            _u.logger.info('[EVENT] ' + _json.dumps({"stage":"report","status":"start"}))
        except Exception:
            pass
        with httpx.Client(timeout=int(os.environ.get("LM_TIMEOUT", "60"))) as client:
            r = client.post(f"{base}/chat/completions", headers={"Authorization": f"Bearer {api_key}"}, json=payload)
            r.raise_for_status()
        data = r.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    except Exception as e:
        utils.logger.error(f"[AnalysisAgent] API call failed: {e}")
        content = _offline_report(comments, contents_index)
    timestamp_dt = datetime.now().strftime("%Y%m%d%H%M")
    reports_dir = os.path.join(base_dir, "reports")
    os.makedirs(reports_dir, exist_ok=True)
    # 尝试从文件名推断批次前缀（关键词+时间）
    def _prefix_from_path(p: str) -> str | None:
        bn = os.path.basename(p or "")
        if bn.endswith("_comments.jsonl"):
            return bn[:-len("_comments.jsonl")]
        if bn.endswith("_contents.jsonl"):
            return bn[:-len("_contents.jsonl")]
        return None
    rpfx = _prefix_from_path(comments_path) or _prefix_from_path(contents_path)
    if not rpfx:
        # 若无新命名，使用关键词目录名作为前缀
        from var import request_keyword_var
        kw = request_keyword_var.get() or ""
        safe_kw = "".join(c for c in kw if c.isalnum() or c in (' ', '-', '_')).strip() or "generic"
        rpfx = f"{safe_kw} {timestamp_dt}"
    out_path = os.path.join(reports_dir, f"{rpfx}_analysis.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content or "")
    utils.logger.info(f"[AnalysisAgent] Report saved: {out_path}")
    try:
        from tools.utils import utils as _u
        import json as _json
        _u.logger.info('[EVENT] ' + _json.dumps({"stage":"report","status":"saved","path": out_path}))
    except Exception:
        pass
    return out_path

def generate_feedback_report_from_paths(comments_path: str, contents_path: str, out_dir: str | None = None) -> str | None:
    comments = _read_jsonl(comments_path or "", config.ANALYSIS_MAX_LINES)
    contents = _read_jsonl(contents_path or "", config.ANALYSIS_MAX_LINES)
    contents_index = _build_contents_index(contents)
    api_key = settings_manager.get_api_key()
    if (not api_key) or ("dummy" in str(api_key).lower()) or ("test" in str(api_key).lower()):
        content = _offline_report(comments, contents_index)
        timestamp_dt = datetime.now().strftime("%Y%m%d%H%M")
        if out_dir:
            reports_dir = out_dir
        else:
            try:
                base_dir = os.path.dirname(os.path.dirname(comments_path))
                reports_dir = os.path.join(base_dir, "reports")
            except Exception:
                reports_dir = os.path.join("data", "reports")
        os.makedirs(reports_dir, exist_ok=True)
        def _prefix_from_path(p: str) -> str | None:
            bn = os.path.basename(p or "")
            if bn.endswith("_comments.jsonl"):
                return bn[:-len("_comments.jsonl")]
            if bn.endswith("_contents.jsonl"):
                return bn[:-len("_contents.jsonl")]
            return None
        rpfx = _prefix_from_path(comments_path) or _prefix_from_path(contents_path)
        if not rpfx:
            try:
                kw = os.path.basename(os.path.dirname(comments_path or "")) or ""
                safe_kw = "".join(c for c in kw if c.isalnum() or c in (' ', '-', '_')).strip() or "generic"
                rpfx = f"{safe_kw} {timestamp_dt}"
            except Exception:
                rpfx = f"generic {timestamp_dt}"
        out_path = os.path.join(reports_dir, f"{rpfx}_analysis.md")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(content or "")
        utils.logger.info(f"[AnalysisAgent] Report saved: {out_path}")
        return out_path
    lm = settings_manager.get_lm()
    base = (lm.get("api_base") or "https://api.deepseek.com")
    model = (lm.get("model") or "deepseek-chat")
    PROMPT_TEMPLATE = _load_prompt("""
你是一名资深产品经理 & 用户研究分析师，擅长把社交媒体（小红书/微博/知乎等）的零散用户反馈，
提炼成“以真实场景为主轴、可复核证据链、可行动”的用户反馈分析报告。
【input】
{{用户反馈文本}}
""")
    def _minify_comment(obj: dict, content_max_len: int = 260) -> dict:
        cid = obj.get("comment_id") or obj.get("id")
        nid = obj.get("note_id") or obj.get("noteId") or obj.get("note_id_str")
        txt = obj.get("content_norm") or obj.get("content") or ""
        if isinstance(txt, str) and len(txt) > content_max_len:
            txt = txt[:content_max_len]
        like = obj.get("like_count")
        try:
            like = int(like) if like is not None else None
        except Exception:
            like = None
        return {
            "comment_id": cid,
            "note_id": nid,
            "content": txt,
            "created_at_iso": obj.get("created_at_iso") or obj.get("time_iso") or "",
            "like_count": like,
            "source_url": obj.get("source_url") or obj.get("note_url") or ""
        }
    def __to_int_count(v) -> int:
        try:
            if isinstance(v, (int, float)):
                return int(v)
            s = str(v or "").strip()
            if not s:
                return 0
            if "万" in s:
                try:
                    base = float(s.replace("万", "").strip())
                    return int(base * 10000)
                except Exception:
                    pass
            return match_interact_info_count(s)
        except Exception:
            return 0
    def _sample_comments(items: list[dict], total_limit: int = 200, per_note_limit: int = 5, content_max_len: int = 260) -> list[dict]:
        from collections import defaultdict
        groups = defaultdict(list)
        for it in items:
            nid = str(it.get("note_id") or it.get("noteId") or it.get("note_id_str") or "")
            groups[nid].append(it)
        picked = []
        for nid, arr in groups.items():
            arr.sort(key=lambda o: (__to_int_count(o.get("like_count")), str(o.get("created_at_iso") or "")), reverse=True)
            for it in arr[:per_note_limit]:
                picked.append(it)
                if len(picked) >= total_limit:
                    break
            if len(picked) >= total_limit:
                break
        if len(picked) < total_limit:
            rest = [it for sub in groups.values() for it in sub]
            rest.sort(key=lambda o: (__to_int_count(o.get("like_count")), str(o.get("created_at_iso") or "")), reverse=True)
            for it in rest:
                if len(picked) >= total_limit:
                    break
                if it not in picked:
                    picked.append(it)
        dedup = {}
        out = []
        for it in picked:
            cid = str(it.get("comment_id") or it.get("id") or "")
            if cid and cid in dedup:
                continue
            dedup[cid] = True
            out.append(_minify_comment(it))
        return out
    total_limit = min(config.ANALYSIS_MAX_LINES, 120)
    per_note_limit = 5
    content_max_len = 220
    comments = _sample_comments(comments, total_limit=total_limit, per_note_limit=per_note_limit, content_max_len=content_max_len)
    def _build_input_blob(ttl: int, pnl: int, cml: int) -> tuple[str, list[dict]]:
        cmts = _sample_comments(comments, total_limit=ttl, per_note_limit=pnl, content_max_len=cml)
        blob = json.dumps({"comments.jsonl": cmts, "contents_index.json": contents_index}, ensure_ascii=False)
        return blob, cmts
    MAX_PROMPT_CHARS = int(os.environ.get("PROMPT_MAX_CHARS", "80000"))
    blob, cmts = _build_input_blob(total_limit, per_note_limit, content_max_len)
    while len(blob) > MAX_PROMPT_CHARS and (total_limit > 60 or per_note_limit > 2 or content_max_len > 180):
        if per_note_limit > 2:
            per_note_limit -= 1
        elif total_limit > 60:
            total_limit = max(60, total_limit - 30)
        elif content_max_len > 180:
            content_max_len -= 20
        blob, cmts = _build_input_blob(total_limit, per_note_limit, content_max_len)
    final_prompt = PROMPT_TEMPLATE.replace("{{用户反馈文本}}", blob)
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": final_prompt}],
        "temperature": float(lm.get("temperature") or 0.1),
        "max_tokens": int(lm.get("max_tokens") or 4000),
    }
    try:
        with httpx.Client(timeout=int(os.environ.get("LM_TIMEOUT", "60"))) as client:
            r = client.post(f"{base}/chat/completions", headers={"Authorization": f"Bearer {api_key}"}, json=payload)
            r.raise_for_status()
        data = r.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    except Exception as e:
        utils.logger.error(f"[AnalysisAgent] API call failed (from_paths): {e}")
        content = _offline_report(comments, contents_index)
    timestamp_dt = datetime.now().strftime("%Y%m%d%H%M")
    if out_dir:
        reports_dir = out_dir
    else:
        try:
            base_dir = os.path.dirname(os.path.dirname(comments_path))
            reports_dir = os.path.join(base_dir, "reports")
        except Exception:
            reports_dir = os.path.join("data", "reports")
    os.makedirs(reports_dir, exist_ok=True)
    # 批次前缀：优先从文件名提取（<kw> <yyyyMMddHHmm>），否则从父目录关键词+当前时间
    def _prefix_from_path(p: str) -> str | None:
        bn = os.path.basename(p or "")
        if bn.endswith("_comments.jsonl"):
            return bn[:-len("_comments.jsonl")]
        if bn.endswith("_contents.jsonl"):
            return bn[:-len("_contents.jsonl")]
        return None
    rpfx = _prefix_from_path(comments_path) or _prefix_from_path(contents_path)
    if not rpfx:
        try:
            kw = os.path.basename(os.path.dirname(comments_path or "")) or ""
            safe_kw = "".join(c for c in kw if c.isalnum() or c in (' ', '-', '_')).strip() or "generic"
            rpfx = f"{safe_kw} {timestamp_dt}"
        except Exception:
            rpfx = f"generic {timestamp_dt}"
    out_path = os.path.join(reports_dir, f"{rpfx}_analysis.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content or "")
    utils.logger.info(f"[AnalysisAgent] Report saved: {out_path}")
    return out_path
