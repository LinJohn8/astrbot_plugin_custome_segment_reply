import asyncio
import random
import json
import re
import unicodedata
from typing import List, Optional, Tuple

from astrbot.api.event import filter as event_filter
from astrbot.api.event import AstrMessageEvent
from astrbot.api.all import Context, Star, register, AstrBotConfig, logger
from astrbot.core.message.message_event_result import MessageChain
from astrbot.api.message_components import Plain


@register("astrbot_plugin_custome_segment_reply", "LinJohn8", "自定义规则本地智能分段", "1.0.0")
class CustomSegmentReplyPlugin(Star):
    """基于可配置规则的消息分段插件，将长回复拆分为多条消息依次发送。"""

    PAIR_SYMBOLS = {
        "(": ")", "[": "]", "{": "}", "（": "）", "【": "】",
        "《": "》", "〈": "〉", "「": "」", "『": "』",
        "\u201c": "\u201d", "\u2018": "\u2019", "<": ">",
    }

    # ========================= 初始化 =========================

    def __init__(self, context: Context, config: AstrBotConfig):
        """初始化插件，解析并校验所有配置项。"""
        super().__init__(context)
        self.config = config or {}
        self._load_config()

    def _load_config(self):
        """从 self.config 中读取全部配置项，并进行类型转换与合法性校验。"""
        cfg = self.config

        # 强制分隔符
        self.force_split_symbols = self._parse_symbol_list(cfg.get("force_split_symbols"), default=[])

        # 字数范围
        self.min_length = self._parse_int(cfg, "min_length", 20)
        self.max_length = self._parse_int(cfg, "max_length", 50)
        if self.min_length > self.max_length:
            self.min_length = self.max_length

        # 超长处理
        self.allow_exceed_max = bool(cfg.get("allow_exceed_max", True))
        self.hard_max_limit = self._parse_int(cfg, "hard_max_limit", 100)
        if self.hard_max_limit < self.max_length:
            self.hard_max_limit = self.max_length + 20

        # 短尾合并
        self.merge_short_tail = bool(cfg.get("merge_short_tail", True))
        self.short_tail_threshold = self._parse_int(cfg, "short_tail_threshold", 8)

        # 断句符号
        self.split_symbols = self._parse_symbol_list(
            cfg.get("split_symbols"),
            default=["\n\n", "\n", "。", "！", "？", "；", "……", ".", "!", "?", ";", "\u201d", "、", "，", ","],
        )

        # 符号行为
        self.keep_symbol = bool(cfg.get("keep_symbol", True))
        self.extend_to_trailing_symbols = bool(cfg.get("extend_to_trailing_symbols", True))
        self.protect_paired_symbols = bool(cfg.get("protect_paired_symbols", False))

        # 排除关键词
        exclude_kw = cfg.get("exclude_keywords", [])
        self.exclude_keywords = exclude_kw if isinstance(exclude_kw, list) else []

        # 超长跳过阈值
        self.skip_longer_than = self._parse_int(cfg, "skip_longer_than", 0)

        # 延迟配置
        self._load_delay_config(cfg)

    def _load_delay_config(self, cfg: dict):
        """读取延迟相关配置：延迟类型、随机范围、固定秒数、每字符秒数。"""
        delay_range = cfg.get("random_delay_range", [1, 3])
        if isinstance(delay_range, list) and len(delay_range) >= 2:
            self.delay_min = self._safe_float(delay_range[0], 1.0)
            self.delay_max = self._safe_float(delay_range[1], 3.0)
        else:
            self.delay_min, self.delay_max = 1.0, 3.0
        if self.delay_min > self.delay_max:
            self.delay_min, self.delay_max = self.delay_max, self.delay_min

        mode = str(cfg.get("delay_type", "random")).strip().lower()
        self.delay_type = mode if mode in {"fixed", "random", "per_char", "smart"} else "random"

        self.fixed_delay_seconds = max(0.0, self._parse_float(cfg, "fixed_delay_seconds", 1.0))
        self.per_char_delay_seconds = max(0.0, self._parse_float(cfg, "per_char_delay_seconds", 0.08))

    # ========================= 配置解析工具 =========================

    @staticmethod
    def _safe_float(value, default: float) -> float:
        """将任意值安全转换为 float，失败时返回 default。"""
        try:
            return float(value)
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _parse_int(cfg: dict, key: str, default: int) -> int:
        """从配置字典中读取整数值，类型转换失败时返回 default。"""
        try:
            return int(cfg.get(key, default))
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _parse_float(cfg: dict, key: str, default: float) -> float:
        """从配置字典中读取浮点值，类型转换失败时返回 default。"""
        try:
            return float(cfg.get(key, default))
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _parse_symbol_list(raw, default: List[str]) -> List[str]:
        """将配置中的符号列表清洗为实际字符串列表（处理 \\n 转义等）。"""
        if not isinstance(raw, list) or not raw:
            raw = default
        result = []
        for s in raw:
            if isinstance(s, str):
                cleaned = s.replace("\\n", "\n").strip("\r")
                if cleaned:
                    result.append(cleaned)
        return result or default

    # ========================= 事件处理 =========================

    @event_filter.on_decorating_result()
    async def handle_segment_reply(self, event: AstrMessageEvent):
        """事件钩子：拦截 LLM 回复，执行分段并逐条发送。若分段失败则保持原消息不变。"""
        result = event.get_result()
        if not result or not result.chain:
            return

        raw_text = "".join(
            comp.text.strip() for comp in result.chain if isinstance(comp, Plain)
        ).strip()
        if not raw_text:
            return

        if self._should_skip(raw_text):
            return

        try:
            segments = self.segment_text_by_rules(raw_text)

            if len(segments) <= 1:
                return

            full_segmented_text = "\n\n".join(segments)
            result.chain.clear()

            await self._set_typing(event, True)
            for i, segment in enumerate(segments):
                if i > 0:
                    delay = self._calculate_delay(segments[i - 1], segment)
                    await self._set_typing(event, True)
                    await asyncio.sleep(delay)
                await event.send(MessageChain().message(segment))
                await self._set_typing(event, False)
            await self._set_typing(event, False)

            await self._save_to_conversation_history(event, full_segmented_text)
            logger.info(f"分段回复完成，共 {len(segments)} 段")

        except Exception as e:
            logger.error(f"分段异常，发送原消息。原因：{e}")

    def _should_skip(self, text: str) -> bool:
        """检查文本是否包含排除关键词或长度超过阈值（字数），若匹配则跳过分段处理。"""
        if self.skip_longer_than > 0 and len(text) > self.skip_longer_than:
            logger.info(f"文本长度 {len(text)} 超过阈值 {self.skip_longer_than}，跳过分段")
            return True
        if not self.exclude_keywords:
            return False
        text_lower = text.lower()
        for kw in self.exclude_keywords:
            if isinstance(kw, str) and kw and kw.lower() in text_lower:
                logger.info(f"检测到排除关键词 '{kw}'，跳过分段")
                return True
        return False

    # ========================= 分段核心逻辑 =========================

    def segment_text_by_rules(self, text: str) -> List[str]:
        """分段入口：先按强制分隔符预切，再对每段应用长度规则，最后执行短尾合并。"""
        # 第一步：按强制分隔符预分段
        pre_segments = self._split_by_force_symbols(text.strip())
        # 第二步：对每个预分段应用长度规则
        segments = []
        for pre_seg in pre_segments:
            segments.extend(self._segment_by_length(pre_seg))
        # 短尾合并
        if self.merge_short_tail and len(segments) >= 2:
            if self._logical_len(segments[-1]) <= self.short_tail_threshold:
                tail = segments.pop()
                segments[-1] += tail
        return segments

    def _split_by_force_symbols(self, text: str) -> List[str]:
        """按强制分隔符预分段，连续重复的同一符号视为一个整体。"""
        if not self.force_split_symbols:
            return [text]
        pieces = [text]
        for symbol in self.force_split_symbols:
            new_pieces = []
            for piece in pieces:
                i, last_end = 0, 0
                while i <= len(piece) - len(symbol):
                    if piece.startswith(symbol, i):
                        sep_len = self._get_split_char_len(piece, i, symbol)
                        if self.keep_symbol:
                            new_pieces.append(piece[last_end:i + sep_len])
                        else:
                            new_pieces.append(piece[last_end:i])
                        last_end = i + sep_len
                        i = last_end
                    else:
                        i += 1
                new_pieces.append(piece[last_end:])
            pieces = new_pieces
        return [p.strip() for p in pieces if p.strip()]

    def _segment_by_length(self, text: str) -> List[str]:
        """对单段文本按字数范围和断句符号进行迭代切分。"""
        segments = []
        remaining = text.strip()

        while remaining:
            if len(remaining) <= self.max_length:
                segments.append(remaining)
                break

            protected = self._build_protected_ranges(remaining) if self.protect_paired_symbols else []
            split_idx, char_len = self._find_split_point(remaining, protected)

            if self.keep_symbol:
                cut = split_idx + char_len
                seg = remaining[:cut].strip()
                remaining = remaining[cut:].strip()
            else:
                seg = remaining[:split_idx].strip()
                remaining = remaining[split_idx + char_len:].strip()

            if seg:
                segments.append(seg)

        return segments

    def _find_split_point(self, text: str, protected: List[tuple]) -> Tuple[int, int]:
        """在 text 中寻找最佳分段点，返回 (index, symbol_length)。"""

        # 1) 优先在 [min_length, max_length) 范围内反向查找
        result = self._rfind_symbol(text, self.min_length, self.max_length, protected)
        if result:
            return result

        # 2) 允许超出时，在 [max_length, hard_max_limit) 范围内正向查找
        if self.allow_exceed_max:
            search_end = min(len(text), self.hard_max_limit)
            result = self._find_symbol_forward(text, self.max_length, search_end, protected)
            if result:
                return result
            return search_end, 0

        # 3) 不允许超出时，在 [0, min_length) 范围内反向查找
        result = self._rfind_symbol(text, 0, self.min_length, protected)
        if result:
            return result
        return self.max_length, 0

    def _rfind_symbol(self, text: str, start: int, end: int, protected: List[tuple]) -> Optional[Tuple[int, int]]:
        """在 text[start:end] 中反向查找第一个匹配的分段符号。"""
        for symbol in self.split_symbols:
            idx = text.rfind(symbol, start, end)
            if idx != -1 and not self._in_protected_range(idx, protected):
                return idx, self._get_split_char_len(text, idx, symbol)
        return None

    def _find_symbol_forward(self, text: str, start: int, end: int, protected: List[tuple]) -> Optional[Tuple[int, int]]:
        """在 text[start:end] 中正向查找第一个匹配的分段符号。"""
        for i in range(start, end):
            for symbol in self.split_symbols:
                if text.startswith(symbol, i) and not self._in_protected_range(i, protected):
                    return i, self._get_split_char_len(text, i, symbol)
        return None

    # ========================= 符号处理工具 =========================

    @staticmethod
    def _is_symbol_char(ch: str) -> bool:
        """判断单个字符是否为标点(P)或符号(S)类 Unicode 字符。"""
        cat = unicodedata.category(ch)
        return cat[0] in ("P", "S")

    @classmethod
    def _logical_len(cls, text: str) -> int:
        """计算逻辑长度：连续重复的同一符号字符视为 1 个字符。"""
        length = 0
        i = 0
        while i < len(text):
            ch = text[i]
            if cls._is_symbol_char(ch):
                # 跳过后续相同的符号字符
                while i + 1 < len(text) and text[i + 1] == ch:
                    i += 1
            length += 1
            i += 1
        return length

    def _get_split_char_len(self, text: str, idx: int, symbol: str) -> int:
        """返回从 idx 开始分隔符应吞掉的总长度（含顺延的连续符号）。"""
        total = len(symbol)
        if not self.extend_to_trailing_symbols:
            return total
        # 空白类分隔符不做顺延，避免误吞下一段开头的符号
        if any(ch.isspace() for ch in symbol):
            return total
        while idx + total < len(text) and self._is_symbol_char(text[idx + total]):
            total += 1
        return total

    @classmethod
    def _build_protected_ranges(cls, text: str) -> List[tuple]:
        """构建成对符号的保护区间（开→闭之间不分段）。"""
        ranges, stack = [], []
        for idx, ch in enumerate(text):
            if ch in cls.PAIR_SYMBOLS:
                stack.append((idx, cls.PAIR_SYMBOLS[ch]))
            elif stack and ch == stack[-1][1]:
                open_idx, _ = stack.pop()
                ranges.append((open_idx, idx))
        return ranges

    @staticmethod
    def _in_protected_range(split_idx: int, protected: List[tuple]) -> bool:
        """判断切分点是否落在任一成对符号的保护区间内部（不含边界）。"""
        return any(start < split_idx < end for start, end in protected)

    # ========================= 延迟计算 =========================

    @staticmethod
    def _gauss_clamped(min_v: float, max_v: float) -> float:
        """生成正态分布随机数，均值为区间中点，结果钳制在 [min_v, max_v] 内。"""
        if min_v >= max_v:
            return min_v
        mean = (min_v + max_v) / 2
        std = max((max_v - min_v) / 6, 1e-6)
        return max(min_v, min(max_v, random.gauss(mean, std)))

    def _calculate_delay(self, prev_seg: str, curr_seg: str) -> float:
        """根据 delay_type 配置计算当前分段发送前的等待秒数。"""
        if self.delay_type == "fixed":
            return self.fixed_delay_seconds

        if self.delay_type == "per_char":
            return max(0.0, self.per_char_delay_seconds * len(prev_seg))

        if self.delay_type == "smart":
            return self._calculate_smart_delay(prev_seg, curr_seg)

        # random（默认）
        return self._gauss_clamped(self.delay_min, self.delay_max)

    def _calculate_smart_delay(self, prev_seg: str, curr_seg: str) -> float:
        """智能延迟：基于字符数的打字间隔，叠加符号修正。"""
        per_char_ms = max(10.0, random.gauss(80.0, 30.0))
        base = (per_char_ms * len(curr_seg)) / 1000.0

        # 感叹号加速（减少延迟）：语气急促，打字更快
        exclam_count = curr_seg.count("!") + curr_seg.count("！")
        exclam_reduce = sum(self._gauss_clamped(0.1, 0.3) for _ in range(exclam_count))

        # 问号减速（增加延迟）：上一句是疑问句时，模拟"等待回应"的短暂停顿
        question_add = 0.0
        if prev_seg and prev_seg.rstrip()[-1] in "?？":
            question_add = self._gauss_clamped(0.2, 0.5)

        # 逗号/顿号结尾加速（减少延迟）：上一句被截断在逗号处，说明是同一句话的延续
        comma_reduce = 0.0
        if prev_seg and prev_seg.rstrip()[-1] in ",，、":
            comma_reduce = self._gauss_clamped(0.2, 0.5)

        # 省略号/破折号减速（增加延迟）
        # - prev_seg 句尾的停顿符：上一句说完后的停顿
        # - curr_seg 句首/句中的停顿符：犹豫、欲言又止
        pause_pattern = r"(?:\.{3,}|。{3,}|…{2,}|-{2,}|—{2,}|－{2,})"
        prev_tail_pauses = len(re.findall(pause_pattern + r"\s*$", prev_seg))
        all_curr_pauses = re.findall(pause_pattern, curr_seg)
        curr_tail_pauses = len(re.findall(pause_pattern + r"\s*$", curr_seg))
        curr_non_tail_pauses = len(all_curr_pauses) - curr_tail_pauses
        pause_count = prev_tail_pauses + curr_non_tail_pauses
        pause_add = sum(self._gauss_clamped(0.4, 0.8) for _ in range(pause_count))

        return max(0.0, base - exclam_reduce - comma_reduce + question_add + pause_add)

    # ========================= 输入状态 =========================

    @staticmethod
    async def _set_typing(event: AstrMessageEvent, typing: bool):
        """向平台发送"正在输入"状态。仅 aiocqhttp (QQ) 平台可用，其他平台静默忽略。"""
        try:
            if event.get_platform_name() != "aiocqhttp":
                return
            from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
            if not isinstance(event, AiocqhttpMessageEvent):
                return
            user_id = event.message_obj.sender.user_id
            if not user_id:
                return
            await event.bot.api.call_action(
                "set_input_status",
                user_id=user_id,
                event_type=1 if typing else 0,
            )
        except Exception:
            pass  # 平台不支持或调用失败时静默忽略

    # ========================= 对话历史 =========================

    async def _save_to_conversation_history(self, event: AstrMessageEvent, content: str):
        """将分段合并后的完整回复写入对话历史，确保上下文连贯。"""
        try:
            conv_mgr = self.context.conversation_manager
            if not conv_mgr:
                return

            umo = event.unified_msg_origin
            curr_cid = await conv_mgr.get_curr_conversation_id(umo)
            if not curr_cid:
                return

            conversation = await conv_mgr.get_conversation(umo, curr_cid)
            if not conversation:
                return

            try:
                history = json.loads(conversation.history) if isinstance(conversation.history, str) else conversation.history
            except (json.JSONDecodeError, TypeError):
                history = []

            user_content = event.message_str
            if user_content and (not history or history[-1].get("role") != "user"):
                history.append({"role": "user", "content": user_content})

            history.append({"role": "assistant", "content": content})

            await conv_mgr.update_conversation(
                unified_msg_origin=umo,
                conversation_id=curr_cid,
                history=history,
            )
        except Exception as e:
            logger.error(f"保存对话历史失败: {e}")

    async def terminate(self):
        """插件卸载时的清理回调。"""
        logger.info("本地自定义规则分段插件已卸载")
