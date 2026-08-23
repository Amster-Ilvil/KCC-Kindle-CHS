# -*- coding: utf-8 -*-
"""Manual, locked GitHub updater for the packaged Kindle Chinese macOS app.

The customization repository is a build recipe, not the source tree embedded in
an installed KCC app. Therefore we check the locked Git ``main`` branch like
Folirina, but install only a CI-produced ``.app.zip`` GitHub Release. Raw source
commits are never copied into the running app bundle.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Callable
from urllib.parse import quote, urlparse
import urllib.request
import zipfile

DEFAULT_REPOSITORY = "Amster-Ilvil/KCC-Kindle-CHS"
DEFAULT_BRANCH = "main"
API_BASE = "https://api.github.com/repos"
EXPECTED_BUNDLE_ID = "org.kcc.kindlecn"
MAX_DOWNLOAD_BYTES = 2 * 1024**3
MAX_ARCHIVE_FILES = 120_000
MAX_ARCHIVE_BYTES = 5 * 1024**3
ProgressCallback = Callable[[str], None]


def _emit(progress: ProgressCallback | None, message: str) -> None:
    if progress is not None:
        progress(str(message))


def normalize_repository(value: str | None = None) -> str:
    raw = str(value or DEFAULT_REPOSITORY).strip().rstrip("/").removesuffix(".git")
    if raw.startswith("git@github.com:"):
        raw = raw.split(":", 1)[1]
    elif "://" in raw:
        parsed = urlparse(raw)
        if parsed.hostname not in {"github.com", "www.github.com"}:
            raise ValueError("Git 更新仓库已锁定为官方 GitHub 仓库")
        raw = parsed.path.strip("/").removesuffix(".git")
    if raw != DEFAULT_REPOSITORY:
        raise ValueError(f"Git 更新仓库已锁定：{DEFAULT_REPOSITORY}")
    return DEFAULT_REPOSITORY


def normalize_branch(value: str | None = None) -> str:
    raw = str(value or DEFAULT_BRANCH).strip()
    if raw != DEFAULT_BRANCH:
        raise ValueError(f"Git 更新分支已锁定：{DEFAULT_BRANCH}")
    return DEFAULT_BRANCH


def _version_tuple(value: str) -> tuple[int, int, int]:
    raw = str(value or "0").strip().lstrip("vV").split("-", 1)[0]
    parts: list[int] = []
    for token in raw.split("."):
        match = re.search(r"\d+", token)
        parts.append(int(match.group(0)) if match else 0)
    return tuple((parts + [0, 0, 0])[:3])  # type: ignore[return-value]


def _headers() -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "User-Agent": "KCC-Kindle-CN-Git-Updater",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _request_json(url: str, timeout: float = 12.0) -> Any:
    request = urllib.request.Request(url, headers=_headers())
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def _request_text(url: str, timeout: float = 20.0) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "KCC-Kindle-CN-Git-Updater"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(4 * 1024 * 1024).decode("utf-8", errors="replace")


def discover_app_bundle() -> Path | None:
    override = str(os.environ.get("KCC_CN_APP_BUNDLE", "") or "").strip()
    candidates = [Path(override).expanduser()] if override else []
    candidates.extend([Path(sys.executable), Path(sys.argv[0] if sys.argv else "")])
    seen: set[Path] = set()
    for candidate in candidates:
        try:
            path = candidate.resolve()
        except OSError:
            path = candidate.absolute()
        for probe in (path, *path.parents):
            if probe in seen:
                continue
            seen.add(probe)
            if probe.suffix.lower() == ".app" and (probe / "Contents" / "Info.plist").is_file():
                return probe
    return None


def _read_plist(app: Path) -> dict[str, Any]:
    with (app / "Contents" / "Info.plist").open("rb") as stream:
        data = plistlib.load(stream)
    if not isinstance(data, dict):
        raise RuntimeError("Info.plist 内容异常")
    return data


def read_app_version(app: Path) -> str:
    return str(_read_plist(app).get("CFBundleShortVersionString") or "0.0.0").strip() or "0.0.0"


def _asset_score(asset: dict[str, Any]) -> tuple[int, int, str]:
    name = str(asset.get("name") or "")
    lower = name.lower()
    if not lower.endswith(".app.zip"):
        return (-1, -1, lower)
    score = 0
    if "applesilicon" in lower or "apple-silicon" in lower or "arm64" in lower:
        score += 10
    if "kindle" in lower:
        score += 4
    if "漫画" in name or "转换器" in name:
        score += 2
    return (score, -len(name), lower)


def _select_app_asset(assets: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = [asset for asset in assets if _asset_score(asset)[0] >= 0]
    return max(candidates, key=_asset_score) if candidates else None


def _select_checksum_asset(assets: list[dict[str, Any]]) -> dict[str, Any] | None:
    for asset in assets:
        name = str(asset.get("name") or "").lower()
        if name.startswith("sha256sums") and name.endswith(".txt"):
            return asset
    return None


def _checksum_for_asset(text: str, asset_name: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.replace(" *", "  ").split()
        if len(parts) >= 2 and parts[-1].lstrip("*") == asset_name:
            digest = parts[0].lower()
            if re.fullmatch(r"[0-9a-f]{64}", digest):
                return digest
    return ""


@dataclass(frozen=True, slots=True)
class GitUpdateInfo:
    repository: str
    branch: str
    app_bundle: Path | None
    local_version: str
    release_version: str
    release_tag: str
    release_name: str
    release_notes: str
    asset_name: str
    asset_url: str
    expected_sha256: str
    main_commit: str
    main_message: str
    main_date: str
    release_commit: str
    available: bool
    source_ahead: bool
    installable: bool
    reason: str

    @property
    def main_short(self) -> str:
        return self.main_commit[:10] if self.main_commit else "未知"

    @property
    def release_short(self) -> str:
        return self.release_commit[:10] if self.release_commit else "未知"


def check_git_update(timeout: float = 12.0) -> GitUpdateInfo:
    repository = normalize_repository()
    branch = normalize_branch()
    main = _request_json(f"{API_BASE}/{repository}/commits/{quote(branch, safe='')}", timeout=timeout)
    if not isinstance(main, dict) or not main.get("sha"):
        raise RuntimeError("GitHub 没有返回 main 分支 commit")
    main_commit = str(main.get("sha") or "")
    commit_meta = main.get("commit") if isinstance(main.get("commit"), dict) else {}
    main_message = str((commit_meta or {}).get("message") or "").splitlines()[0].strip()
    author = (commit_meta or {}).get("author") if isinstance((commit_meta or {}).get("author"), dict) else {}
    main_date = str((author or {}).get("date") or "").strip()

    release = _request_json(f"{API_BASE}/{repository}/releases/latest", timeout=timeout)
    if not isinstance(release, dict):
        raise RuntimeError("GitHub Release 响应异常")
    release_tag = str(release.get("tag_name") or "").strip()
    release_version = release_tag.lstrip("vV")
    assets = [item for item in (release.get("assets") or []) if isinstance(item, dict)]
    app_asset = _select_app_asset(assets)
    asset_name = str((app_asset or {}).get("name") or "")
    asset_url = str((app_asset or {}).get("browser_download_url") or "")
    if asset_url and urlparse(asset_url).hostname not in {"github.com", "www.github.com"}:
        raise RuntimeError("Release 下载地址不是 GitHub，已拒绝更新")

    release_commit = ""
    if release_tag:
        try:
            tagged = _request_json(f"{API_BASE}/{repository}/commits/{quote(release_tag, safe='')}", timeout=timeout)
            if isinstance(tagged, dict):
                release_commit = str(tagged.get("sha") or "")
        except Exception:
            release_commit = ""

    expected_sha256 = ""
    checksum_asset = _select_checksum_asset(assets)
    checksum_url = str((checksum_asset or {}).get("browser_download_url") or "")
    if checksum_url and asset_name:
        try:
            expected_sha256 = _checksum_for_asset(_request_text(checksum_url), asset_name)
        except Exception:
            expected_sha256 = ""

    app = discover_app_bundle()
    local_version = read_app_version(app) if app is not None else "0.0.0"
    local_v = _version_tuple(local_version)
    release_v = _version_tuple(release_version)
    source_ahead = bool(main_commit and release_commit and main_commit != release_commit)

    if app is None:
        available = False
        reason = "已连接 Git 仓库；当前不是已安装的 macOS .app，仅支持检查，不能自动覆盖源码目录"
    elif not release_tag or not app_asset or not asset_url:
        available = False
        reason = "Git main 可访问，但最新 Release 没有可安装的 .app.zip"
    elif release_v > local_v:
        available = True
        reason = f"发现可安装更新 v{release_version}"
    elif release_v < local_v:
        available = False
        reason = f"本地 v{local_version} 比 Release v{release_version} 更新；禁止自动降级"
    elif source_ahead:
        available = False
        reason = "Git main 已有更新提交，但尚未发布新的可安装 App；等待 CI Release 后再更新"
    else:
        available = False
        reason = "当前 App 已是最新 Release"

    installable = bool(available and app is not None and asset_url)
    return GitUpdateInfo(
        repository=repository, branch=branch, app_bundle=app,
        local_version=local_version, release_version=release_version,
        release_tag=release_tag, release_name=str(release.get("name") or ""),
        release_notes=str(release.get("body") or ""), asset_name=asset_name,
        asset_url=asset_url, expected_sha256=expected_sha256,
        main_commit=main_commit, main_message=main_message, main_date=main_date,
        release_commit=release_commit, available=available, source_ahead=source_ahead,
        installable=installable, reason=reason,
    )


def _download(url: str, destination: Path, progress: ProgressCallback | None = None, timeout: float = 90.0) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "KCC-Kindle-CN-Git-Updater"})
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    total = 0
    with urllib.request.urlopen(request, timeout=timeout) as response, destination.open("wb") as out:
        try:
            declared = int(response.headers.get("Content-Length", "0") or 0)
        except (TypeError, ValueError):
            declared = 0
        if declared > MAX_DOWNLOAD_BYTES:
            raise RuntimeError("更新包下载体积异常，已停止安装")
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_DOWNLOAD_BYTES:
                raise RuntimeError("更新包下载体积异常，已停止安装")
            digest.update(chunk)
            out.write(chunk)
            if declared:
                _emit(progress, f"正在下载更新包… {min(100, int(total * 100 / declared))}%")
    return digest.hexdigest()


def _validate_archive(archive_path: Path) -> None:
    with zipfile.ZipFile(archive_path) as archive:
        infos = archive.infolist()
        if len(infos) > MAX_ARCHIVE_FILES:
            raise RuntimeError("更新包文件数量异常，已停止安装")
        total = sum(max(0, int(info.file_size)) for info in infos)
        if total > MAX_ARCHIVE_BYTES:
            raise RuntimeError("更新包解压体积异常，已停止安装")
        for info in infos:
            name = str(info.filename).replace("\\", "/")
            candidate = Path(name)
            if candidate.is_absolute() or any(part == ".." for part in candidate.parts):
                raise RuntimeError(f"更新包包含不安全路径：{info.filename}")


def _extract_archive(archive_path: Path, destination: Path) -> None:
    _validate_archive(archive_path)
    destination.mkdir(parents=True, exist_ok=True)
    ditto = Path("/usr/bin/ditto")
    if sys.platform == "darwin" and ditto.is_file():
        proc = subprocess.run([str(ditto), "-x", "-k", str(archive_path), str(destination)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)
        if proc.returncode != 0:
            raise RuntimeError("系统解压更新包失败：" + str(proc.stdout or "")[-3000:])
        return
    with zipfile.ZipFile(archive_path) as archive:
        archive.extractall(destination)


def _find_app(root: Path) -> Path:
    apps = sorted((path for path in root.rglob("*.app") if path.is_dir()), key=lambda p: (len(p.relative_to(root).parts), p.as_posix().casefold()))
    if not apps:
        raise RuntimeError("更新包中没有找到 .app")
    return apps[0]


def _validate_app(app: Path, expected_version: str | None = None) -> str:
    data = _read_plist(app)
    if str(data.get("CFBundleIdentifier") or "") != EXPECTED_BUNDLE_ID:
        raise RuntimeError("更新包 Bundle Identifier 不匹配，已停止安装")
    version = str(data.get("CFBundleShortVersionString") or "0.0.0")
    if expected_version and _version_tuple(version) != _version_tuple(expected_version):
        raise RuntimeError(f"更新包版本 v{version} 与 Release v{expected_version} 不一致")
    executable = str(data.get("CFBundleExecutable") or "").strip()
    if executable and not (app / "Contents" / "MacOS" / executable).is_file():
        raise RuntimeError("更新包主程序缺失")
    codesign = Path("/usr/bin/codesign")
    if sys.platform == "darwin" and codesign.is_file():
        verify = subprocess.run([str(codesign), "--verify", "--deep", "--strict", "--verbose=2", str(app)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)
        if verify.returncode != 0:
            raise RuntimeError("更新包代码签名结构校验失败：" + str(verify.stdout or "")[-3000:])
    return version


def install_git_update(info: GitUpdateInfo, progress: ProgressCallback | None = None) -> Path:
    """Install a CI-built release transactionally; keep one rollback app bundle."""
    normalize_repository(info.repository)
    normalize_branch(info.branch)
    if not info.installable or not info.available:
        raise RuntimeError(info.reason or "当前没有可安装更新")
    target = info.app_bundle.resolve() if info.app_bundle is not None else None
    current = discover_app_bundle()
    if target is None or current is None or current.resolve() != target:
        raise RuntimeError("运行中的 App 路径发生变化，已停止更新")
    if _version_tuple(info.release_version) <= _version_tuple(read_app_version(target)):
        raise RuntimeError("Release 版本不高于当前 App，禁止重复安装或降级")

    parent = target.parent
    staged = parent / (target.name + ".update-new")
    backup = parent / (target.name + ".previous")
    with tempfile.TemporaryDirectory(prefix="kcc-kindle-cn-update-") as temp_name:
        temp = Path(temp_name)
        archive = temp / "release.app.zip"
        _emit(progress, f"准备从 {info.repository} 下载 {info.asset_name}…")
        actual_sha = _download(info.asset_url, archive, progress=progress)
        if info.expected_sha256 and actual_sha.lower() != info.expected_sha256.lower():
            raise RuntimeError("更新包 SHA-256 与 Release 校验文件不一致，已停止安装")
        _emit(progress, "下载完成，正在校验并解压 App…")
        extracted = temp / "unpacked"
        _extract_archive(archive, extracted)
        incoming = _find_app(extracted)
        _validate_app(incoming, info.release_version)

        if staged.exists() or staged.is_symlink():
            if staged.is_dir() and not staged.is_symlink():
                shutil.rmtree(staged)
            else:
                staged.unlink()
        shutil.copytree(incoming, staged, symlinks=True)
        _validate_app(staged, info.release_version)
        _emit(progress, "新版本完整性校验通过，正在事务替换应用…")

        if backup.exists() or backup.is_symlink():
            if backup.is_dir() and not backup.is_symlink():
                shutil.rmtree(backup)
            else:
                backup.unlink()
        target.rename(backup)
        try:
            staged.rename(target)
            _validate_app(target, info.release_version)
        except Exception:
            if target.exists() or target.is_symlink():
                if target.is_dir() and not target.is_symlink():
                    shutil.rmtree(target, ignore_errors=True)
                else:
                    try:
                        target.unlink()
                    except OSError:
                        pass
            if staged.exists() and staged.is_dir():
                shutil.rmtree(staged, ignore_errors=True)
            backup.rename(target)
            raise
    _emit(progress, f"Git 更新完成：v{info.local_version} → v{info.release_version}；重新启动后生效。")
    return backup


__all__ = ["DEFAULT_REPOSITORY", "DEFAULT_BRANCH", "GitUpdateInfo", "check_git_update", "discover_app_bundle", "install_git_update", "normalize_repository", "normalize_branch"]
