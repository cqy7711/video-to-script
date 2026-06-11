"""核心 Pipeline — 视频→剧本分析全流程"""

import os
import json
import subprocess
import tempfile
import shutil
from dataclasses import dataclass, field
from typing import Optional, Callable

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
                 language: str = None,
                 work_dir: str = ""):
        self.whisper_model_name = whisper_model
        self.scene_threshold = scene_threshold
        self.min_scene_duration = min_scene_duration
        self.openai_api_key = openai_api_key
        self.openai_model = openai_model
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
        raw_audio = os.path.join(self.work_dir, "audio_raw.wav")
        resampled_audio = os.path.join(self.work_dir, "audio_16k.wav")
        clip = VideoFileClip(video_path)
        clip.audio.write_audiofile(raw_audio, logger=None)
        clip.close()
        self._run_ffmpeg(["-y", "-i", raw_audio, "-ar", "16000", "-ac", "1", resampled_audio])
        if os.path.exists(raw_audio):
            os.remove(raw_audio)
        return resampled_audio

    def step3_transcribe(self, audio_path: str, progress_cb: Callable = None) -> dict:
        if progress_cb:
            progress_cb("正在加载 Whisper 模型...")
        if self._whisper_model is None:
            self._whisper_model = whisper.load_model(self.whisper_model_name)
        if progress_cb:
            progress_cb("正在进行语音转写...")
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

    def step5_llm_analyze(self, transcript: str, scenes: list, video_info: VideoInfo,
                          progress_cb: Callable = None) -> dict:
        if not self.openai_api_key:
            return {
                "hooks_analysis": "⚠️ 未配置 OpenAI API Key，跳过 LLM 分析。\n请在设置中填入 API Key 后重新分析。",
                "script_structure": "", "character_map": "", "rewrite_suggestions": ""
            }
        if progress_cb:
            progress_cb("正在进行 AI 剧本分析...")
        from openai import OpenAI
        client = OpenAI(api_key=self.openai_api_key)
        scene_desc = "\n".join([f"场景{s.index}: {s.start}s-{s.end}s (时长{s.duration}s)" for s in scenes])
        prompt = f"""你是一个专业的短剧剧本分析专家。请对以下视频内容进行深度拆解。

## 视频信息
- 时长: {video_info.duration:.1f}秒
- 分辨率: {video_info.width}×{video_info.height}

## 场景切割
{scene_desc}

## 语音转写文本
{transcript}

---

请按以下结构输出分析结果（用 Markdown 格式）：

### 一、钩子结构分析
识别视频中所有钩子，按时间线排列。每个钩子标注：出现时间点、对应原文、钩子类型（开场悬念钩/反转钩/证据钩/倒计时钩/情感钩/恐惧钩/身份钩/呼应钩）、为什么有效、付费驱动效果。

### 二、结构化剧本
按场景拆解，每个场景包含：场景编号·地点·时间、画面描述、对白/旁白（带情绪标注）、钩子功能。

### 三、人物图谱
用文字图示展示人物关系网络，标注关系张力。

### 四、改写建议
原剧弱点（3个）、5种改写方向（A升级原版/B视角翻转/C设定变更/D类型转换/E市场导向）、后续钩子设计、付费节点建议。"""
        try:
            response = client.chat.completions.create(
                model=self.openai_model,
                messages=[
                    {"role": "system", "content": "你是专业的短剧剧本分析专家，擅长钩子设计和付费转化分析。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7, max_tokens=4000
            )
            analysis_text = response.choices[0].message.content
            sections = {"hooks_analysis": "", "script_structure": "", "character_map": "", "rewrite_suggestions": ""}
            current_section = None
            section_map = {"一、钩子": "hooks_analysis", "二、结构化剧本": "script_structure", "三、人物图谱": "character_map", "四、改写建议": "rewrite_suggestions"}
            for line in analysis_text.split("\n"):
                for key, field_name in section_map.items():
                    if key in line:
                        current_section = field_name
                        break
                if current_section:
                    sections[current_section] += line + "\n"
            if not any(sections.values()):
                sections["hooks_analysis"] = analysis_text
            return sections
        except Exception as e:
            return {"hooks_analysis": f"❌ LLM 分析失败: {str(e)}", "script_structure": "", "character_map": "", "rewrite_suggestions": ""}

    def run(self, video_path: str, progress_cb: Callable = None) -> AnalysisResult:
        result = AnalysisResult()
        try:
            self._ensure_ffmpeg()
            if progress_cb:
                progress_cb("正在获取视频信息...")
            result.video_info = self.step1_get_video_info(video_path)
            audio_path = self.step2_extract_audio(video_path, progress_cb)
            whisper_result = self.step3_transcribe(audio_path, progress_cb)
            result.transcript_text = whisper_result.get("text", "")
            result.transcript_segments = [{"start": round(seg["start"], 1), "end": round(seg["end"], 1), "text": seg["text"].strip()} for seg in whisper_result.get("segments", [])]
            result.scenes = self.step4_detect_scenes(video_path, progress_cb)
            llm_result = self.step5_llm_analyze(result.transcript_text, result.scenes, result.video_info, progress_cb)
            result.hooks_analysis = llm_result.get("hooks_analysis", "")
            result.script_structure = llm_result.get("script_structure", "")
            result.character_map = llm_result.get("character_map", "")
            result.rewrite_suggestions = llm_result.get("rewrite_suggestions", "")
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
        report = f"""# 短剧拆解报告

## 视频信息
- 文件: {os.path.basename(vi.path)}
- 时长: {vi.duration:.1f}秒
- 分辨率: {vi.width}×{vi.height}
- 文件大小: {vi.size_mb:.1f}MB

## 转写文本

### 完整文本
{result.transcript_text}

### 带时间戳
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
