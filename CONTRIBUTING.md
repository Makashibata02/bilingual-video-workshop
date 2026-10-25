# 开发与贡献

1. 使用 Python 3.12 和独立虚拟环境。
2. 从 README 安装依赖；离线单元测试仅需 `requirements-test.txt`。模型准备需显式执行，不在导入应用时运行。
3. 不提交个人视频、实际字幕、密钥、加密配置、路径日志或抓取的网页数据。新增测试使用合成数据和虚构凭据。
4. 新增公开文件时，同步更新 `scripts/public-files.json`。CI 将拒绝不在白名单中的跟踪文件。
5. 运行 `python scripts/run_tests.py` 和 `python scripts/check_public.py --gitleaks`。
6. 功能验证请说明实际运行边界：合成测试、GUI 测试、模型推理、在线服务请求和真实视频导出分别验证了什么。

启用本地提交检查：`git config core.hooksPath .githooks`。需要系统 Python 和已安装的 Gitleaks；可通过 `python scripts/install_gitleaks.py` 获取固定版本到忽略目录。

PR 描述应说明问题、改后的行为、测试和仍未验证的部分。涉及 API 的测试使用本地模拟服务，不在 CI 中提供真实付费密钥。
