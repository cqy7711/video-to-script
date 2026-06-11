"""视频下载模块 — 支持 抖音/YouTube/B站/快手 等 1000+ 平台"""

import os
import re
import json
import tempfile
from dataclasses import dataclass
from typing import Optional, Callable

import yt_dlp


@dataclass
class DownloadResult:
    success: bool
    video_path: str = ""
    title: str = ""
    platform: str = ""
    duration: float = 0.0
    description: str = ""
    uploader: str = ""
    error: str = ""


# 平台识别规则
PLATFORM_RULES = [
    (r"(douyin\.com|iesdouyin\.com)", "抖音"),
    (r"(youtube\.com|youtu\.be)", "YouTube"),
    (r"(bilibili\.com|b23\.tv)", "B站"),
    (r"(kuaishou\.com|gifshow\.com|chenzhongtech\.com)", "快手"),
    (r"(ixigua\.com)", "西瓜视频"),
    (r"(weibo\.com|weibo\.cn|m\.weibo\.cn)", "微博"),
    (r"(v\.qq\.com)", "腾讯视频"),
    (r"(youku\.com)", "优酷"),
    (r"(tiktok\.com)", "TikTok"),
    (r"(instagram\.com)", "Instagram"),
    (r"(twitter\.com|x\.com)", "X/Twitter"),
    (r"(facebook\.com|fb\.watch)", "Facebook"),
    (r"(vimeo\.com)", "Vimeo"),
    (r"(rednote\.cn|xiaohongshu\.com)", "小红书"),
]


def detect_platform(url: str) -> str:
    """根据 URL 识别视频平台"""
    for pattern, name in PLATFORM_RULES:
        if re.search(pattern, url, re.IGNORECASE):
            return name
    return "其他平台"


def download_video(
    url: str,
    output_dir: str = "",
    progress_cb: Optional[Callable] = None,
    cookie_file: str = "",
) -> DownloadResult:
    """
    从 URL 下载视频，返回下载结果。

    Args:
        url: 视频链接（支持抖音/YouTube/B站/快手等 1000+ 平台）
        output_dir: 输出目录，默认临时目录
        progress_cb: 进度回调函数
        cookie_file: Cookie 文件路径（某些平台需要登录才能下载）

    Returns:
        DownloadResult 包含下载状态和视频信息
    """
    if not url or not url.strip().startswith("http"):
        return DownloadResult(success=False, error="请输入有效的视频链接")

    url = url.strip()
    platform = detect_platform(url)

    if not output_dir:
        output_dir = tempfile.mkdtemp(prefix="v2s_dl_")

    output_template = os.path.join(output_dir, "%(title).50s.%(ext)s")

    # yt-dlp 配置
    ydl_opts = {
        "format": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
        "outtmpl": output_template,
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        # 进度钩子
        "progress_hooks": [_make_progress_hook(progress_cb, platform)],
        # 避免被反爬
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "referer": url,
        # 中文标题兼容
        "restrictfilenames": False,
        # 自动修复扩展名
        "fixup": "detect_or_warn",
    }

    # Cookie 文件（用于需要登录的平台）
    if cookie_file and os.path.exists(cookie_file):
        ydl_opts["cookiefile"] = cookie_file

    # 抖音特殊处理：抖音短链需要先重定向
    if "抖音" in platform:
        ydl_opts["extractor_args"] = {"douyin": {"no_playlist": True}}

    # B站特殊处理：优先获取最高画质
    if "B站" in platform:
        ydl_opts["extractor_args"] = {"bilibili": {"no_playlist": True}}

    try:
        if progress_cb:
            progress_cb(f"正在从{platform}获取视频信息...")

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

            if info is None:
                return DownloadResult(success=False, error="无法获取视频信息", platform=platform)

            # 获取下载后的文件路径
            downloaded_path = ydl.prepare_filename(info)
            # yt-dlp 可能改了扩展名（merge 后是 .mp4）
            if not os.path.exists(downloaded_path):
                base = os.path.splitext(downloaded_path)[0]
                for ext in [".mp4", ".mkv", ".webm", ".mov"]:
                    candidate = base + ext
                    if os.path.exists(candidate):
                        downloaded_path = candidate
                        break

            if not os.path.exists(downloaded_path):
                return DownloadResult(
                    success=False,
                    error=f"下载完成但找不到文件: {downloaded_path}",
                    platform=platform
                )

            duration = info.get("duration", 0) or 0
            title = info.get("title", "未知标题")
            description = info.get("description", "") or ""
            uploader = info.get("uploader", "") or info.get("channel", "") or ""

            if progress_cb:
                progress_cb(f"✅ {platform}视频下载完成: {title}")

            return DownloadResult(
                success=True,
                video_path=downloaded_path,
                title=title,
                platform=platform,
                duration=duration,
                description=description,
                uploader=uploader,
            )

    except yt_dlp.utils.DownloadError as e:
        error_msg = str(e)
        # 友好化常见错误
        if "Sign in" in error_msg or "login" in error_msg.lower():
            error_msg = f"{platform}需要登录才能下载，请在设置中配置 Cookie 文件"
        elif "Private video" in error_msg or "private" in error_msg.lower():
            error_msg = "这是私密视频，无法下载"
        elif "Video unavailable" in error_msg:
            error_msg = "视频不可用或已被删除"
        elif "HTTP Error 403" in error_msg:
            error_msg = f"{platform}访问被拒绝，可能需要配置 Cookie"
        elif "Unsupported URL" in error_msg:
            error_msg = f"不支持该链接格式，请检查链接是否正确"

        if progress_cb:
            progress_cb(f"❌ 下载失败: {error_msg}")

        return DownloadResult(success=False, error=error_msg, platform=platform)

    except Exception as e:
        error_msg = f"下载失败: {str(e)}"
        if progress_cb:
            progress_cb(f"❌ {error_msg}")
        return DownloadResult(success=False, error=error_msg, platform=platform)


def _make_progress_hook(progress_cb, platform):
    """创建 yt-dlp 进度钩子"""
    last_percent = [-1]

    def hook(d):
        if d["status"] == "downloading":
            try:
                percent = int(float(d.get("_percent_str", "0%").strip().replace("%", "")))
                if percent != last_percent[0] and percent % 10 == 0:
                    last_percent[0] = percent
                    if progress_cb:
                        progress_cb(f"正在从{platform}下载视频... {percent}%")
            except (ValueError, TypeError):
                pass
        elif d["status"] == "finished":
            if progress_cb:
                progress_cb(f"下载完成，正在合并音视频...")

    return hook


def get_video_info_only(url: str) -> DownloadResult:
    """仅获取视频信息，不下载。用于预览链接信息。"""
    if not url or not url.strip().startswith("http"):
        return DownloadResult(success=False, error="请输入有效的视频链接")

    url = url.strip()
    platform = detect_platform(url)

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info is None:
                return DownloadResult(success=False, error="无法获取视频信息", platform=platform)

            return DownloadResult(
                success=True,
                title=info.get("title", "未知标题"),
                platform=platform,
                duration=info.get("duration", 0) or 0,
                description=(info.get("description", "") or "")[:200],
                uploader=info.get("uploader", "") or info.get("channel", "") or "",
            )
    except Exception as e:
        return DownloadResult(success=False, error=str(e), platform=platform)


# 支持的平台列表（用于 UI 展示）
SUPPORTED_PLATFORMS = [name for _, name in PLATFORM_RULES] + ["其他平台"]
