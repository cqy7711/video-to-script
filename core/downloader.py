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
        # 重试机制：网络不稳定时自动重试
        "retries": 10,
        "fragment_retries": 10,
        "file_access_retries": 3,
        "extractor_retries": 3,
        # 断点续传：支持从断开处继续下载
        "continue_dl": True,
        # 超时设置
        "socket_timeout": 30,
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
        elif "Downloaded" in error_msg and "expected" in error_msg:
            # 文件大小不匹配（网络中断导致），提示重试
            error_msg = f"⚠️ 下载不完整（网络中断），已自动开启断点续传。请重新点击「开始分析」即可继续下载。"

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


def get_playlist_info(url: str) -> dict:
    """
    检测链接是否为剧集/播放列表，返回分集列表信息。

    Args:
        url: 视频或剧集链接

    Returns:
        dict:
            is_series: bool — 是否为多集系列
            total_episodes: int — 总集数
            series_title: str — 剧集名称
            episodes: list[dict] — 分集信息列表，每项含 {index, title, url, duration}
            error: str — 错误信息（如有）
    """
    url = url.strip()
    if not url or not url.startswith("http"):
        return {"is_series": False, "total_episodes": 0, "series_title": "",
                "episodes": [], "error": "无效的链接"}

    # 先识别平台（用于后续推断系列URL）
    platform = detect_platform(url)

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in",  # 获取播放列表但不下载每个视频的详细信息（更快）
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info is None:
                return {"is_series": False, "total_episodes": 0, "series_title": "",
                        "episodes": [], "error": "无法获取视频信息", "uploader": ""}

            # 检查是否为播放列表/剧集
            entries = info.get("entries") or []
            series_title = info.get("title", "") or ""

            # 单个视频（不是剧集）
            if not entries:
                duration = info.get("duration", 0) or 0
                current_id = info.get("id", "")
                webpage_url = info.get("webpage_url") or info.get("original_url") or url

                # 尝试从单个视频信息中提取系列ID（抖音/B站等平台）
                series_id = (
                    info.get("series") or info.get("series_id") or
                    info.get("mix_id") or info.get("album_id") or ""
                )

                # 如果拿到 series_id，尝试构造系列页面URL并重试
                if series_id and not url.startswith("file"):
                    deduced_series_url = _try_deduce_series_url(info, webpage_url, platform)
                    if deduced_series_url:
                        try:
                            opts2 = dict(ydl_opts)
                            opts2["extract_flat"] = True  # 只拿列表
                            with yt_dlp.YoutubeDL(opts2) as ydl2:
                                info2 = ydl2.extract_info(deduced_series_url, download=False)
                                if info2 and info2.get("entries"):
                                    entries = info2.get("entries") or []
                                    series_title = info2.get("title", "") or info.get("title", "")
                                    # 找到包含当前视频的那一集，排到前面
                                    for i, entry in enumerate(entries):
                                        if entry.get("id") == current_id:
                                            entries = [entry] + [e for j, e in enumerate(entries) if j != i]
                                            break
                        except Exception:
                            pass

                # Fallback：如果还没拿到列表，尝试用上传者ID拼用户主页链接再试一次
                if not entries and platform == "抖音":
                    uploader_id = info.get("uploader_id") or ""
                    if uploader_id:
                        # 抖音：尝试用 video_url 替换为用户主页相关路径
                        fallback_urls = [
                            f"https://www.douyin.com/user/{uploader_id}",
                            # 某些抖音合集页面格式
                            f"https://www.douyin.com/mix/{series_id}" if series_id else "",
                        ]
                        for fu in fallback_urls:
                            if not fu:
                                continue
                            try:
                                opts3 = dict(ydl_opts)
                                opts3["extract_flat"] = True
                                with yt_dlp.YoutubeDL(opts3) as ydl3:
                                    info3 = ydl3.extract_info(fu, download=False)
                                    if info3 and info3.get("entries"):
                                        entries = info3.get("entries") or []
                                        series_title = info3.get("title", "") or info.get("title", "")
                                        break
                            except Exception:
                                pass

                if not entries:
                    uploader_name = (
                        info.get("uploader") or info.get("channel") or
                        info.get("artist") or ""
                    )
                    return {
                        "is_series": False, "total_episodes": 1,
                        "series_title": "", "episodes": [{
                            "index": 1, "title": info.get("title", ""),
                            "url": url, "duration": duration,
                        }], "error": "",
                        "uploader": uploader_name,
                    }

            # 多集：构建分集列表
            episodes = []
            for i, entry in enumerate(entries):
                ep_url = entry.get("url") or entry.get("webpage_url") or ""
                if not ep_url and entry.get("id"):
                    # 尝试用通用方式构造分集URL
                    ep_url = _try_build_episode_url(url, entry.get("id", ""), platform)
                ep_info = {
                    "index": i + 1,
                    "title": entry.get("title", f"第{i+1}集"),
                    "url": ep_url,
                    "duration": entry.get("duration") or 0,
                }
                episodes.append(ep_info)

            return {
                "is_series": True,
                "total_episodes": len(episodes),
                "series_title": series_title,
                "episodes": episodes,
                "error": "",
                "uploader": info.get("uploader") or info.get("channel") or "",
            }

    except Exception as e:
        err_msg = str(e)
        return {
            "is_series": False, "total_episodes": 1,
            "series_title": "", "episodes": [{
                "index": 1, "title": "", "url": url, "duration": 0,
            }], "error": f"检测失败({err_msg})，将按单集处理",
            "uploader": "",
        }


def _try_deduce_series_url(info: dict, url: str, platform: str) -> str:
    """尝试从单个视频信息中推断系列页面URL"""
    # 抖音：从视频页面提取用户主页，再拼出系列页
    if platform == "抖音":
        user_id = (
            info.get("uploader_id") or info.get("creator_id") or ""
        )
        if user_id:
            # 抖音用户主页（系列通常在用户主页的「作品」或「合集」tab）
            return f"https://www.douyin.com/user/{user_id}"
    # YouTube：从 video info 里取 playlist_id
    if platform == "YouTube":
        playlist_id = info.get("playlist_id") or ""
        if playlist_id:
            return f"https://www.youtube.com/playlist?list={playlist_id}"
    return ""


def _try_build_episode_url(base_url: str, video_id: str, platform: str) -> str:
    """尝试根据平台和video_id构造分集直链"""
    if platform == "抖音" and video_id:
        return f"https://www.douyin.com/video/{video_id}"
    if platform == "YouTube" and video_id:
        return f"https://www.youtube.com/watch?v={video_id}"
    if platform == "B站" and video_id:
        return f"https://www.bilibili.com/video/{video_id}"
    return base_url  # 降级用原链接


# 支持的平台列表（用于 UI 展示）
SUPPORTED_PLATFORMS = [name for _, name in PLATFORM_RULES] + ["其他平台"]
