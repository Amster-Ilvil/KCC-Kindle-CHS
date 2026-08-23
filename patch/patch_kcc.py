#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Patch official KCC v11.0.1 into the Kindle-only Simplified Chinese edition."""
from __future__ import annotations
import re, shutil, sys
from pathlib import Path

EXPECTED_COMMIT = "bd0328a12fe40ab62285d3a8ae3e501f6e41c78b"

def fail(msg): raise SystemExit(f"[错误] {msg}")
def one(text, old, new, label):
    n=text.count(old)
    if n != 1: fail(f"补丁定位失败：{label}（期望 1 处，实际 {n} 处）")
    return text.replace(old,new,1)

def patch_gui(path: Path):
    text=path.read_text(encoding="utf-8")
    if "apply_kindle_cn_ui" in text:
        print("[跳过] KCC_gui.py 已修改"); return
    shutil.copy2(path, path.with_suffix(path.suffix+".official.bak"))
    text=one(
        text,
        "from . import KCC_ui_editor\n",
        "from . import KCC_ui_editor\n"
        "from .kindle_cn_ui import apply_kindle_cn_ui, apply_meta_editor_cn, translate_runtime_message\n"
        "from .kindle_cn_enhancements import install_enhancements, enhance_meta_editor, translate_more\n"
        "from .kindle_cn_update_ui import install_git_update_ui\n",
        "导入中文 UI",
    )

    # Disable upstream update/announcement/promotion networking entirely.
    p=re.compile(r"(class VersionThread\(QThread\):.*?\n    def run\(self\):\n)(.*?)(\n    def setAnswer\(self, dialoganswer\):)",re.S)
    m=p.search(text)
    if not m: fail("无法定位 VersionThread.run")
    text=text[:m.start()]+m.group(1)+"        # Kindle 中文版：启动时不检查更新，不请求公告/推广。\n        return\n"+m.group(3)+text[m.end():]

    text=one(
        text,
        "        self.setupUi(MW)\n        self.editor = KCCGUI_MetaEditor()\n",
        "        self.setupUi(MW)\n        apply_kindle_cn_ui(self, MW)\n        install_enhancements(self, MW)\n        self.editor = KCCGUI_MetaEditor()\n        install_git_update_ui(self, MW)\n",
        "主界面入口",
    )
    text=one(text,"        self.settings = QSettings('ciromattia', 'kcc10')\n","        self.settings = QSettings('KCC-Kindle-CN', 'kcc11-kindle-only')\n","独立设置")

    # Kindle-focused output list. Indexes 0..3 remain compatible with upstream
    # profile defaults (MOBI, EPUB, CBZ, PDF).
    a=text.find("        self.formats = {"); b=text.find("        self.profiles = {",a)
    if a<0 or b<0: fail("无法定位输出格式块")
    formats='''        self.formats = {  # Kindle-only; keep upstream indexes 0..3 compatible
            "MOBI/AZW3": {'icon': 'MOBI', 'format': 'MOBI'},
            "EPUB（Send to Kindle）": {'icon': 'EPUB', 'format': 'EPUB'},
            "CBZ（旧 Kindle / KOReader）": {'icon': 'CBZ', 'format': 'CBZ'},
            "PDF（Kindle Scribe）": {'icon': 'EPUB', 'format': 'PDF'},
            "KFX（Send to Kindle）": {'icon': 'KFX', 'format': 'KFX'},
        }\n\n'''
    text=text[:a]+formats+text[b:]

    # Replace the complete upstream device-profile block, rather than merely
    # hiding Kobo/reMarkable at runtime. This makes the product genuinely
    # Kindle-only while preserving all Kindle profile labels used by image.py.
    a=text.find("        self.profiles = {")
    b=text.find("        link_dict = {", a)
    if a<0 or b<0: fail("无法定位设备配置块")
    kindle_profiles='''        self.profiles = {
            "Kindle Oasis 9/10": {'PVOptions': True, 'ForceExpert': False, 'DefaultFormat': 0,
                                 'DefaultUpscale': True, 'ForceColor': False, 'Label': 'KO'},
            "Kindle 8/10": {'PVOptions': True, 'ForceExpert': False, 'DefaultFormat': 0,
                       'DefaultUpscale': False, 'ForceColor': False, 'Label': 'K810'},
            "Kindle Oasis 8": {'PVOptions': True, 'ForceExpert': False, 'DefaultFormat': 0,
                             'DefaultUpscale': True, 'ForceColor': False, 'Label': 'KPW34'},
            "Kindle Voyage": {'PVOptions': True, 'ForceExpert': False, 'DefaultFormat': 0,
                              'DefaultUpscale': True, 'ForceColor': False, 'Label': 'KV'},
            "Kindle 1860x1920": {'PVOptions': True, 'ForceExpert': False, 'DefaultFormat': 0,
                                 'DefaultUpscale': False, 'ForceColor': False, 'Label': 'KS1860'},
            "Kindle 1920x1920": {'PVOptions': True, 'ForceExpert': False, 'DefaultFormat': 0,
                                 'DefaultUpscale': False, 'ForceColor': False, 'Label': 'KS1920'},
            "Kindle 1240x1860": {'PVOptions': True, 'ForceExpert': False, 'DefaultFormat': 0,
                                 'DefaultUpscale': False, 'ForceColor': False, 'Label': 'KS1240'},
            "Kindle 1324x1986": {'PVOptions': True, 'ForceExpert': False, 'DefaultFormat': 0,
                                 'DefaultUpscale': False, 'ForceColor': False, 'Label': 'KS1324'},
            "Kindle Scribe 1/2": {'PVOptions': True, 'ForceExpert': False, 'DefaultFormat': 0,
                                  'DefaultUpscale': False, 'ForceColor': False, 'Label': 'KS'},
            "Kindle Scribe 3": {'PVOptions': True, 'ForceExpert': False, 'DefaultFormat': 3,
                                'DefaultUpscale': False, 'ForceColor': False, 'Label': 'KS3'},
            "Kindle Scribe Colorsoft": {'PVOptions': True, 'ForceExpert': False, 'DefaultFormat': 3,
                                         'DefaultUpscale': False, 'ForceColor': True, 'Label': 'KSCS'},
            "Kindle 11": {'PVOptions': True, 'ForceExpert': False, 'DefaultFormat': 0,
                          'DefaultUpscale': True, 'ForceColor': False, 'Label': 'K11'},
            "Kindle Paperwhite 11": {'PVOptions': True, 'ForceExpert': False, 'DefaultFormat': 0,
                                     'DefaultUpscale': True, 'ForceColor': False, 'Label': 'KPW5'},
            "Kindle Paperwhite 12": {'PVOptions': True, 'ForceExpert': False, 'DefaultFormat': 0,
                                     'DefaultUpscale': True, 'ForceColor': False, 'Label': 'KPW6'},
            "Kindle Colorsoft": {'PVOptions': True, 'ForceExpert': False, 'DefaultFormat': 0,
                                 'DefaultUpscale': True, 'ForceColor': True, 'Label': 'KCS'},
            "Kindle Paperwhite 7/10": {'PVOptions': True, 'ForceExpert': False, 'DefaultFormat': 0,
                                       'DefaultUpscale': True, 'ForceColor': False, 'Label': 'KPW34'},
            "Kindle Paperwhite 5/6": {'PVOptions': True, 'ForceExpert': False, 'DefaultFormat': 0,
                                      'DefaultUpscale': False, 'ForceColor': False, 'Label': 'KPW'},
            "Kindle 4/5/7": {'PVOptions': True, 'ForceExpert': False, 'DefaultFormat': 0,
                             'DefaultUpscale': False, 'ForceColor': False, 'Label': 'K57'},
            "Kindle DX": {'PVOptions': False, 'ForceExpert': False, 'DefaultFormat': 2,
                          'DefaultUpscale': False, 'ForceColor': False, 'Label': 'KDX'},
            "Kindle 1": {'PVOptions': False, 'ForceExpert': False, 'DefaultFormat': 0,
                         'DefaultUpscale': False, 'ForceColor': False, 'Label': 'K1'},
            "Kindle 2": {'PVOptions': False, 'ForceExpert': False, 'DefaultFormat': 0,
                         'DefaultUpscale': False, 'ForceColor': False, 'Label': 'K2'},
            "Kindle Keyboard": {'PVOptions': False, 'ForceExpert': False, 'DefaultFormat': 0,
                                'DefaultUpscale': False, 'ForceColor': False, 'Label': 'K34'},
            "Kindle Touch": {'PVOptions': False, 'ForceExpert': False, 'DefaultFormat': 0,
                             'DefaultUpscale': False, 'ForceColor': False, 'Label': 'K34'},
        }

        profilesGUI = [
            "Kindle Scribe Colorsoft", "Kindle Scribe 3", "Kindle Colorsoft",
            "Kindle Paperwhite 12", "Kindle Scribe 1/2", "Kindle Paperwhite 11",
            "Kindle 11", "Kindle Oasis 9/10", "Separator",
            "Kindle 1324x1986", "Kindle 1920x1920", "Kindle 1860x1920", "Kindle 1240x1860",
            "Kindle 8/10", "Kindle Oasis 8", "Kindle Paperwhite 7/10", "Kindle Voyage",
            "Kindle Paperwhite 5/6", "Kindle 4/5/7", "Kindle Touch", "Kindle Keyboard",
            "Kindle DX", "Kindle 2", "Kindle 1",
        ]

'''
    text=text[:a]+kindle_profiles+text[b:]

    # Remove status-bar external links and all promotion entry points.
    a=text.find("        link_dict = {"); b=text.find("        self.tar = TAR in available_archive_tools()",a)
    if a<0 or b<0: fail("无法定位推广块")
    clean='''        statusBarLabel = QLabel("Kindle 专用 · 简体中文 · 无广告/推广")
        statusBarLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        GUI.statusBar.addPermanentWidget(statusBarLabel, 1)
        self.addMessage('<b>提示：</b>可拖入漫画文件、压缩包、PDF 或图片文件夹。', 'info')
        self.addMessage('<b>提示：</b>高级选项默认收起，常用 Kindle 参数已集中显示。', 'info')

'''
    text=text[:a]+clean+text[b:]
    text=text.replace("        GUI.kofiButton.clicked.connect(self.openKofi)\n","")
    text=text.replace("        GUI.humbleButton.clicked.connect(self.openHumble)\n","")
    text=one(text,"        self.versionCheck.start()\n","        # Kindle 中文版：不启动联网检查线程。\n","禁用联网线程")
    text=one(text,'        MW.setWindowTitle("Kindle Comic Converter " + __version__)\n','        MW.setWindowTitle("Kindle 漫画转换器 " + __version__ + " 中文版")\n',"窗口标题")

    # Translate the common runtime surfaces while keeping all internal keys,
    # command-line switches and metadata field names unchanged.
    text=one(
        text,
        "    def addMessage(self, message, icon, replace=False):\n        if icon != '':\n",
        "    def addMessage(self, message, icon, replace=False):\n        message = translate_runtime_message(message)\n        message = translate_more(message)\n        if icon != '':\n",
        "消息翻译",
    )
    text=one(
        text,
        "    def showDialog(self, message, kind):\n        if kind == 'error':\n            QMessageBox.critical(MW, 'KCC - Error', message, QMessageBox.StandardButton.Ok)\n",
        "    def showDialog(self, message, kind):\n        message = translate_runtime_message(message)\n        message = translate_more(message)\n        if kind == 'error':\n            QMessageBox.critical(MW, 'KCC - 错误', message, QMessageBox.StandardButton.Ok)\n",
        "对话框翻译",
    )
    text=text.replace("QMessageBox.question(MW, 'KCC - Question', message,","QMessageBox.question(MW, 'KCC - 确认', message,")
    text=text.replace("GUI.croppingPowerLabel.setText('Cropping Power: ' + str(value))","GUI.croppingPowerLabel.setText('裁边强度：' + str(value))")
    text=text.replace("GUI.gammaLabel.setText('Gamma: Auto')","GUI.gammaLabel.setText('Gamma：自动')")
    text=text.replace("GUI.gammaLabel.setText('Gamma: ' + str(value))","GUI.gammaLabel.setText('Gamma：' + str(value))")

    hook="        self.setupUi(self.ui)\n        self.ui.setWindowFlags"
    if hook in text:
        text=text.replace(
            hook,
            "        self.setupUi(self.ui)\n        apply_meta_editor_cn(self, self.ui)\n        enhance_meta_editor(self, self.ui)\n        self.ui.setWindowFlags",
            1,
        )
    else:
        fail("无法定位元数据编辑器 setupUi")

    path.write_text(text,encoding="utf-8")
    print("[完成] KCC_gui.py")

def patch_core(path: Path):
    text=path.read_text(encoding="utf-8")
    if "capture_original_epub_toc" in text:
        print("[跳过] comic2ebook.py EPUB 目录保留已修改"); return
    shutil.copy2(path, path.with_suffix(path.suffix+".official.bak"))
    text=one(
        text,
        "from . import __version__\n",
        "from . import __version__\n"
        "from .kindle_cn_epub_toc import capture_original_epub_toc, rewrite_preserved_toc\n",
        "导入 EPUB 目录保留模块",
    )
    text=one(
        text,
        "                    opf = ET.parse(opf_path)\n                    spine = []\n",
        "                    opf = ET.parse(opf_path)\n"
        "                    try:\n"
        "                        options.original_epub_toc = capture_original_epub_toc(path, opf_path)\n"
        "                    except Exception as exc:\n"
        "                        options.original_epub_toc = None\n"
        "                        print(f'WARNING: Failed to capture original EPUB TOC; KCC fallback will be used. {exc}')\n"
        "                    spine = []\n",
        "捕获原 EPUB 目录",
    )
    text=one(
        text,
        "    buildNCX(path, options.title, chapterlist, chapternames)\n"
        "    buildNAV(path, options.title, chapterlist, chapternames)\n"
        "    buildOPF(path, options.title, filelist, originalpath, cover)\n",
        "    buildNCX(path, options.title, chapterlist, chapternames)\n"
        "    buildNAV(path, options.title, chapterlist, chapternames)\n"
        "    buildOPF(path, options.title, filelist, originalpath, cover)\n"
        "    original_toc = getattr(options, 'original_epub_toc', None)\n"
        "    if original_toc:\n"
        "        try:\n"
        "            if rewrite_preserved_toc(path, options.title, filelist, original_toc, options.language, options.uuid):\n"
        "                print('Preserved original EPUB TOC hierarchy and remapped chapter targets.')\n"
        "        except Exception as exc:\n"
        "            print(f'WARNING: Failed to remap original EPUB TOC; using KCC-generated TOC. {exc}')\n",
        "重建原 EPUB 目录",
    )
    path.write_text(text, encoding="utf-8")
    print("[完成] comic2ebook.py EPUB 目录保留")

def patch_setup(path: Path):
    text=path.read_text(encoding="utf-8")
    if "Kindle-only Simplified Chinese edition" in text: return
    shutil.copy2(path,path.with_suffix(path.suffix+".official.bak"))
    text=text.replace("description='Comic and Manga converter for e-book readers.',","description='Kindle-only Simplified Chinese edition based on KCC 11.0.1.',")
    text=text.replace("keywords=['kindle', 'kobo', 'comic', 'manga', 'mobi', 'epub', 'cbz'],","keywords=['kindle', 'comic', 'manga', 'mobi', 'azw3', 'epub'],")
    path.write_text(text,encoding="utf-8")

def main():
    if len(sys.argv)!=2: fail("用法：patch_kcc.py /path/to/kcc-v11.0.1")
    root=Path(sys.argv[1]).expanduser().resolve()
    gui=root/"kindlecomicconverter/KCC_gui.py"
    core=root/"kindlecomicconverter/comic2ebook.py"
    setup=root/"setup.py"
    patch_dir=Path(__file__).parent
    sources={
        "kindle_cn_ui.py": patch_dir/"kindle_cn_ui.py",
        "kindle_cn_enhancements.py": patch_dir/"kindle_cn_enhancements.py",
        "kindle_cn_epub_toc.py": patch_dir/"kindle_cn_epub_toc.py",
        "kindle_cn_git_update.py": patch_dir/"kindle_cn_git_update.py",
        "kindle_cn_update_ui.py": patch_dir/"kindle_cn_update_ui.py",
    }
    if not gui.is_file() or not core.is_file() or not setup.is_file(): fail("目标不是完整 KCC v11.0.1 源码目录")
    for name, source in sources.items():
        if not source.is_file(): fail(f"缺少 {name}")
        try:
            compile(source.read_text(encoding="utf-8"), str(source), "exec")
        except SyntaxError as exc:
            fail(f"{name} 语法检查失败：{exc}")
        shutil.copy2(source, root/"kindlecomicconverter"/name)
    patch_gui(gui)
    patch_core(core)
    patch_setup(setup)
    print("[完成] KCC 11.0.1 Kindle 中文专用补丁已应用")
if __name__=="__main__": main()
