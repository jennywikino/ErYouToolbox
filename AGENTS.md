# 项目工作规则

- 所有项目文件只在当前 `ErYouToolbox` 根目录内创建或修改；操作前检查已有文件，不覆盖用户内容。
- 项目可能位于移动硬盘，不硬编码盘符；脚本从自身路径定位项目根目录。
- Python 虚拟环境放在本机 `%LOCALAPPDATA%\ErYouToolbox\venv`，不得放在移动硬盘项目内。
- 仅请求完成任务所需的公开数据；保护个人配置、凭据和原始响应，不登录、不绕过验证、不下载 MOD 文件或图片。
- 控制请求数量与频率，遵守服务端限流；网络失败如实记录，不伪造结果。
- 保持改动最小，只实现当前明确要求；未经明确要求不提交、推送或上传数据。


ErYouToolbox Windows 开发规范：

所有 Python 测试、脚本执行和验收命令，
必须使用项目虚拟环境解释器。

PowerShell 标准写法：

$python = Join-Path $env:LOCALAPPDATA 'ErYouToolbox\venv\Scripts\python.exe'

& $python <参数>

禁止在验收说明中直接使用：
python scripts/...
python -m unittest ...

除非明确说明已经激活正确的虚拟环境。

不得因为全局 Python 缺少依赖，
就向全局环境安装项目依赖。
