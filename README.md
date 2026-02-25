<div align="center">

  <img src="./logo.png" width="180" height="180" alt="CustomSegment Logo" style="border-radius: 50%; box-shadow: 0 0 20px rgba(0,0,0,0.2);">
  <br>

  <img src="https://count.getloli.com/@astrbot_custseg_reply?theme=minecraft&padding=7&offset=0&align=top&scale=1&pixelated=1&darkmode=auto" alt="Counter">

# Custom Segment Reply (本地智能分段)

_✨ 告别 API 延迟：纯本地计算、零成本、极速响应的多维断句引擎 ✨_

[![License](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Python 3.8+](https://img.shields.io/badge/Python-3.8%2B-blue.svg)](https://www.python.org/)
[![AstrBot](https://img.shields.io/badge/AstrBot-Recommended-orange.svg)](https://github.com/Soulter/AstrBot)
[![Version](https://img.shields.io/badge/Version-v1.0.0-purple.svg)](https://github.com/LinJohn8/astrbot_plugin_custome_segment_reply)

</div>

---

## 📖 简介 | Introduction

**告别“大模型分段”带来的网络延迟与账单焦虑。**

Custom Segment Reply 是一个为 AstrBot 打造的**纯本地智能断句系统**。它彻底抛弃了依赖 LLM (大模型) 进行文本拆分的传统做法，转而采用一套高自由度的**“多维本地策略算法”**。

在 Bot 输出长篇大论时，它能在**毫秒级**完成精准断句、模拟真人发送节奏。无视网络波动、无惧 API 报错，让你的数字生命回复更加自然、丝滑且极度稳定。

---

## ✨ 深度功能解析 | Deep Dive

### 🧠 1. 四维断句引擎 (Quad-Core Segment Engine)
这是本插件的核心算法。它绝不是简单的“按标点切分”，而是执行一套拟人化的判定程序：
* **区间探测 (Range Detection)**：优先在用户设定的 `[最小字数, 最大字数]` 黄金区间内寻找断点，保证每一句话长短适中。
* **优先级锚定 (Priority Anchoring)**：根据设定的符号优先级列表（如换行符 > 句号 > 逗号），优先在最强烈的语意停顿处断开。
* **标点吸附 (Punctuation Keep)**：支持灵活配置断句后是否保留原标点，满足不同人格设定的文字习惯。

### 🛡️ 2. 超长降级保护 (Exceed & Fallback Protocol) —— 🔥 核心防线
**遇到没有标点符号的几百字纯英文/乱码怎么办？程序会死循环吗？**

不存在的。系统内置了强大的降级保护机制：
* **弹性延伸 (`allow_exceed_max`)**：当黄金区间内找不到标点时，程序会允许突破最大字数限制，继续向后寻找第一个出现的标点，保证句子完整不被生硬切断。
* **绝对熔断 (`hard_max_limit`)**：如果向后延伸到了设定的“硬性截断极限”（如 100 字）依然没有标点，系统将无情介入，强制执行物理截断，彻底杜绝超长消息刷屏和内存溢出。

### 🧲 3. 短尾智能合并 (Short-Tail Merge System) `v1.0+`
**告别机器人说话大喘气！**
如果切分到最后，剩余的文本只有孤零零的几个字（例如：“好的。”、“没问题~”），单独发出来不仅突兀，还会破坏对话节奏。
触发短尾合并后，系统会**“撤回最后一刀”**，将这极短的尾巴无缝缝合到上一段话中一并发出。

### ⚡ 4. 极致轻量架构 (Ultra-Lightweight)
* 🚀 **0 依赖**：无需安装 `aiohttp`，不发任何网络请求。
* 💾 **0 成本**：完全不消耗大模型 Token 额度。
* 🛡️ **0 延迟**：内存级运算，即插即用，主打一个稳如泰山。

---

## 🛠️ 安装与配置 | Installation

1. 将本仓库下载后，把文件夹放入 `AstrBot/data/plugins/` 目录（请确保文件夹名为 `astrbot_plugin_custome_segment_reply`）。
2. 重启 AstrBot。
3. 在 AstrBot 的 WebUI 管理面板 -> 插件设置中，找到本插件即可进行**可视化配置**：

```json
{
  "min_length": 20,            // 触发断句的下限，在此字数内尽量不断句
  "max_length": 50,            // 常规断句上限，寻找标点的黄金区间
  "allow_exceed_max": true,    // 允许在没找到标点时突破上限往后找
  "hard_max_limit": 100,       // 绝对熔断长度，防止无限寻找
  "merge_short_tail": true,    // 开启短尾合并
  "short_tail_threshold": 8    // 当最后一段少于等于8个字时触发合并
}
