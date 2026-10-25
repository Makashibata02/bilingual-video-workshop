# 双语视频工坊 · BilingualVideo

把英语、日语视频制作成中文字幕、双语字幕和带字幕成片。**导入后先设置，点击开始才处理。**

[下载 Windows 便携版](https://github.com/Makashibata02/bilingual-video-workshop/releases/latest) · [动漫模式](docs/ANIME.md) · [更新记录](CHANGELOG.md) · [问题反馈](https://github.com/Makashibata02/bilingual-video-workshop/issues)

![Windows x64](https://img.shields.io/badge/Windows-10%2F11%20x64-0078D6)
![GPL v3](https://img.shields.io/badge/License-GPLv3-blue)
![Checks](https://github.com/Makashibata02/bilingual-video-workshop/actions/workflows/ci.yml/badge.svg)

## 下载和开始使用

1. 从 [Releases](https://github.com/Makashibata02/bilingual-video-workshop/releases/latest) 下载 **BilingualVideo-1.9.5-windows-x64-portable.zip**。GitHub 的 Source code 是源码，不是可直接运行的程序。
2. **完整解压**到可写文件夹，双击 BilingualVideo.exe。无需安装 Python、FFmpeg、Node.js 或模型；不要只复制一个 exe。
3. 添加本地视频，或粘贴 YouTube / X 的公开视频链接下载。选择模式、翻译方案和字幕位置。
4. 可选“选择片段”，再点击“开始选中”。每次导出进入独立文件夹，原视频保持不变。

便携包包含 CPU 识别运行库、Whisper base / small、Argos 英中模型、FFmpeg、Node.js 和 Noto 中日文字体。体积较大是因为这些组件已随包提供。[SHA256 校验值](https://github.com/Makashibata02/bilingual-video-workshop/releases/download/v1.9.5/SHA256SUMS.txt)用于核对下载。

适用于 Windows 10/11 64 位。视频处理需要可用内存和输出空间。程序未购买代码签名证书，系统可能显示来源未知；请核对下载来源与校验值。

## 主要功能

- **英中、日中双语字幕**：优先使用原文 SRT，没有时在本机识别音频。
- **完整画面与窄字幕带**：中文在上、原文在下，也可选画面内字幕；不裁切、不放大原画面。
- **按需处理**：逐视频选片段、保存多套 API 方案、批量应用设置，导入与开始分开。
- **固定译名与上下文**：按作品复用人名和称呼，API 可先理解全部原文，再分批翻译。
- **可选自动精修**：默认关闭，复用原译，保存修改对照、额外耗时和 API 用量。
- **下载与导出**：YouTube / X 公开链接、自选保存位置，以及 SRT、ASS、MP4 输出。PPT 中文注释保留为默认关闭的可选功能。

## 选择翻译方式

| 方案 | 费用与网络 | 适用范围 |
| --- | --- | --- |
| 必应 | 免费网页接口，需要联网 | 英中、日中；保护已有作品译名，可能限流 |
| Google | 免费网页接口，需要联网 | 英中、日中；网络与限流可能导致不可用 |
| Argos | 本地离线，无需密钥 | **仅英中**，作为离线备用 |
| API | 自备服务与密钥，可能计费 | 英中、日中；全局理解、译名、省用量及精修 |

免费服务失败后**不会自动切换到付费 API**。可分别保存 DS Flash、DS Pro 等方案；实际模型由服务商的模型 ID 决定。开始前会确认联网与费用，API 测试也可能计费。

## 日语视频与自动精修

选择“日本动漫（日→中）”，可指定日文 SRT、使用同名 .ja.srt，或本地日语识别。普通同名 .srt 不会被直接当作日文。可先识别、校对，再继续翻译。[详细流程](docs/ANIME.md)

自动译名是作品内的约定，**不代表官方译名**，人工指定名称优先。未登记名称、代词和识别错误仍可能影响结果。

选择 API 方案后可开启自动精修，它沿用当前模型，对照原文校对已有中文，不重新识别或重译有效缓存。固定名称、说话人标签或备注检查不通过时保留原译，不自动重发请求；时间轴保持不变。

在“更多操作 → 校对与检查 → 查看精修修改”中查看对照和用量。换字幕位置或画质可以复用精修缓存。自动精修仍可能误改，有限对白抽测不等于整集人工校译。

## 简洁界面与本地资料

主界面保留常用操作。其余选项放在“更多设置”的四页：**翻译与精修 / 识别与作品 / 画面与导出 / 方案管理**。操作菜单按队列、校对和导出分组。

便携版的数据保存在自身文件夹：settings 为方案与作品资料，cache 为缓存，exports 为结果，downloads 为下载视频。更新前请保留这些本地资料，不要提交到 GitHub。加密密钥通常无法跨 Windows 账户解密。

默认使用 CPU 识别和 H.264 编码，按本机资源控制线程及优先级。**显示显卡信息不代表启用 GPU 加速**，线程预算也不是固定占用百分比。高保真保留源分辨率和帧率，不能修复原片已有模糊。

## 隐私与限制

- 音视频、识别和成片合成在本机；在线翻译发送字幕及相关语境，启用 PPT 注释时还发送所选说明文字。
- 密钥通过 Windows DPAPI 加密保存在本机；**加密配置同样不应上传**。
- 发行包不含作者的视频、真实字幕、配置、密钥、作品资料或处理日志。
- 下载受网络、登录要求和网站变化影响，不保证所有链接可用，不绕过付费墙或登录限制。
- 识别、翻译、精修及 OCR 可能有误；首版不含内封字幕提取、声纹识别、配音或歌词特效。

[隐私说明](PRIVACY.md) · [验证范围](docs/VALIDATION.md) · [便携版构建与依赖](docs/PORTABLE.md)

<details>
<summary><strong>开发者：源码运行、测试与构建</strong></summary>

目标环境为 Python 3.12，需包含 Tcl/Tk。普通使用者下载便携版即可。

~~~powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts/prepare_runtime.py --download
.\.venv\Scripts\python.exe app/main.py
~~~

源码运行资料默认放在 .local/runtime。模型需显式准备，不在处理途中静默下载。动漫推荐 small，可在界面准备，或运行：

~~~powershell
.\.venv\Scripts\python.exe scripts/prepare_runtime.py --download --groups asr-small
.\.venv\Scripts\python.exe -m pip install -r requirements-test.txt
.\.venv\Scripts\python.exe scripts/run_tests.py
~~~

测试使用合成数据、本地模拟服务和虚构密钥，不调用真实付费服务。公开便携版须在独立、可核验的环境构建，不能压缩个人安装目录。详见 [PORTABLE.md](docs/PORTABLE.md) 和 [RELEASE.md](docs/RELEASE.md)。

新增公开文件需更新 scripts/public-files.json；发布前重新扫描。整个本地工作目录不是可公开源码包。

</details>

## 开源许可

应用按 [GNU GPL v3](LICENSE) 分发，翻译适配代码保留 [VideoCaptioner](https://github.com/WEIFENG2333/VideoCaptioner) 的来源与 GPL 许可要求。

便携包附各依赖、模型和字体的许可。FFmpeg 及 GPL/LGPL 组件的对应源码、补丁和构建材料通过同一 Release 的 third-party-sources 附件提供；其他组件按各自许可分发。详见 [NOTICE.md](NOTICE.md)。

请在有权下载和处理视频的前提下使用本工具。
