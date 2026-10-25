# Windows 便携版

公开便携包从独立 CPython 3.12.15 环境构建，使用 Astral python-build-standalone 的固定构建及其 GitHub SHA-256；没有复制本机 Codex 运行时、个人证书或旧安装目录。具体来源记录在包内 BUILD-INFO.json，Python wheel 固定于 scripts/requirements-portable.lock.txt。

## 包含内容

- GUI、工作进程、Python/Tcl/Tk 和所需运行库，无需用户安装 Python。
- Whisper base / small、Argos 英中模型及 OCR 权重，按 scripts/assets.json 校验。
- 独立构建的 FFmpeg、核验过的 Node.js LTS，以及 Noto Sans CJK SC / JP。
- 应用许可、THIRD-PARTY-NOTICES.md、licenses 目录、组件版本与来源记录。

不附个人配置、加密密钥、视频、真实字幕、作品资料、导出记录、缓存或调试符号。certifi 的公共 CA 根证书属于已核验的运行依赖，不是作者个人信任证书。便携版使用后产生的 settings、cache、exports 和 downloads 应继续保留在本机。

## 许可材料

Python 包装库的许可不能代表它链接的原生库。PyAV wheel 所附 FFmpeg 包括 x264/x265 等组件，按实际组合保留 GPL/LGPL 材料；不单凭 PyAV 的 BSD 元数据判断整个媒体栈。

同一 Release 提供 third-party-sources 附件，包括 FFmpeg、编码与字幕库、GEOS、libiconv 等对应源码、上游补丁、固定构建配方和来源索引。目录中的 archive SHA-256 用于核验保存的文件。部分上游归档不可访问时使用同一版本/提交的上游 Git 镜像重归档，并在索引中区别于原配方归档字节。

模型分别保留 MIT、Apache-2.0、CC-BY-4.0 的许可与署名，字体保留 SIL OFL，Node.js 保留其完整第三方声明。应用自身继续使用 GNU GPL v3，其他组件仍按原许可分发。库文件和源码均可按其许可检查、修改、重建和替换，不增加禁止反向工程的限制。

## 构建流程

1. 新建独立 Python 3.12 环境，核验来源，安装 scripts/requirements-portable.lock.txt 中固定且带哈希的 wheel。不要复用个人运行环境。
2. 显式准备模型，在独立工作目录完成原生媒体组件构建。scripts/build_media.py 记录核心固定来源与配方；构建工具需要 MinGW-w64、NASM、CMake、Ninja、make、pkg-config、Git Bash 和 Meson 1.9.2。原生构建工作路径需为无空格的 ASCII 路径。
3. 使用 scripts/BilingualVideo.spec 创建 GUI 与工作进程。公开构建不调用本机专用的运行时配置脚本，不移除或禁用现有环境的安全策略。
4. 根据已核验的材料运行 scripts/package_portable.py。它只从新构建、公开模型和许可材料组装到不存在的新目录，不复制已有安装目录。
5. 运行 scripts/audit_portable.py，传入需要排除的本机构建路径标记，并检查其报告。它会检查文件、模型哈希、许可材料及压缩 Python 代码；扫描通过不是法律意见或恶意软件认证。
6. 将 ZIP 解压到另外一个目录，限制 PATH，在新目录验证窗口启动、识别、离线翻译、英中/日中字幕排版、MP4 完整解码和精修结果预览。真实视频和用户密钥不进入发行包；若本机另行抽测片源，输入和记录仅留在私有验证目录。
7. 对最终 ZIP 计算 SHA-256，复核归档清单；公开源码与便携包对应同一提交。先上传草稿 Release，核对附件后再发布。

GitHub 自动检查验证源码和隐私规则，不代表已在所有处理器或一台全新 Windows 电脑通过安装测试。具体实测范围和限制见 VALIDATION.md 与包内构建信息。

## 使用和更新

完整解压到可写位置，双击 BilingualVideo.exe。保留整个文件夹，不要从压缩包中直接运行，也不要单独移动 exe。

API 密钥由使用者自行配置。离线英中可以使用 Argos；在线免费服务、网站下载和 API 仍需要网络，受第三方可用性影响。

更新前备份已有 settings、cache、exports 和 downloads；这些资料不属于可公开的初始便携包。加密密钥通常不能跨 Windows 账户直接复用。
