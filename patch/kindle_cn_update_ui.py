# -*- coding: utf-8 -*-
"""Manual Git update controls for KCC Kindle Chinese edition."""
from __future__ import annotations

from PySide6.QtCore import QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMessageBox, QPushButton

from .kindle_cn_git_update import (
    DEFAULT_BRANCH,
    DEFAULT_REPOSITORY,
    GitUpdateInfo,
    check_git_update,
    install_git_update,
)


class _GitCheckWorker(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def run(self):
        try:
            self.completed.emit(check_git_update())
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class _GitInstallWorker(QThread):
    progressChanged = Signal(str)
    completed = Signal(str)
    failed = Signal(str)

    def __init__(self, info: GitUpdateInfo, parent=None):
        super().__init__(parent)
        self.info = info

    def run(self):
        try:
            backup = install_git_update(self.info, progress=self.progressChanged.emit)
            self.completed.emit(str(backup))
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


def install_git_update_ui(ui, window):
    """Add Folirina-style manual Git check/update controls without startup I/O."""
    parent = getattr(ui, "deviceHintLabel", None)
    parent = parent.parentWidget() if parent is not None else None
    layout = parent.layout() if parent is not None else None
    if layout is None:
        return

    row = QHBoxLayout()
    row.setSpacing(8)
    check_btn = QPushButton("检查 Git 更新")
    update_btn = QPushButton("从 Git 更新")
    repo_btn = QPushButton("打开 GitHub")
    update_btn.setEnabled(False)
    check_btn.setToolTip(f"手动检查 {DEFAULT_REPOSITORY} · {DEFAULT_BRANCH}；启动时不会自动联网。")
    update_btn.setToolTip("仅安装 GitHub Actions 生成的 .app.zip Release；不会把补丁源码直接覆盖到 App。")
    repo_btn.setToolTip("打开锁定的官方项目仓库。")
    row.addWidget(check_btn)
    row.addWidget(update_btn)
    row.addWidget(repo_btn)
    row.addStretch(1)
    layout.addLayout(row)

    status = QLabel("Git 更新：尚未检查 · 仓库和 main 分支已锁定")
    status.setWordWrap(True)
    status.setStyleSheet("color:#6E7781; font-size:12px;")
    layout.addWidget(status)

    ui.gitUpdateCheckButton = check_btn
    ui.gitUpdateInstallButton = update_btn
    ui.gitUpdateStatusLabel = status
    ui._gitUpdateInfo = None
    ui._gitCheckWorker = None
    ui._gitInstallWorker = None

    def set_idle():
        check_btn.setEnabled(True)
        worker = getattr(ui, "_gitInstallWorker", None)
        if worker is None or not worker.isRunning():
            info = getattr(ui, "_gitUpdateInfo", None)
            update_btn.setEnabled(bool(info and info.installable))

    def check_updates():
        running = getattr(ui, "_gitCheckWorker", None)
        if running is not None and running.isRunning():
            return
        check_btn.setEnabled(False)
        update_btn.setEnabled(False)
        status.setText("Git 更新：正在检查 main commit 与最新 Release…")
        worker = _GitCheckWorker(window)
        ui._gitCheckWorker = worker

        def done(payload):
            if not isinstance(payload, GitUpdateInfo):
                failed("更新检查返回无效结果")
                return
            ui._gitUpdateInfo = payload
            detail = (
                f"{payload.reason} · 本地 v{payload.local_version} · "
                f"Release {payload.release_tag or '无'} · main {payload.main_short}"
            )
            if payload.source_ahead:
                detail += " · main 领先当前 Release"
            status.setText("Git 更新：" + detail)
            update_btn.setEnabled(payload.installable)

        def failed(message):
            ui._gitUpdateInfo = None
            update_btn.setEnabled(False)
            status.setText("Git 更新：检查失败；当前版本未受影响 · " + str(message))

        def finished():
            ui._gitCheckWorker = None
            set_idle()
            worker.deleteLater()

        worker.completed.connect(done)
        worker.failed.connect(failed)
        worker.finished.connect(finished)
        worker.start()

    def install_update():
        running = getattr(ui, "_gitInstallWorker", None)
        if running is not None and running.isRunning():
            return
        if bool(getattr(ui, "conversionAlive", False)):
            QMessageBox.information(window, "任务进行中", "请先等待当前漫画转换任务结束，再更新程序。")
            return
        info = getattr(ui, "_gitUpdateInfo", None)
        if not isinstance(info, GitUpdateInfo):
            QMessageBox.information(window, "请先检查更新", "请先点击“检查 Git 更新”。")
            return
        if not info.installable:
            QMessageBox.information(window, "当前不可安装", info.reason)
            return
        answer = QMessageBox.question(
            window,
            "确认 Git 更新",
            f"将更新 Kindle 漫画转换器：\n\n"
            f"v{info.local_version} → v{info.release_version}\n"
            f"仓库：{info.repository}\n"
            f"Release：{info.release_tag}\n"
            f"文件：{info.asset_name}\n\n"
            "新 App 会先完整下载、校验，再事务替换；旧 App 保留为 .previous。\n"
            "更新完成后需要退出并重新打开程序。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        check_btn.setEnabled(False)
        update_btn.setEnabled(False)
        status.setText("Git 更新：正在准备安装…")
        worker = _GitInstallWorker(info, window)
        ui._gitInstallWorker = worker

        def progress(message):
            status.setText("Git 更新：" + str(message))
            try:
                window.statusBar().showMessage(str(message))
            except Exception:
                pass

        def done(backup):
            status.setText(f"Git 更新：v{info.release_version} 已安装，重新启动后生效。旧版备份：{backup}")
            QMessageBox.information(
                window,
                "Git 更新完成",
                f"v{info.release_version} 已安装。\n\n请退出并重新打开程序后使用新版本。\n旧版本备份：\n{backup}",
            )
            ui._gitUpdateInfo = None

        def failed(message):
            status.setText("Git 更新：安装失败，已保留/回滚当前版本 · " + str(message))
            QMessageBox.critical(window, "Git 更新失败", str(message))

        def finished():
            ui._gitInstallWorker = None
            check_btn.setEnabled(True)
            update_btn.setEnabled(False)
            worker.deleteLater()

        worker.progressChanged.connect(progress)
        worker.completed.connect(done)
        worker.failed.connect(failed)
        worker.finished.connect(finished)
        worker.start()

    def open_repository():
        QDesktopServices.openUrl(QUrl(f"https://github.com/{DEFAULT_REPOSITORY}"))

    check_btn.clicked.connect(check_updates)
    update_btn.clicked.connect(install_update)
    repo_btn.clicked.connect(open_repository)


__all__ = ["install_git_update_ui"]
