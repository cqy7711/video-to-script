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
    full_report: str = ""
    error: str = ""


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
            temperature=0.3, max_tokens=2000
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
        prompt = f"""你是专业的短剧钩子分析专家。分析以下视频的钩子结构。

## 视频信息
- 时长: {video_info.duration:.1f}秒 | 分辨率: {video_info.width}×{video_info.height}

## 场景切割
{scene_desc}

## 语音转写文本
{transcript}

---

识别视频中所有钩子，按时间线排列。

### 钩子概览表
先用 Markdown 表格列出所有钩子的关键信息：

| 时间点 | 钩子类型 | 对应原文 | 付费驱动 |
|-------|---------|---------|---------|
| 0:15 | 开场悬念 | "你到底是谁？" | ★★★ |

### 钩子详细分析
然后对每个钩子展开分析，包含：出现时间点、对应原文、钩子类型（开场悬念钩/反转钩/证据钩/倒计时钩/情感钩/恐惧钩/身份钩/呼应钩）、为什么有效、付费驱动效果。用 Markdown 格式输出。{language_hint}"""
        resp = self._llm_call_with_retry(client,
            model=self.openai_model,
            messages=[
                {"role": "system", "content": "你是短剧钩子分析专家，擅长钩子设计和付费转化分析。"},
                {"role": "user", "content": prompt}
            ], temperature=0.7, max_tokens=2000
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
        # 根据视频时长决定每幕重点场景数量
        duration = video_info.duration
        if duration > 600:  # >10分钟
            detail_instruction = "这是长视频，**每一幕必须提炼至少10个重点场景**，确保分析深度和完整性。"
        elif duration > 300:  # >5分钟
            detail_instruction = "这是中等长度视频，**每一幕提炼8个重点场景**。"
        else:
            detail_instruction = "请按**所有场景**逐一拆解。"

        prompt = f"""你是专业的短剧剧本结构分析专家。分析以下视频的结构化剧本。

## 视频信息
- 时长: {video_info.duration:.1f}秒

## 场景切割
{scene_desc}

## 语音转写文本
{transcript}

---

{detail_instruction}

请按以下格式输出：

### 场景概览表
用 Markdown 表格列出所有场景的关键信息：

| 场景编号 | 时间范围 | 地点 | 钩子功能 |
|---------|---------|------|---------|
| 1 | 0s-15s | 客厅 | 开场悬念 |

### 场景详细分析
对每个场景展开详细描述，包含：
- **场景编号**：序号标注
- **时间范围**：起止时间点
- **地点**：场景发生场所
- **画面描述**：镜头内容和视觉要素
- **对白/旁白**：带情绪标注（如：[愤怒]、[委屈]、[冷漠]）
- **钩子功能**：该场景对观众的吸引点（悬念/反转/情感/冲突等）

请确保不遗漏任何场景，用 Markdown 格式输出，层次分明。{language_hint}"""
        resp = self._llm_call_with_retry(client,
            model=self.openai_model,
            messages=[
                {"role": "system", "content": "你是短剧剧本结构分析专家，擅长按场景完整拆解剧本结构。"},
                {"role": "user", "content": prompt}
            ], temperature=0.7, max_tokens=6000 if duration > 600 else 4000
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
        prompt = f"""你是专业的短剧人物关系分析专家。分析以下视频中的人物图谱。

## 视频信息
- 时长: {video_info.duration:.1f}秒

## 语音转写文本
{transcript}

---

分析人物图谱，请按以下格式输出：

### 人物概览表
先用 Markdown 表格列出所有人物：

| 角色 | 身份 | 核心特征 | 出场频次 |
|------|------|---------|---------|
| 小美 | 女主角 | 倔强独立 | 高 |

### 人物关系表
用表格展示人物之间的关系：

| 人物A | 人物B | 关系 | 张力类型 |
|-------|-------|------|---------|
| 小美 | 阿强 | 恋人→仇人 | 情感冲突 |

### 人物详细分析
然后对每个角色展开分析，包含核心特征、动机、成长弧线、关键台词等。用文字图示展示人物关系网络。用 Markdown 格式输出。{language_hint}"""
        resp = self._llm_call_with_retry(client,
            model=self.openai_model,
            messages=[
                {"role": "system", "content": "你是短剧人物关系分析专家。"},
                {"role": "user", "content": prompt}
            ], temperature=0.7, max_tokens=2000
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
        prompt = f"""你是专业的短剧改写顾问。为以下视频提供改写建议。

## 视频信息
- 时长: {video_info.duration:.1f}秒

## 场景切割
{scene_desc}

## 语音转写文本
{transcript}

---

请输出：1) 原剧弱点（3个）；2) 5种改写方向（A升级原版/B视角翻转/C设定变更/D类型转换/E市场导向）；3) 后续钩子设计；4) 付费节点建议。用 Markdown 格式输出。{language_hint}"""
        resp = self._llm_call_with_retry(client,
            model=self.openai_model,
            messages=[
                {"role": "system", "content": "你是短剧改写顾问，擅长付费转化和钩子设计。"},
                {"role": "user", "content": prompt}
            ], temperature=0.7, max_tokens=2000
        )
        return resp.choices[0].message.content

    def step5_llm_analyze(self, transcript: str, segments: list, scenes: list, video_info: VideoInfo,
                          progress_cb: Callable = None) -> dict:
        if not self.openai_api_key:
            return {
                "hooks_analysis": "⚠️ 未配置 OpenAI API Key，跳过 LLM 分析。\n请在设置中填入 API Key 后重新分析。",
                "script_structure": "", "character_map": "", "rewrite_suggestions": "",
                "enriched_segments": [], "bgm_info": ""
            }
        if progress_cb:
            progress_cb("正在连接 AI 服务...")
        try:
            client = self._get_client()
        except Exception as e:
            return {
                "hooks_analysis": f"❌ AI 服务初始化失败: {str(e)}", "script_structure": "",
                "character_map": "", "rewrite_suggestions": "",
                "enriched_segments": [], "bgm_info": ""
            }
        if progress_cb:
            progress_cb("正在进行 AI 剧本分析（5模块并行）...")
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

        # 5 个并行分析任务
        tasks = {
            "hooks_analysis": ("钩子分析", self._llm_hooks, [client, transcript, scene_desc, video_info, lang_hint]),
            "script_structure": ("结构化剧本", self._llm_script, [client, transcript, scene_desc, video_info, lang_hint]),
            "character_map": ("人物图谱", self._llm_characters, [client, transcript, video_info, lang_hint]),
            "rewrite_suggestions": ("改写建议", self._llm_rewrite, [client, transcript, scene_desc, video_info, lang_hint]),
            "enrich": ("角色标注与BGM识别", self._llm_enrich_transcript, [client, segments_json, video_info, lang_hint]),
        }

        results = {"enriched_segments": [], "bgm_info": ""}
        completed = 0
        total = len(tasks)

        with ThreadPoolExecutor(max_workers=5) as executor:
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
        return report
