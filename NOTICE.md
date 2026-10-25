# 来源与第三方组件

应用源码按根目录 LICENSE 中的 GNU GPL v3 分发。

## 改编来源

- VideoCaptioner — https://github.com/WEIFENG2333/VideoCaptioner ，GPL-3.0。
- Bing / Google 适配器最初参考其 `videocaptioner/core/translate/` 实现，保留了引擎文件头中的来源说明。
- Bing 网页会话协议另参考 plainheart/bing-translate-api（MIT）：https://github.com/plainheart/bing-translate-api 。
- Google JSON 接口参考 py-googletrans（MIT）：https://github.com/ssut/py-googletrans 。

本项目增加本地流水线编排、队列、恢复、凭据隔离、布局和界面等逻辑。不能以其他宽松许可替换此衍生应用的 GPL 许可。

## 使用的运行库与模型

| 组件 | 用途 | 来源 / 许可说明 |
| --- | --- | --- |
| faster-whisper | 英语语音识别 | https://github.com/SYSTRAN/faster-whisper ，MIT |
| Whisper base 转换权重 | 本地识别模型 | https://huggingface.co/Systran/faster-whisper-base ，按其模型卡许可 |
| CTranslate2 / SentencePiece | 本地模型推理与分词 | 各组件原始许可 |
| Argos en→zh 1.9 | 离线翻译 | https://github.com/argosopentech/argos-translate ，模型包附说明 |
| OPUS-MT 模型 | Argos 包内权重来源 | 包内说明为 CC-BY 4.0，作者 Jörg Tiedemann、Santhosh Thottingal，2020 |
| RapidOCR / PP-OCRv3 | 可选 PPT OCR | https://github.com/RapidAI/RapidOCR ，RapidOCR 为 Apache-2.0；保留各模型来源 |
| yt-dlp / yt-dlp-ejs | 视频链接下载 | https://github.com/yt-dlp/yt-dlp 、https://github.com/yt-dlp/ejs ；Unlicense，EJS 内第三方代码还包含 MIT / ISC 条款 |
| FFmpeg | 媒体处理 | https://ffmpeg.org/ ，具体许可随二进制编译选项变化 |
| fontTools | 日文字体字形覆盖检查 | https://github.com/fonttools/fonttools ，保留原始许可 |
| Python / Tcl/Tk、Pillow、OpenCV、ONNX Runtime、Pyclipper、Shapely、Requests 等 | 基础运行环境 | 保留对应版本的原始许可 |

源码 ZIP 不包含模型、FFmpeg、Python 运行库、第三方二进制或网站视频。重新分发可执行程序、模型或相关依赖时，需要另外整理其完整许可、署名、源码义务及适用的分发条件。
