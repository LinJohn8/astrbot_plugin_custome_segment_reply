from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.core.message.message_event_result import MessageChain
from astrbot.api.message_components import Plain
import asyncio
import random
import json

@register(
    "astrbot_plugin_custome_segment_reply",  # 对应你的仓库名
    "LinJohn8",                              # 对应你的Github用户名
    "通过自定义规则实现本地智能分段回复，彻底告别AI断句延迟，支持多维度配置",
    "1.0.0",                                 # 版本号
    "https://github.com/LinJohn8/astrbot_plugin_custome_segment_reply"
)
class CustomSegmentReply(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.config = config
        
        # 1. 基础字数配置
        self.min_length = int(self.config.get("min_length", 20))
        self.max_length = int(self.config.get("max_length", 50))
        if self.min_length > self.max_length:
            self.min_length = self.max_length # 防止配置错误导致死循环
            
        # 2. 超长处理配置
        self.allow_exceed_max = bool(self.config.get("allow_exceed_max", True))
        self.hard_max_limit = int(self.config.get("hard_max_limit", 100))
        if self.hard_max_limit < self.max_length:
            self.hard_max_limit = self.max_length + 20
            
        # 3. 短尾合并配置
        self.merge_short_tail = bool(self.config.get("merge_short_tail", True))
        self.short_tail_threshold = int(self.config.get("short_tail_threshold", 8))
        
        # 4. 符号与保留配置
        self.split_symbols = self.config.get("split_symbols", [
            "\n\n", "\n", "。", "！", "？", "；", "……", ".", "!", "?", ";", "”", "、", "，", ","
        ])
        self.keep_symbol = bool(self.config.get("keep_symbol", True))
        
        # 5. 杂项配置
        self.exclude_keywords = self.config.get("exclude_keywords", [])
        delay_range = self.config.get("random_delay_range", [1, 3])
        if isinstance(delay_range, list) and len(delay_range) >= 2:
            self.delay_min = float(delay_range[0])
            self.delay_max = float(delay_range[1])
        else:
            self.delay_min = 1.0
            self.delay_max = 3.0

    @filter.on_decorating_result()
    async def handle_segment_reply(self, event: AstrMessageEvent):
        result = event.get_result()
        if not result or not result.chain:
            return

        # 提取原始纯文本（保留顺序拼装）
        raw_text = ""
        for comp in result.chain:
            if isinstance(comp, Plain):
                raw_text += comp.text.strip()
        raw_text = raw_text.strip()
        if not raw_text:
            return

        # 检查是否包含排除关键词（不区分大小写）
        if self.exclude_keywords:
            text_lower = raw_text.lower()
            for keyword in self.exclude_keywords:
                if keyword and keyword.lower() in text_lower:
                    logger.info(f"检测到排除关键词 '{keyword}'，跳过自定义规则分段")
                    return

        try:
            logger.info(f"——准备进行自定义规则分段（原回复长度：{len(raw_text)}字符）——")
            
            # 核心算法：调用本地规则进行分段
            segments = self.segment_text_by_rules(raw_text)
            
            if not segments or len(segments) <= 1:
                logger.info(f"——分段完成，无需拆分，保持 1 段输出——")
                return

            full_segmented_text = "\n\n".join(segments)
            
            # 清空原消息链，准备分段发送
            result.chain.clear()
            
            # 遍历分段并延迟发送
            for i, segment in enumerate(segments):
                if i > 0:  # 第一段不延迟，后续段落使用随机延迟
                    delay = random.uniform(self.delay_min, self.delay_max)
                    await asyncio.sleep(delay)
                await event.send(MessageChain().message(segment))
            
            # 手动保存到对话历史，保证上下文连贯
            await self._save_to_conversation_history(event, full_segmented_text)
            
            logger.info(f"——本地规则分段回复成功，共分 {len(segments)} 段——")
            
        except Exception as e:
            logger.error(f"本地规则分段异常，发送原消息。失败原因：{str(e)}")
            return

    def segment_text_by_rules(self, text: str) -> list[str]:
        """核心：纯本地多策略规则断句算法"""
        segments = []
        remaining_text = text.strip()

        while remaining_text:
            # 基础退出条件：如果剩余文本已经小于等于最大长度，直接作为最后一段
            if len(remaining_text) <= self.max_length:
                if remaining_text:
                    segments.append(remaining_text)
                break

            best_split_index = -1
            split_char_len = 0

            # 策略一：在 [min_length, max_length] 范围内，寻找优先级最高（最靠前配置）的标点
            # 使用 rfind 寻找该范围内最后出现的符号，以保证单段文本尽可能长
            for symbol in self.split_symbols:
                idx = remaining_text.rfind(symbol, self.min_length, self.max_length)
                if idx != -1:
                    best_split_index = idx
                    split_char_len = len(symbol)
                    break # 找到优先级最高的符号，立刻停止检查其他符号

            # 策略二：如果在常规区间没找到任何标点
            if best_split_index == -1:
                if self.allow_exceed_max:
                    # 允许超出：从 max_length 往后一直找到 hard_max_limit，寻找第一个出现的标点
                    search_end = min(len(remaining_text), self.hard_max_limit)
                    found = False
                    for i in range(self.max_length, search_end):
                        for symbol in self.split_symbols:
                            if remaining_text.startswith(symbol, i):
                                best_split_index = i
                                split_char_len = len(symbol)
                                found = True
                                break
                        if found:
                            break
                    
                    if best_split_index == -1:
                        # 如果直到 hard_max_limit 都没标点，强制在 hard_max_limit 处生硬截断
                        best_split_index = search_end
                        split_char_len = 0
                else:
                    # 不允许超出：只能回头在 [0, min_length] 范围内找标点
                    for symbol in self.split_symbols:
                        idx = remaining_text.rfind(symbol, 0, self.min_length)
                        if idx != -1:
                            best_split_index = idx
                            split_char_len = len(symbol)
                            break
                    
                    if best_split_index == -1:
                        # 全文彻底没标点，强制在 max_length 处生硬截断
                        best_split_index = self.max_length
                        split_char_len = 0

            # 执行切割并处理是否保留标点符号
            if self.keep_symbol:
                # 包含标点符号一起切下
                cut_point = best_split_index + split_char_len
                seg = remaining_text[:cut_point].strip()
                if seg:
                    segments.append(seg)
                remaining_text = remaining_text[cut_point:].strip()
            else:
                # 切下内容，但丢弃该标点符号
                seg = remaining_text[:best_split_index].strip()
                if seg:
                    segments.append(seg)
                # 剩下的文本从标点符号之后开始算
                remaining_text = remaining_text[best_split_index + split_char_len:].strip()

        # 策略三：处理短尾合并 (merge_short_tail)
        # 如果切分完毕后至少有2段，且最后一段字数极少，则将其拼接到倒数第二段上
        if self.merge_short_tail and len(segments) >= 2:
            last_seg = segments[-1]
            if len(last_seg) <= self.short_tail_threshold:
                tail = segments.pop()
                # 考虑到有时候是去掉了标点，拼接时加个空格作为保险，如果是中文环境其实直接拼接即可。
                # 此处采用直接无缝拼接，更符合大多数聊天语境
                segments[-1] = segments[-1] + tail

        return segments

    async def _save_to_conversation_history(self, event: AstrMessageEvent, content: str):
        """手动保存分段后的助手回复到对话历史中，防止上下文丢失"""
        try:
            conv_mgr = self.context.conversation_manager
            if not conv_mgr:
                return
            
            umo = event.unified_msg_origin
            curr_cid = await conv_mgr.get_curr_conversation_id(umo)
            
            if curr_cid:
                conversation = await conv_mgr.get_conversation(umo, curr_cid)
                if conversation:
                    try:
                        history = json.loads(conversation.history) if isinstance(conversation.history, str) else conversation.history
                    except:
                        history = []
                    
                    user_content = event.message_str
                    if user_content:
                        # 检查历史记录避免重复添加用户输入
                        if not history or history[-1].get("role") != "user":
                            history.append({
                                "role": "user",
                                "content": user_content
                            })
                    
                    # 添加助手回复（保存的是分段合并后的完整内容，用 \n\n 隔开）
                    history.append({
                        "role": "assistant",
                        "content": content
                    })
                    
                    await conv_mgr.update_conversation(
                        unified_msg_origin=umo,
                        conversation_id=curr_cid,
                        history=history
                    )
        except Exception as e:
            logger.error(f"保存对话历史失败: {str(e)}")

    async def terminate(self):
        logger.info("本地自定义规则分段插件已卸载，资源已释放")