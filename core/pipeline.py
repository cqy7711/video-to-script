"""核心 Pipeline — 视频→剧本分析全流程"""

import os
import json
import subprocess
import tempfile
import shutil
from dataclasses import dataclass, field
from typing import Optional, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

import whisper
from moviepy import VideoFileClip


@dataclass
class VideoInfo:
    path: str
    duration: float = 0.0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    size_mb: float = 0.0
    source: str = "local"        # "local" or "url"
    platform: str = ""           # 来源平台（抖音/YouTube/B站等）
    title: str = ""              # 视频标题（链接下载时）


@dataclass
class SceneInfo:
    index: int
    start: float
    end: float
    duration: float
    mid_time: float
    frame_path: Optional[str] = None


@dataclass
class AnalysisResult:
    video_info: Optional[VideoInfo] = None
    transcript_text: str = ""
    transcript_segments: list = field(default_factory=list)
    enriched_segments: list = field(default_factory=list)   # 含角色/BGM标注的分段
    bgm_info: str = ""
    scenes: list = field(default_factory=list)
    hooks_analysis: str = ""
    script_structure: str = ""
    character_map: str = ""
    rewrite_suggestions: str = ""
    north_america: str = ""
    full_report: str = ""
    error: str = ""
    # 精简版分析结果（按需生成，缓存于此）
    hooks_analysis_concise: str = ""
    script_structure_concise: str = ""
    character_map_concise: str = ""
    rewrite_suggestions_concise: str = ""
    north_america_concise: str = ""


class VideoToScriptPipeline:
    def __init__(self,
                 whisper_model: str = "base",
                 scene_threshold: float = 35.0,
                 min_scene_duration: float = 2.0,
                 openai_api_key: str = "",
                 openai_model: str = "gpt-4o-mini",
                 openai_base_url: str = "",
                 language: str = None,
                 work_dir: str = ""):
        self.whisper_model_name = whisper_model
        self.scene_threshold = scene_threshold
        self.min_scene_duration = min_scene_duration
        self.openai_api_key = openai_api_key
        self.openai_model = openai_model
        self.openai_base_url = openai_base_url
        self.language = language
        self.work_dir = work_dir or tempfile.mkdtemp(prefix="v2s_")
        self._whisper_model = None
        self._ffmpeg_path = None

    def _ensure_ffmpeg(self):
        result = shutil.which("ffmpeg")
        if result:
            self._ffmpeg_path = result
            return
        try:
            import imageio_ffmpeg
            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
            if os.path.exists(ffmpeg_exe):
                if os.name == "nt":
                    # Windows: 直接使用 exe，无需 wrapper
                    self._ffmpeg_path = ffmpeg_exe
                    ffmpeg_dir = os.path.dirname(ffmpeg_exe)
                    current_path = os.environ.get("PATH", "")
                    if ffmpeg_dir not in current_path:
                        os.environ["PATH"] = f"{ffmpeg_dir};{current_path}"
                else:
                    # macOS/Linux: 创建 shell wrapper
                    wrapper_path = os.path.join(self.work_dir, "ffmpeg")
                    with open(wrapper_path, "w") as f:
                        f.write(f"#!/bin/bash\nexec {ffmpeg_exe} \"$@\"\n")
                    os.chmod(wrapper_path, 0o755)
                    self._ffmpeg_path = wrapper_path
                    current_path = os.environ.get("PATH", "")
                    os.environ["PATH"] = f"{self.work_dir}:{current_path}"
                return
        except Exception:
            pass
        if os.name == "nt":
            raise RuntimeError("找不到 ffmpeg。请安装: 1) 从 https://ffmpeg.org/download.html 下载 2) 或 pip install imageio-ffmpeg")
        else:
            raise RuntimeError("找不到 ffmpeg。请安装: brew install ffmpeg 或 pip install imageio-ffmpeg")

    def _run_ffmpeg(self, args: list) -> subprocess.CompletedProcess:
        cmd = [self._ffmpeg_path or "ffmpeg"] + args
        return subprocess.run(cmd, capture_output=True, text=True)

    def step1_get_video_info(self, video_path: str) -> VideoInfo:
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"视频文件不存在: {video_path}")
        info = VideoInfo(path=video_path)
        info.size_mb = os.path.getsize(video_path) / (1024 * 1024)
        try:
            clip = VideoFileClip(video_path)
            info.duration = clip.duration
            info.width = clip.w
            info.height = clip.h
            info.fps = clip.fps
            clip.close()
        except Exception:
            pass
        return info

    def step2_extract_audio(self, video_path: str, progress_cb: Callable = None) -> str:
        if progress_cb:
            progress_cb("正在提取音频...")
        resampled_audio = os.path.join(self.work_dir, "audio_16k.wav")
        # 直接用 ffmpeg 提取+重采样，跳过 moviepy 开销
        self._run_ffmpeg([
            "-y", "-i", video_path,
            "-vn", "-ar", "16000", "-ac", "1", "-f", "wav",
            resampled_audio
        ])
        if not os.path.exists(resampled_audio):
            # 降级：用 moviepy 提取
            if progress_cb:
                progress_cb("ffmpeg 提取失败，降级使用 moviepy...")
            raw_audio = os.path.join(self.work_dir, "audio_raw.wav")
            from moviepy import VideoFileClip
            clip = VideoFileClip(video_path)
            clip.audio.write_audiofile(raw_audio, logger=None)
            clip.close()
            self._run_ffmpeg(["-y", "-i", raw_audio, "-ar", "16000", "-ac", "1", resampled_audio])
            if os.path.exists(raw_audio):
                os.remove(raw_audio)
        return resampled_audio

    def _load_whisper_model(self, model_name: str, progress_cb: Callable = None):
        """加载 Whisper 模型，网络失败时自动降级到更小的模型"""
        try:
            if progress_cb:
                progress_cb(f"正在加载 Whisper {model_name} 模型（首次需下载，请耐心等待）...")
            return whisper.load_model(model_name)
        except Exception as e:
            error_str = str(e).lower()
            if "broken pipe" in error_str or "connection" in error_str or "network" in error_str or "download" in error_str:
                # 网络下载失败，清理不完整的缓存
                self._clear_whisper_cache(model_name)
                raise
            raise

    def _clear_whisper_cache(self, model_name: str):
        """清除可能损坏的模型缓存"""
        import os
        # Whisper 使用 XDG 缓存目录，Windows 上是 ~/AppData/Local/whisper
        cache_dir = os.path.join(os.path.expanduser("~"), ".cache", "whisper")
        if os.path.exists(cache_dir):
            for f in os.listdir(cache_dir):
                if model_name in f and f.endswith(".pt"):
                    try:
                        os.remove(os.path.join(cache_dir, f))
                    except Exception:
                        pass

    def step3_transcribe(self, audio_path: str, progress_cb: Callable = None) -> dict:
        """语音转写，支持模型自动降级"""
        if self._whisper_model is None:
            models_to_try = [self.whisper_model_name]
            # 如果选的是 medium/large/small，失败时自动降级
            fallback_chain = {"large": "medium", "medium": "small", "small": "base", "base": "tiny"}
            current = self.whisper_model_name
            while current in fallback_chain and fallback_chain[current] not in models_to_try:
                current = fallback_chain[current]
                models_to_try.append(current)

            last_error = None
            for model_name in models_to_try:
                try:
                    self._whisper_model = self._load_whisper_model(model_name, progress_cb)
                    if model_name != self.whisper_model_name and progress_cb:
                        progress_cb(f"⚠️ {self.whisper_model_name} 模型下载失败，已自动降级到 {model_name}")
                    break
                except Exception as e:
                    last_error = e
                    if progress_cb:
                        progress_cb(f"❌ Whisper {model_name} 加载失败：{str(e)[:60]}...")
                    continue
            else:
                # 所有模型都失败了
                raise RuntimeError(
                    f"Whisper 模型加载失败：{last_error}\n"
                    f"可能原因：网络不稳定导致模型下载中断。\n"
                    f"解决方法：\n"
                    f"1. 检查网络连接后重试\n"
                    f"2. 尝试选择更小的模型（如 base 或 tiny）\n"
                    f"3. 手动下载模型放到缓存目录"
                )

        if progress_cb:
            progress_cb("Whisper 模型加载完成，正在进行语音转写...")
        result = self._whisper_model.transcribe(audio_path, language=self.language, verbose=False)
        return result

    def step4_detect_scenes(self, video_path: str, progress_cb: Callable = None) -> list:
        if progress_cb:
            progress_cb("正在进行场景检测...")
        try:
            from scenedetect import open_video, SceneManager
            from scenedetect.detectors import ContentDetector
            video = open_video(video_path)
            scene_manager = SceneManager()
            scene_manager.add_detector(ContentDetector(threshold=self.scene_threshold))
            scene_manager.detect_scenes(video)
            raw_scenes = scene_manager.get_scene_list()
            merged = []
            for start, end in raw_scenes:
                duration = end.seconds - start.seconds
                if merged and duration < self.min_scene_duration:
                    merged[-1] = (merged[-1][0], end)
                else:
                    merged.append((start, end))
            scenes = []
            frames_dir = os.path.join(self.work_dir, "frames")
            os.makedirs(frames_dir, exist_ok=True)
            for i, (start, end) in enumerate(merged):
                mid = (start.seconds + end.seconds) / 2
                frame_path = os.path.join(frames_dir, f"scene_{i+1:03d}.jpg")
                self._run_ffmpeg(["-y", "-ss", str(mid), "-i", video_path, "-frames:v", "1", "-q:v", "2", frame_path])
                scene = SceneInfo(
                    index=i + 1, start=round(start.seconds, 1), end=round(end.seconds, 1),
                    duration=round(end.seconds - start.seconds, 1), mid_time=round(mid, 1),
                    frame_path=frame_path if os.path.exists(frame_path) else None
                )
                scenes.append(scene)
            return scenes
        except ImportError:
            if progress_cb:
                progress_cb("PySceneDetect 未安装，使用间隔模式...")
            return self._extract_frames_interval(video_path)

    def _extract_frames_interval(self, video_path: str, interval: int = 5) -> list:
        info = self.step1_get_video_info(video_path)
        scenes = []
        frames_dir = os.path.join(self.work_dir, "frames")
        os.makedirs(frames_dir, exist_ok=True)
        t = 0
        idx = 1
        while t < info.duration:
            frame_path = os.path.join(frames_dir, f"scene_{idx:03d}.jpg")
            next_t = min(t + interval, info.duration)
            self._run_ffmpeg(["-y", "-ss", str(t + interval / 2), "-i", video_path, "-frames:v", "1", "-q:v", "2", frame_path])
            scene = SceneInfo(
                index=idx, start=round(t, 1), end=round(next_t, 1),
                duration=round(next_t - t, 1), mid_time=round(t + interval / 2, 1),
                frame_path=frame_path if os.path.exists(frame_path) else None
            )
            scenes.append(scene)
            t += interval
            idx += 1
        return scenes

    # ─── 转写文本增强：角色标注 + BGM分离 ───

    def _llm_enrich_transcript(self, client, segments_json, video_info, language_hint):
        """让LLM标注每个转写段落的说话人和类型（对白/BGM）"""
        prompt = f"""你是一名音频内容分析专家。请分析以下从视频转写的文本片段，完成两项任务：

1. **标注说话人**：判断每句台词是谁说的，给出合理的人物名称
2. **区分对白与背景音乐(BGM)**：如果是BGM歌词，标记为BGM；如果是对白，标记为DIALOGUE

视频时长: {video_info.duration:.1f}秒

---

以下是需要分析的转写段落（JSON格式）：

{segments_json}

---

请用JSON格式输出，格式如下：
{{
  "bgm_info": "背景音乐识别信息，格式如：🎵 检测到背景音乐：《歌名》- 歌手（相似度：高/中/低）。如果无法确定具体歌名，写相似歌曲如：🎵 BGM风格类似《歌名》- 歌手。如果没有BGM写'未检测到背景音乐'。请尽可能根据歌词内容、音乐风格识别或推测最可能的歌曲。",
  "segments": [
    {{"start": 0.0, "end": 2.5, "text": "原文", "type": "DIALOGUE", "speaker": "角色名"}},
    {{"start": 2.5, "end": 5.0, "text": "原文", "type": "BGM", "speaker": "BGM"}},
    ...
  ]
}}

注意：
- type 只能是 "DIALOGUE" 或 "BGM"
- 对白请根据上下文推断说话人，用合理的人名标注
- 如果无法确定说话人，用"未知角色"
- 对于BGM，speaker填"BGM"
- 保持原始的时间戳和文本内容不变
- **BGM识别要求**：请根据歌词内容、旋律描述、音乐风格等线索，尽量识别出准确的歌名或相似歌曲。中文流行歌、英文歌、纯音乐都请尝试识别。即使只能推测，也请给出最可能的1-3首候选歌曲{language_hint}"""
        resp = self._llm_call_with_retry(client,
            model=self.openai_model,
            messages=[
                {"role": "system", "content": "你是音频内容分析专家，擅长区分对白和背景音乐，并为台词标注说话人。只输出JSON格式，不要其他内容。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3, max_tokens=4000
        )
        return resp.choices[0].message.content

    def _parse_enriched(self, raw_text):
        """解析LLM返回的JSON富化结果"""
        import json
        try:
            # 尝试直接解析
            data = json.loads(raw_text)
        except json.JSONDecodeError:
            # 尝试从 Markdown 代码块中提取 JSON
            if "```json" in raw_text:
                raw_text = raw_text.split("```json")[1].split("```")[0]
            elif "```" in raw_text:
                raw_text = raw_text.split("```")[1].split("```")[0]
            try:
                data = json.loads(raw_text.strip())
            except json.JSONDecodeError:
                return None, ""
        segments = data.get("segments", [])
        bgm_info = data.get("bgm_info", "")
        # 确保字段存在
        for seg in segments:
            seg.setdefault("type", "DIALOGUE")
            seg.setdefault("speaker", "未知角色")
        return segments, bgm_info

    # ─── 4 个并行 LLM 分析子任务 ───

    def _get_client(self):
        from openai import OpenAI
        kwargs = {"api_key": self.openai_api_key, "timeout": 120.0}
        if self.openai_base_url:
            kwargs["base_url"] = self.openai_base_url
        return OpenAI(**kwargs)

    def _llm_call_with_retry(self, client, **kwargs):
        """带重试的 LLM 调用，自动处理超时"""
        import time
        last_error = None
        for attempt in range(3):
            try:
                return client.chat.completions.create(**kwargs)
            except Exception as e:
                last_error = e
                err_msg = str(e)
                if "timed out" in err_msg.lower() or "timeout" in err_msg.lower():
                    if attempt < 2:
                        time.sleep((attempt + 1) * 5)
                        continue
                raise
        raise last_error

    def _llm_hooks(self, client, transcript, scene_desc, video_info, language_hint):
        # 长视频转写截断
        MAX_TRANSCRIPT_LEN = 12000
        if len(transcript) > MAX_TRANSCRIPT_LEN:
            head = transcript[:4000]
            tail = transcript[-4000:]
            omitted = len(transcript) - 8000
            transcript = f"{head}\n\n...[中间省略 {omitted} 字符]...\n\n{tail}"
        prompt = f"""你是专业的短剧钩子分析专家。请对以下视频进行完整的「单集钩子与留存分析」。

## 视频信息
- 时长: {video_info.duration:.1f}秒 | 分辨率: {video_info.width}×{video_info.height}

## 场景切割
{scene_desc}

## 语音转写文本
{transcript}

---

请严格按照以下结构输出，必须包含【精简版】和【详细版】两部分：

## 核心要点（精简版）
用5-8条bullet points提炼最关键的结论，每条不超过20字，覆盖：钩子类型、核心反转数、情绪走势、完播率预估、核心受众。不要展开论述。
> 格式：- [结论要点]

---FULL---

### 一、基础信息与核心数据

#### 1.1 视频基础信息
| 分析项 | 内容 |
|-------|------|
| 单集时长 | [X]秒 |
| 集数 | 第[X]集（如为单集则标注"单集"） |
| 视频名称 | （根据内容推断标题） |

#### 1.2 核心数据指标（IAA分账权重参考）
> **IAA分账权重公式：完播率(40%) > 评论率(25%) > 转发率(20%) > 点赞率(15%)**
> 完播率是决定收益的核心指标，由钩子强度和反转节奏直接决定。

| 分析项 | 估算值 | 说明 |
|-------|-------|------|
| 预估完播率 | （高/中/低，基于钩子和反转密度判断） |
| 预估评论率驱动因素 | （哪些设计会引发评论？） |
| 预估转发率驱动因素 | （哪些金句或反转值得转发？） |
| 预估点赞率驱动因素 | （哪些情绪高点会触发点赞？） |

#### 1.3 观众画像推断
| 分析项 | 推断结果 |
|-------|---------|
| 核心受众年龄层 | （如：18-25岁年轻女性 / 30-45岁中年群体） |
| 核心受众性别 | （女性为主 / 男性为主 / 均衡） |
| 受众心理标签 | （如：渴望逆袭 / 情感共鸣 / 悬念猎奇） |

### 二、前3秒钩子分析
| 分析项 | 内容 |
|-------|------|
| 钩子类型 | （冲突爆发型/悬念提问型/结果前置型/视觉冲击型/情绪反差型） |
| 钩子具体内容 | （逐字记录前3秒的台词、画面、音效和字幕） |
| 钩子技巧 | （是否使用了特写镜头/放大音效/加粗字幕/快速剪辑？具体分析） |
| 钩子解决的问题 | （这个钩子让观众产生了什么疑问或情绪？） |

### 三、剧情节奏与反转设计（决定完播率）

#### 2.1 时间节点划分
将视频按时间轴划分为若干段落，并说明每段的功能：
| 时间段 | 功能定位 | 内容摘要 |
|-------|---------|---------|
| 0-3s | 钩子 | ... |

#### 2.2 反转分析
| 分析项 | 内容 |
|-------|------|
| 反转数量与时间点 | （视频中有几个反转？分别出现在第几秒？） |
| 反转类型 | （身份反转/真相反转/立场反转/因果反转/打脸反转） |
| 反转铺垫 | （反转前是否有伏笔？伏笔是否明显但不剧透？） |
| 剧情内容 | （以剧本的形式记录剧情主要内容） |

### 四、情绪调动方法（决定互动率）

#### 3.1 情绪曲线
画出本集的情绪起伏曲线，标注每个情绪高点和低点（用文字描述即可）：
- 高点1：[时间点] [情绪类型] [触发原因]
- 低点1：[时间点] [情绪类型] [触发原因]

#### 3.2 核心情绪点
记录视频中最能调动观众情绪的3个瞬间：
| 排名 | 时间点 | 情绪类型 | 调动方式 |
|-----|-------|---------|---------|
| 1 | | | |

#### 3.3 情绪调动技巧
分析是否使用了以下手段调动情绪：慢镜头、背景音乐、特写镜头、台词张力。

#### 3.4 观众情绪共鸣
分析观众可能在评论区表达最多的情绪是什么。

### 五、评论区互动点设计

#### 5.1 预埋互动点
记录视频中哪些台词或情节是专门为了引发评论设计的：
| 时间点 | 互动设计 | 预期评论类型 |
|-------|---------|------------|

#### 5.2 热门评论类型预测
预测评论区最多的评论类型：（站队型/预测型/共情型/吐槽型）

### 六、结束留钩子设计（决定下一集播放量）

| 分析项 | 内容 |
|-------|------|
| 钩子类型 | （危机型/悬念型/预告型/提问型） |
| 钩子具体内容 | （逐字记录最后5秒的画面、台词、音效和字幕） |
| 钩子强度 | （1-10分评分，说明理由） |
| 引导关注文字 | （视频结尾是否有引导关注的文字或语音？） |

### 七、钩子总评
用一句话总结本集的爆款逻辑：「前3秒[钩子类型] + [X]个反转 + 核心情绪[XX] + 结束留[钩子类型]」

用 Markdown 表格和结构化文字输出。{language_hint}"""
        resp = self._llm_call_with_retry(client,
            model=self.openai_model,
            messages=[
                {"role": "system", "content": "你是短剧钩子分析专家，擅长单集完播率、互动率和留存率的系统化分析。"},
                {"role": "user", "content": prompt}
            ], temperature=0.7, max_tokens=12000
        )
        return resp.choices[0].message.content

    def _llm_script(self, client, transcript, scene_desc, video_info, language_hint):
        # 长视频转写截断：超过12000字符时保留首尾+摘要
        MAX_TRANSCRIPT_LEN = 12000
        if len(transcript) > MAX_TRANSCRIPT_LEN:
            head = transcript[:4000]
            tail = transcript[-4000:]
            omitted = len(transcript) - 8000
            transcript = f"{head}\n\n...[中间省略 {omitted} 字符，共 {len(transcript)} 字符]...\n\n{tail}"
        # 根据视频时长决定场景分析策略（tokens 档位）
        duration = video_info.duration
        if duration > 1200:  # >20分钟
            detail_instruction = (
                "这是超长视频（>20分钟）。请按**每幕12个场景**分组，"
                "计算总幕数。每幕内列出12个场景（最后一幕可能不足）。"
            )
            max_tokens = 24000
        elif duration > 600:  # 10-20分钟
            detail_instruction = (
                "这是长视频（10-20分钟）。请先**估算全部重点场景总数**，然后按**每幕10个场景**分组，"
                "计算出一共需要多少幕（向上取整）。\n"
                "**每一幕都必须完整写出来**，幕标题格式为「第一幕：[幕主题]」「第二幕：[幕主题]」等。"
            )
            max_tokens = 21000
        elif duration > 300:  # 5-10分钟
            detail_instruction = (
                "这是中等长度视频（5-10分钟）。请先**估算全部重点场景总数**，然后按**每幕8个场景**分组，"
                "计算出一共需要多少幕（向上取整）。\n"
                "**每一幕都必须完整写出来**，幕标题格式为「第一幕：[幕主题]」「第二幕：[幕主题]」等。"
            )
            max_tokens = 18000
        elif duration > 180:  # 3-5分钟
            detail_instruction = (
                "这是中短视频（3-5分钟）。请按**所有场景**逐一拆解，不需要分幕。"
                "每个场景都要详细分析。"
            )
            max_tokens = 16000
        else:  # <3分钟
            detail_instruction = "请按**所有场景**逐一拆解，不需要分幕。每个场景都要详细分析。"
            max_tokens = 14000

        prompt = f"""你是专业的短剧剧本结构分析专家。请对以下视频进行完整的「结构化剧本与场景分析」。

## 视频信息
- 时长: {video_info.duration:.1f}秒

## 场景切割
{scene_desc}

## 语音转写文本
{transcript}

---

{detail_instruction}

请严格按照以下结构输出，必须包含【精简版】和【详细版】两部分：

## 核心要点（精简版）
用5-8条bullet points提炼最关键的结论，每条不超过20字，覆盖：场景总数、核心冲突、关键对白/金句、镜头特色、节奏评价。不要展开论述。
> 格式：- [结论要点]

---FULL---

### 一、场景概览表
用 Markdown 表格列出所有场景的关键信息：

| 场景编号 | 时间范围 | 地点 | 画面描述 | 对白要点 | 钩子功能 | 情绪张力 |
|---------|---------|------|---------|---------|---------|---------|
| 1 | 0s-15s | 客厅 | 女主摔门而入 | "你到底是谁？" | 开场悬念 | ★★★★ |

### 二、分幕场景详细分析
{'按幕分组，每幕10个场景（或8个场景），逐幕展开：' if duration > 300 else '对每个场景展开详细描述：'}

{'**第一幕：[幕主题]**\n\n' if duration > 300 else ''}对每个场景展开详细描述，必须包含以下所有要素：

#### 场景X：[场景名称]
| 分析项 | 内容 |
|-------|------|
| 时间范围 | 起止时间点 |
| 地点 | 场景发生场所 |
| 镜头类型 | （特写/近景/中景/远景/俯拍/仰拍等） |
| 画面描述 | 镜头内容和视觉要素，包括人物动作、表情、道具 |
| 对白/旁白 | 带情绪标注（如：[愤怒]"你到底是谁？"、[委屈]"我没想到会这样"） |
| 音效/BGM | 场景中的音效和背景音乐描述 |
| 钩子功能 | 该场景对观众的吸引点（悬念/反转/情感/冲突/铺垫等） |
| 情绪张力 | 1-5星评分，说明理由 |
| 场景转换 | 与下一场景的过渡方式（硬切/淡入淡出/匹配剪辑等） |

{'\n**第二幕：[幕主题]**\n\n（同上格式，继续展开）\n\n以此类推，直到所有幕写完。' if duration > 300 else ''}

### 三、关键场景深度解析
挑选3个最关键的场景（开场钩子场景、高潮反转场景、结尾留钩场景），每个展开深度分析：

| 分析维度 | 场景1：[名称] | 场景2：[名称] | 场景3：[名称] |
|---------|-------------|-------------|-------------|
| 为什么关键 | | | |
| 镜头手法 | | | |
| 情绪设计 | | | |
| 可优化点 | | | |

### 四、场景节奏分析
| 分析项 | 内容 |
|-------|------|
| 场景总数 | [X]个场景 |
| 平均场景时长 | [X]秒 |
| 最短场景 | 第[X]场景，[X]秒 |
| 最长场景 | 第[X]场景，[X]秒 |
| 节奏评价 | （快/中/慢，是否适合该类型短剧） |

### 五、字幕与对白设计（决定理解成本）

#### 5.1 字幕样式分析
| 分析项 | 内容 |
|-------|------|
| 字幕字体风格 | （如：粗黑体/综艺体/手写体） |
| 字号大小 | （大/中/小，是否适合移动端阅读？） |
| 字幕颜色 | （白字黑边/黄字/彩色关键词高亮？） |
| 位置与布局 | （底部居中/底部靠左/跟随说话人？是否有动画效果？） |

#### 5.2 对白风格（逐句记录）
按照剧本格式，逐句记录每个角色的对白内容：
```
【角色名】（情绪标签）：台词内容
【角色名】（情绪标签）：台词内容
...
```
> 如对白过多则只记录关键转折段落的对白。

#### 5.3 核心金句提取
| 排名 | 金句内容 | 说话人 | 情绪感染力 | 可传播性 |
|-----|---------|-------|-----------|---------|
| 1 | | | ★★★★★ | （高/中/低） |
| 2 | | | ★★★★ | |
| 3 | | | ★★★ | |

#### 5.4 口语化程度评估
| 分析项 | 评估结果 |
|-------|---------|
| 整体口语化评分 | （1-10分，10分为极度口语化） |
| 书面语占比 | （是否有明显的书面语或文绉绉的表达？举例说明） |
| 方言/地域特色 | （是否有方言或地域性表达？） |
| 对白节奏感 | （长短句搭配是否自然？是否有金句潜质？） |

### 六、场景与镜头语言专项（决定视觉吸引力）

#### 6.1 场景数量与类型
| 场景编号 | 场景类型 | 时间占比 | 功能定位 |
|---------|---------|---------|---------|
| 场景1 | （室内/室外/车内/办公室/餐厅等） | | （推动剧情/情感渲染/冲突爆发/悬念铺垫） |

#### 6.2 核心冲突场景设计
| 分析项 | 内容 |
|-------|------|
| 核心冲突发生场景 | （哪个场景承载了最大冲突？） |
| 场景如何服务于剧情 | （场景选择是否合理？有没有更好的替代场景？） |
| 道具运用 | （关键道具及其象征意义） |

#### 6.3 镜头运用清单
| 分析项 | 使用情况 | 具体位置/作用 |
|-------|---------|--------------|
| 特写镜头 | （使用次数） | （用于什么情绪/谁的表情？） |
| 近景镜头 | （使用次数） | （用于哪些对话场景？） |
| 中景镜头 | （使用次数） | （用于哪些互动场景？） |
| 远景/全景 | （使用次数） | （用于环境交代或群体场面？） |
| 运动镜头 | （推/拉/摇/移/跟拍） | （具体运镜方式和目的） |

#### 6.4 转场节奏统计
| 分析项 | 内容 |
|-------|------|
| 总镜头数（估算） | [X]个 |
| 平均镜头时长 | [X]秒 |
| 最短镜头 | [X]秒（用于什么？） |
| 最长镜头 | [X]秒（用于什么？） |
| 转场方式统计 | （硬切[X]次 / 淡入淡出[X]次 / 匹配剪辑[X]次 / 其他[X]次） |
| 剪辑节奏评价 | （紧凑/舒缓/松散，是否符合该类型短剧的视觉节奏预期？） |

请确保不遗漏任何场景，用 Markdown 表格和结构化文字输出，层次分明。{language_hint}"""
        resp = self._llm_call_with_retry(client,
            model=self.openai_model,
            messages=[
                {"role": "system", "content": "你是短剧剧本结构分析专家，擅长按场景完整拆解剧本结构，精通镜头语言和情绪节奏分析。"},
                {"role": "user", "content": prompt}
            ], temperature=0.7, max_tokens=max_tokens
        )
        return resp.choices[0].message.content

    def _llm_characters(self, client, transcript, video_info, language_hint):
        # 长视频转写截断
        MAX_TRANSCRIPT_LEN = 12000
        if len(transcript) > MAX_TRANSCRIPT_LEN:
            head = transcript[:4000]
            tail = transcript[-4000:]
            omitted = len(transcript) - 8000
            transcript = f"{head}\n\n...[中间省略 {omitted} 字符]...\n\n{tail}"
        prompt = f"""你是专业的短剧人物关系分析专家。请对以下视频进行完整的「人物图谱与角色塑造分析」。

## 视频信息
- 时长: {video_info.duration:.1f}秒

## 语音转写文本
{transcript}

---

请严格按照以下结构输出，必须包含【精简版】和【详细版】两部分：

## 核心要点（精简版）
用5-8条bullet points提炼最关键的结论，每条不超过20字，覆盖：角色总数、主角关系、核心冲突方、隐藏身份、情感线走向。不要展开论述。
> 格式：- [结论要点]

---FULL---

### 一、核心出场人数
| 分析项 | 内容 |
|-------|------|
| 有名有姓有台词的角色数 | [X]人 |
| 主要人物（戏份占比>15%） | [X]人 |
| 次要人物（戏份占比5-15%） | [X]人 |
| 功能性人物（戏份占比<5%） | [X]人 |

### 二、人物概览表
用 Markdown 表格列出所有人物：

| 角色 | 身份/职业 | 核心特征 | 出场频次 | 戏份占比 | 角色功能 |
|------|---------|---------|---------|---------|---------|
| 小美 | 豪门儿媳 | 倔强独立、隐忍 | 高 | 45% | 推动冲突 |

### 三、主角深度分析

#### 3.1 主角核心标签
| 分析项 | 内容 |
|-------|------|
| 性格标签1 | （如：倔强独立） |
| 性格标签2 | （如：隐忍负重） |
| 性格标签3 | （如：善良心软） |
| 核心目标 | （如：夺回家产、复仇、寻亲） |
| 核心矛盾 | （内在矛盾，如：善良vs复仇） |
| 一句话人设 | （如：被全家嫌弃的千亿千金） |

#### 3.2 主角关键台词
列出主角最经典的3-5句台词，每句标注情绪和场景：
| 台词 | 情绪标注 | 所在场景 |
|-----|---------|---------|
| "你以为我会一直忍下去吗？" | [隐忍→爆发] | 第5场景 |

### 四、反派塑造分析
| 分析项 | 内容 |
|-------|------|
| 核心特征 | （如：贪慕虚荣、两面三刀） |
| 作恶方式 | （如：言语羞辱、栽赃陷害、抢夺家产） |
| 可恨程度 | 1-10分，说明理由 |
| 与主角的冲突点 | （具体说明反派如何推动主角成长） |
| 反派是否有魅力 | （是否有让观众"又恨又爱"的特质？） |

### 五、人物关系图

#### 5.1 人物关系表
| 人物A | 人物B | 关系 | 张力类型 | 冲突描述 |
|-------|-------|------|---------|---------|
| 小美 | 阿强 | 恋人→仇人 | 情感冲突 | 被背叛后的报复 |

#### 5.2 关系网络可视化
用文字图示展示人物关系网络，标注每条关系的性质：
```
    [婆婆] ──打压──→ [小美] ←──爱── [阿强]
       │                │              │
     利用              反抗          背叛
       ↓                ↓              ↓
    [小三] ←──合谋──→ [阿强]
```

### 六、人物弧光分析
对每个主要人物分析其本集的成长或转变：

| 角色 | 起始状态 | 触发事件 | 转变方向 | 结束状态 |
|------|---------|---------|---------|---------|
| 小美 | 隐忍退让 | 被当众羞辱 | 觉醒反击 | 亮出身份 |

### 七、角色塑造总评
| 分析项 | 内容 |
|-------|------|
| 最成功角色 | （哪个角色塑造最成功？为什么？） |
| 最薄弱角色 | （哪个角色缺乏立体感？如何改进？） |
| 人物关系设计亮点 | （最精彩的人物关系冲突是什么？） |
| 改进建议 | （人物塑造方面有什么可优化的？） |

用 Markdown 表格和结构化文字输出。{language_hint}"""
        resp = self._llm_call_with_retry(client,
            model=self.openai_model,
            messages=[
                {"role": "system", "content": "你是短剧人物关系分析专家，擅长角色塑造、人物弧光和关系张力分析。"},
                {"role": "user", "content": prompt}
            ], temperature=0.7, max_tokens=10000
        )
        return resp.choices[0].message.content

    def _llm_rewrite(self, client, transcript, scene_desc, video_info, language_hint):
        # 长视频转写截断
        MAX_TRANSCRIPT_LEN = 12000
        if len(transcript) > MAX_TRANSCRIPT_LEN:
            head = transcript[:4000]
            tail = transcript[-4000:]
            omitted = len(transcript) - 8000
            transcript = f"{head}\n\n...[中间省略 {omitted} 字符]...\n\n{tail}"
        prompt = f"""你是专业的短剧改写顾问。请对以下视频进行完整的「改写方向与实操建议分析」。

## 视频信息
- 时长: {video_info.duration:.1f}秒

## 场景切割
{scene_desc}

## 语音转写文本
{transcript}

---

请严格按照以下结构输出，必须包含【精简版】和【详细版】两部分：

## 核心要点（精简版）
用5-8条bullet points提炼最关键的结论，每条不超过20字，覆盖：最推荐改写方向、核心改写点、预估提升指标、付费墙建议。不要展开论述。
> 格式：- [结论要点]

---FULL---

### 零、IAA分账核心指标与转化留存分析

> **IAA分账权重公式：完播率(40%) > 评论率(25%) > 转发率(20%) > 点赞率(15%)**
> 改写的首要目标是提升完播率，其次引导评论互动。

#### 0.1 当前视频的各指标表现评估
| 指标 | 权重 | 当前预估表现 | 瓶颈因素 | 改写优先级 |
|-----|------|-----------|---------|-----------|
| 完播率 | 40% | （高/中/低） | （钩子弱？反转少？节奏拖？） | ★★★★★ |
| 评论率 | 25% | （高/中/低） | （缺少争议点？互动设计不足？） | ★★★★ |
| 转发率 | 20% | （高/中/低） | （缺金句？缺共鸣反转？） | ★★★ |
| 点赞率 | 15% | （高/中/低） | （情绪高点不够燃？） | ★★ |

#### 0.2 转化与留存设计现状
| 分析项 | 当前状态 | 改进空间 |
|-------|---------|---------|
| 评论互动点预埋 | （当前有哪些台词/情节引发评论？够不够？） | |
| 结束留钩子强度 | （当前结尾留钩类型和强度1-10分） | |
| 付费墙位置建议 | （如果这是多集短剧，建议在第几集设付费墙？） | |

### 一、原剧弱点分析

| 序号 | 弱点类型 | 具体问题 | 影响程度 | 改进方向 |
|-----|---------|---------|---------|---------|
| 1 | （如：节奏拖沓/人设单薄/钩子不足/反转老套/情绪断裂） | | ★★★ | |

### 二、五种改写方向

#### 方向A：升级原版（保留核心设定，优化细节）
| 分析项 | 内容 |
|-------|------|
| 改写核心 | 在原版基础上强化钩子、加快节奏、优化人设 |
| 保留元素 | （列出原版中必须保留的3个核心亮点） |
| 优化要点1 | （如：开场3秒增加冲突爆发） |
| 优化要点2 | （如：反转铺垫更隐蔽，揭晓更震撼） |
| 优化要点3 | （如：主角人设增加一个反差标签） |
| 示例场景 | 写出改写后的开场30秒剧本片段 |

#### 方向B：视角翻转（换一个人物视角重述故事）
| 分析项 | 内容 |
|-------|------|
| 改写核心 | 从反派/配角/旁观者视角重新讲述 |
| 新视角选择 | （选择哪个角色？为什么？） |
| 新叙事逻辑 | （翻转后的故事走向） |
| 新钩子设计 | （新视角下如何设计开场钩子？） |
| 示例场景 | 写出改写后的开场30秒剧本片段 |

#### 方向C：预知能力（给主角一个预知/重生的金手指）
| 分析项 | 内容 |
|-------|------|
| 改写核心 | 主角获得预知未来/回到过去的能力 |
| 金手指设定 | （具体能力描述和限制条件） |
| 新冲突设计 | （知道未来却无法改变的痛苦/选择） |
| 情绪反转点 | （预知失败/预知成功的反差） |
| 示例场景 | 写出改写后的开场30秒剧本片段 |

#### 方向D：悬疑解谜（加入推理/揭秘元素）
| 分析项 | 内容 |
|-------|------|
| 改写核心 | 将故事改造为悬疑推理型 |
| 核心谜题 | （设计一个贯穿全剧的谜题） |
| 线索铺垫 | （如何散布线索，让观众参与推理？） |
| 揭秘时机 | （第几集揭秘？如何制造意外？） |
| 示例场景 | 写出改写后的开场30秒剧本片段 |

#### 方向E：爽文反杀（重生/系统/打脸爽文模式）
| 分析项 | 内容 |
|-------|------|
| 改写核心 | 主角从被欺压到逆袭反杀的爽文路线 |
| 反杀触发 | （什么事件触发主角的反杀？） |
| 打脸节奏 | （设计3次递进的打脸场景） |
| 爽感高潮 | （最大的爽点在哪里？如何铺垫？） |
| 示例场景 | 写出改写后的开场30秒剧本片段 |

### 三、后续钩子设计

#### 3.1 每集结尾钩子建议
| 集数 | 钩子类型 | 钩子内容 | 留念强度 |
|-----|---------|---------|---------|
| 第1集 | 危机型 | ... | ★★★★★ |

#### 3.2 付费墙设计
| 付费位置 | 之前的钩子 | 之后的悬念 | 预期转化率 |
|---------|----------|----------|----------|
| 第3集结尾 | | | |

### 四、改写优先级建议
| 排名 | 改写方向 | 推荐理由 | 预期效果 | 实施难度 |
|-----|---------|---------|---------|---------|
| 1 | （最推荐的方向） | | | ★★★ |

用 Markdown 表格和结构化文字输出。{language_hint}"""
        resp = self._llm_call_with_retry(client,
            model=self.openai_model,
            messages=[
                {"role": "system", "content": "你是短剧改写顾问，擅长付费转化、钩子设计和多方向改写策略。"},
                {"role": "user", "content": prompt}
            ], temperature=0.7, max_tokens=14000
        )
        return resp.choices[0].message.content

    def _llm_north_america(self, client, transcript, scene_desc, video_info, language_hint):
        """北美改编分析：基于爆款短剧分析框架，生成北美市场改编建议"""
        MAX_TRANSCRIPT_LEN = 12000
        if len(transcript) > MAX_TRANSCRIPT_LEN:
            head = transcript[:4000]
            tail = transcript[-4000:]
            omitted = len(transcript) - 8000
            transcript = f"{head}\n\n...[中间省略 {omitted} 字符]...\n\n{tail}"

        prompt = f"""你是专业的北美短剧改编顾问，精通 TikTok 美加区短剧市场。请基于以下视频内容，输出一份完整的「北美改编分析报告」。

## 视频信息
- 时长: {video_info.duration:.1f}秒

## 场景切割
{scene_desc}

## 语音转写文本
{transcript}

---

请严格按照以下结构输出，必须包含【精简版】和【详细版】两部分：

## 核心要点（精简版）
用5-8条bullet points提炼最关键的结论，每条不超过20字，覆盖：北美适配度、最需修改的文化点、目标受众差异、关键改编建议。不要展开论述。
> 格式：- [结论要点]

---FULL---

### 一、爆款公式总结
用一句话总结本集的爆款逻辑，格式：「前3秒[钩子类型] + [X]个反转 + 核心情绪[XX] + 结束留[钩子类型]」
示例：「被婆婆当众羞辱的儿媳亮出亿万身家打脸 + 最后婆婆跪地求饶 + 下一集揭秘儿媳真实身份」

### 二、核心内容拆解

#### 2.1 前3秒钩子分析
| 分析项 | 原版内容 | 北美改编建议 |
|-------|---------|--------------|
| 钩子类型 | （冲突爆发型/悬念提问型/结果前置型/视觉冲击型/情绪反差型） | 欧美偏好：冲突爆发型和结果前置型，避免含蓄悬念 |
| 钩子具体内容 | （记录前5秒画面、台词、音效、字幕） | 必须第1秒就出现核心冲突 |
| 钩子技巧 | （特写/放大音效/加粗字幕/快速剪辑） | 大特写 + 大声效 + 全大写加粗字幕 |

#### 2.2 剧情节奏与反转
| 分析项 | 原版内容 | 北美改编建议 |
|-------|---------|--------------|
| 时间节点划分 | （0-3s钩子/3-20s铺垫/20-45s发展/45-70s高潮/70-90s留钩子） | 每15-20秒必须有小高潮或反转 |
| 反转数量与时间点 | （几个反转？第几秒？） | 最优：70秒视频=2小反转+1大反转，最后反转在60-70秒 |
| 反转类型 | （身份/真相/立场/因果/打脸） | 欧美最吃：打脸反转和身份反转 |
| 反转铺垫 | （伏笔是否明显但不剧透？） | 伏笔要明显，让观众有"原来如此"感 |

#### 2.3 人物塑造
| 分析项 | 原版内容 | 北美改编建议 |
|-------|---------|--------------|
| 核心出场人数 | （有名有姓有台词的角色数） | 每集最多3个主要人物 |
| 主角核心标签 | （3个性格标签+1个核心目标） | 必须标签化、扁平化 |
| 反派塑造 | （核心特征/作恶方式/可恨程度） | 反派必须脸谱化，坏得纯粹 |
| 人物弧光 | （本集是否有成长或转变？） | 每集都要有微小的成长或态度转变 |

#### 2.4 情绪调动
| 分析项 | 原版内容 | 北美改编建议 |
|-------|---------|--------------|
| 情绪曲线 | （画出情绪起伏：愤怒→期待→解气→悬念等） | 最优曲线：愤怒→期待→解气→悬念 |
| 核心情绪点 | （最调动情绪的3个瞬间） | 重点放大愤怒和解气 |
| 情绪调动技巧 | （慢镜头/BGM/特写/台词） | 情绪感染力强的BGM+高潮慢镜头特写 |

#### 2.5 字幕与对白
| 分析项 | 原版内容 | 北美改编建议 |
|-------|---------|--------------|
| 字幕样式 | （字体/大小/颜色/位置） | 全大写英文字幕，加粗，强对比，屏幕下方1/3 |
| 对白内容 | （记录核心对白） | 每句不超过10个单词，时长不超过2秒 |
| 核心台词 | （最经典的3句） | 设计金句，让观众愿意引用和分享 |

#### 2.6 场景与镜头
| 分析项 | 原版内容 | 北美改编建议 |
|-------|---------|--------------|
| 场景数量与类型 | （几个场景？什么类型？） | 每集最多2-3个场景，优先室内 |
| 镜头运用 | （特写/近景/中景/远景） | 多使用特写和近景，突出表情和情绪 |
| 剪辑节奏 | （平均镜头时长） | 平均1-2秒，高潮部分加快 |

### 三、转化与留存设计

#### 3.1 评论区互动点
| 分析项 | 原版内容 | 北美改编建议 |
|-------|---------|--------------|
| 预埋互动点 | （哪些台词/情节是设计来引发评论的？） | 设计开放式问题或争议性话题 |
| 热门评论类型 | （站队型/预测型/共情型/吐槽型） | 针对性设计站队型和预测型评论 |
| 作者回复策略 | （是否回复热门评论？） | 积极回复前100条评论 |

#### 3.2 结束留钩子
| 分析项 | 原版内容 | 北美改编建议 |
|-------|---------|--------------|
| 钩子类型 | （危机型/悬念型/预告型/提问型） | 最优：危机型和悬念型 |
| 钩子具体内容 | （最后5秒的画面、台词、音效、字幕） | 最后一句话必须是疑问句或未完待续 |
| 钩子强度 | （1-10分） | 强度越高越好 |
| 引导关注文字 | （是否有引导关注？） | 最后3秒加上"Follow for Part 2"文字和箭头 |

### 四、改编实操

#### 可直接复用的元素
1. **可复用情节**（3-5个可以直接改编到欧美背景的情节）
2. **可复用台词**（3-5句可以直接翻译成英文的经典台词，附英文翻译）
3. **可复用镜头**（3-5个可以直接模仿的镜头和剪辑手法）

#### 改编风险点
列出3-5个在欧美市场可能水土不服的元素，说明原因

#### 修改建议
根据以上分析，分项给出具体的修改建议

### 五、欧美改编专项检查表
- [ ] 所有中国特有的文化梗、节日、习俗都已替换为欧美通用元素
- [ ] 人物的职业、身份、价值观符合欧美社会的认知
- [ ] 对白全部使用日常口语，没有中式英语
- [ ] 场景和道具符合欧美家庭和工作环境的实际情况
- [ ] 没有涉及欧美敏感话题（如种族、宗教、政治）

{language_hint}"""

        resp = self._llm_call_with_retry(client,
            model=self.openai_model,
            messages=[
                {"role": "system", "content": "你是专业的北美短剧改编顾问，精通 TikTok 美加区短剧市场，擅长将中国爆款短剧改编为北美市场版本。"},
                {"role": "user", "content": prompt}
            ], temperature=0.7, max_tokens=12000
        )
        return resp.choices[0].message.content

    def step5_llm_analyze(self, transcript: str, segments: list, scenes: list, video_info: VideoInfo,
                          progress_cb: Callable = None) -> dict:
        if not self.openai_api_key:
            return {
                "hooks_analysis": "⚠️ 未配置 OpenAI API Key，跳过 LLM 分析。\n请在设置中填入 API Key 后重新分析。",
                "script_structure": "", "character_map": "", "rewrite_suggestions": "", "north_america": "",
                "enriched_segments": [], "bgm_info": ""
            }
        if progress_cb:
            progress_cb("正在连接 AI 服务...")
        try:
            client = self._get_client()
        except Exception as e:
            return {
                "hooks_analysis": f"❌ AI 服务初始化失败: {str(e)}", "script_structure": "",
                "character_map": "", "rewrite_suggestions": "", "north_america": "",
                "enriched_segments": [], "bgm_info": ""
            }
        if progress_cb:
            progress_cb("正在进行 AI 剧本分析（6模块并行）...")
        scene_desc = "\n".join([f"场景{s.index}: {s.start}s-{s.end}s (时长{s.duration}s)" for s in scenes])

        # 语言提示
        lang_hint = ""
        if self.language == "zh":
            lang_hint = "\n请用中文输出。"
        elif self.language == "en":
            lang_hint = "\nPlease output in English."

        # 转写段落的JSON字符串（用于enrichment）
        import json as _json
        segments_json = _json.dumps(segments, ensure_ascii=False, indent=2)

        # 6 个并行分析任务
        tasks = {
            "hooks_analysis": ("钩子分析", self._llm_hooks, [client, transcript, scene_desc, video_info, lang_hint]),
            "script_structure": ("结构化剧本", self._llm_script, [client, transcript, scene_desc, video_info, lang_hint]),
            "character_map": ("人物图谱", self._llm_characters, [client, transcript, video_info, lang_hint]),
            "rewrite_suggestions": ("改写建议", self._llm_rewrite, [client, transcript, scene_desc, video_info, lang_hint]),
            "north_america": ("北美改编", self._llm_north_america, [client, transcript, scene_desc, video_info, lang_hint]),
            "enrich": ("角色标注与BGM识别", self._llm_enrich_transcript, [client, segments_json, video_info, lang_hint]),
        }

        results = {"enriched_segments": [], "bgm_info": ""}
        completed = 0
        total = len(tasks)

        with ThreadPoolExecutor(max_workers=6) as executor:
            future_to_key = {}
            for key, (label, fn, args) in tasks.items():
                future = executor.submit(fn, *args)
                future_to_key[future] = (key, label)

            for future in as_completed(future_to_key):
                key, label = future_to_key[future]
                try:
                    raw = future.result()
                    if key == "enrich":
                        enriched, bgm = self._parse_enriched(raw)
                        results["enriched_segments"] = enriched or []
                        results["bgm_info"] = bgm or ""
                    else:
                        results[key] = raw
                    completed += 1
                    if progress_cb:
                        progress_cb(f"✅ {label}完成 ({completed}/{total})")
                except Exception as e:
                    err_msg = str(e)
                    if "timed out" in err_msg.lower() or "timeout" in err_msg.lower():
                        if key == "script":
                            err_msg = "结构化剧本生成超时（内容量大），建议换更快的模型或缩短视频时长"
                        else:
                            err_msg = "连接超时，请检查网络或设置 API 代理地址"
                    elif "connection" in err_msg.lower():
                        err_msg = "无法连接 AI 服务，请检查网络或设置 API 代理地址"
                    if key == "enrich":
                        results["enriched_segments"] = []
                        results["bgm_info"] = f"❌ {err_msg}"
                    else:
                        results[key] = f"❌ {label}失败: {err_msg}"
                    completed += 1
                    if progress_cb:
                        progress_cb(f"❌ {label}失败 ({completed}/{total})")

        return results

    def run(self, video_path: str, progress_cb: Callable = None,
            source: str = "local", platform: str = "", video_title: str = "") -> AnalysisResult:
        result = AnalysisResult()
        try:
            self._ensure_ffmpeg()
            if progress_cb:
                progress_cb("正在获取视频信息...")
            result.video_info = self.step1_get_video_info(video_path)
            result.video_info.source = source
            result.video_info.platform = platform
            result.video_info.title = video_title
            audio_path = self.step2_extract_audio(video_path, progress_cb)
            whisper_result = self.step3_transcribe(audio_path, progress_cb)
            result.transcript_text = whisper_result.get("text", "")
            raw_segments = [{"start": round(seg["start"], 1), "end": round(seg["end"], 1), "text": seg["text"].strip()} for seg in whisper_result.get("segments", [])]
            # 去重：移除连续重复的段落
            deduped = []
            for seg in raw_segments:
                if deduped and seg["text"] == deduped[-1]["text"]:
                    continue  # 跳过与上一段完全相同的文本
                deduped.append(seg)
            result.transcript_segments = deduped
            result.scenes = self.step4_detect_scenes(video_path, progress_cb)
            llm_result = self.step5_llm_analyze(result.transcript_text, raw_segments, result.scenes, result.video_info, progress_cb)
            result.hooks_analysis = llm_result.get("hooks_analysis", "")
            result.script_structure = llm_result.get("script_structure", "")
            result.character_map = llm_result.get("character_map", "")
            result.rewrite_suggestions = llm_result.get("rewrite_suggestions", "")
            result.north_america = llm_result.get("north_america", "")
            result.enriched_segments = llm_result.get("enriched_segments", [])
            result.bgm_info = llm_result.get("bgm_info", "")
            result.full_report = self._generate_report(result)
            if progress_cb:
                progress_cb("✅ 分析完成！")
        except Exception as e:
            result.error = str(e)
            if progress_cb:
                progress_cb(f"❌ 分析失败: {str(e)}")
        return result

    def _generate_report(self, result: AnalysisResult) -> str:
        vi = result.video_info
        source_info = ""
        if vi.source == "url" and vi.platform:
            source_info = f"\n- 来源: {vi.platform}（链接下载）"
        if vi.title:
            source_info += f"\n- 标题: {vi.title}"
        report = f"""# 短剧拆解报告

## 视频信息
- 文件: {os.path.basename(vi.path)}
- 时长: {vi.duration:.1f}秒
- 分辨率: {vi.width}×{vi.height}
- 文件大小: {vi.size_mb:.1f}MB{source_info}

## 转写文本（带时间戳）
"""
        for seg in result.transcript_segments:
            report += f"[{seg['start']}s - {seg['end']}s] {seg['text']}\n"
        report += "\n## 场景切割\n"
        for s in result.scenes:
            report += f"- 场景{s.index}: {s.start}s → {s.end}s (时长{s.duration}s)\n"
        if result.hooks_analysis:
            report += f"\n## 钩子结构分析\n{result.hooks_analysis}\n"
        if result.script_structure:
            report += f"\n## 结构化剧本\n{result.script_structure}\n"
        if result.character_map:
            report += f"\n## 人物图谱\n{result.character_map}\n"
        if result.rewrite_suggestions:
            report += f"\n## 改写建议\n{result.rewrite_suggestions}\n"
        if result.north_america:
            report += f"\n## 北美改编分析\n{result.north_america}\n"
        return report
