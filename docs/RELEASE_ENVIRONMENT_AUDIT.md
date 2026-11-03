# 妙妙二玩箱 0.5.0-rc3 Release 依赖环境审计

日期：2026-11-03（北京时间）。结论：**BLOCK：干净 Windows 10/11 真实兼容性测试未执行，且本轮联网预览后退出测试失败。** 包内容审计和开发机来源预览可分别通过，不构成 Release 全部门槛通过。

后续F6复验（同日）：以下原始失败记录继续保留。F6加入关闭阶段诊断并修复GUI等待生命周期锁、不可取消冒烟线程等风险，最终干净提交ZIP已通过真实20条预览后正常关闭/重启及原完整桌面隔离回归，退出码0、端口可重绑、桌面锁可重取、SQLite正常。最终交付包结果见 OB6_E2_F6_SHUTDOWN_FIX.md 及交付。**干净Windows10/11仍未测试，环境兼容Release门槛继续BLOCK。** 不回写旧审计为通过。

## 审计对象

- ZIP：`dist/desktop-0.5.0-rc3-F5-delivery-final/ErYouToolbox-0.5.0-rc3-win-x64.zip`。
- SHA-256：`f8e0bffe3e9481a11712403688d2a2323cc95f1f297c6f8516b431a159e64817`。
- 构建源码：`928389d1094e7d36283751d3edc0b1f4e5a39071`，BUILD_INFO记录干净构建。
- 本轮不修改客户端代码、UI、同步、schema或ZIP；只新增启动依赖模拟测试并更新文档。未执行生产apply、安装软件、注册任务、提交、推送或Release发布。

## 包内依赖审计：PASS

PyInstaller onedir通过EXE bootloader加载`_internal/python315.dll`，并非需要用户安装Python或单独运行python.exe。标准库位于base_library.zip和内嵌PYZ，原生扩展位于_internal。

实际读取最终EXE的PyInstaller归档，以下PYZ模块均存在：webview、pythonnet、clr_loader、proxy_tools、bottle、typing_extensions、cffi、httpx、httpcore、h11、anyio、certifi、idna、sqlite3、ssl，以及项目API/同步模块。审计的是该功能所需模块闭包与已执行运行路径，不声称能单凭文件存在证明所有动态路径都通过。

原生文件包括python315.dll、_sqlite3.pyd/sqlite3.dll、_ssl.pyd、libssl-3.dll、libcrypto-3.dll、_cffi_backend、VCRUNTIME140.dll、VCRUNTIME140_1.dll和ucrtbase.dll。托管桥接包含Python.Runtime.dll、clr_loader组件、Microsoft.Web.WebView2.Core.dll、WinForms.dll及x64 WebView2Loader.dll。WebView2 SDK DLL版本1.0.3856.49；**Loader/SDK不是浏览器Runtime**。

构建版本：Python3.15.1、pywebview6.2.1、pythonnet3.2.1、clr_loader0.3.1、PyInstaller6.22.3、httpx0.28.1。React为生产静态资源，无Vite/Node服务。完整目录不可只复制EXE。

## 必需系统依赖

| 依赖 | 当前包与要求 | 分发方式 |
|---|---|---|
| Windows x64 | Python3.15官方支持Windows10及更新版本；本产品未据此获得Win10实测通过 | 建议验收Win10 22H2与当前Win11，ARM/旧Windows不在本次认证范围 |
| .NET Framework | 包内WinForms SDK目标v4.6.2，Python.Runtime为.NETStandard2.0；pywebview检测Release>=394802。建议4.8/4.8.1，未测试所有低版本 | 使用官方Framework安装器/系统更新，不能复制系统CLR DLL充当便携运行时；可能需管理员权限和重启 |
| WebView2 Evergreen | 必需且未打包。使用当前受支持版本。pywebview检测代码历史门槛86.0.622.0不能视为本应用所有API的已验证最低版本 | 官方Bootstrapper联网安装，或官方x64 Standalone离线安装；支持每用户/每机器安装 |
| VC/UCRT | 已含相关VC运行库和UCRT DLL；仍依赖Windows系统组件 | 不因审计自动安装VC开发工具或SDK；干净系统确认无额外缺失DLL |

pythonnet在Windows默认加载netfx，本构建未附带CoreCLR；安装.NET 6/8/10不能视作安装.NET Framework。pywebview内部虽有CoreCLR回退，不把未经本包验证的回退当发行要求或支持保证。

WebView2可按微软分发条款随安装器携带官方安装包并经明确安装流程调用，不应无提示修改系统。Fixed Version也可按条款打包，但涉及路径、体积、更新和权限策略，本候选未接入，不能把文件丢进目录就声称支持。Framework可按微软再分发许可使用官方安装程序，需检查系统支持、签名、退出码和重启要求。本轮不制作安装器、不下载或安装这些依赖。

官方依据：

- [Python Windows支持](https://docs.python.org/3.15/using/windows.html)
- [pywebview Windows引擎要求](https://pywebview.flowrl.com/guide/web_engine.html)
- [Python.NET运行时选择](https://pythonnet.github.io/pythonnet/python.html)
- [WebView2分发指南](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution)
- [.NET Framework部署指南](https://learn.microsoft.com/en-us/dotnet/framework/deployment/deployment-guide-for-developers)
- [.NET Framework系统版本](https://learn.microsoft.com/en-us/dotnet/framework/install/on-windows-and-server)

## 错误提示与测试范围

现有desktop_app.py在prepare_data之前检测WebView2。缺失时以“妙妙二玩箱启动失败”原生消息框提示需要Microsoft Edge WebView2 Runtime，包含`https://developer.microsoft.com/microsoft-edge/webview2/`，返回1；不创建替代库、不自动下载。当前提示已有明确官方地址，不为审计重新打包。

新增`tests/test_release_environment.py`两项模拟测试通过：注册表缺失返回False；main捕获错误并显示官方URL，portable_root与prepare_data均未调用。**这些是模拟，不是已卸载WebView2的干净机器实测。** 当前未单独预检.NET Framework版本，CLR加载异常会由现有异常处理显示原始错误；低版本/损坏.NET时的具体用户体验待干净快照验收。

本机实测环境：Windows11家庭版中文版，10.0.26200 x64；Win32_OperatingSystem用于判定，Get-ComputerInfo的Windows10旧名称不采信。Framework注册表Release533509（4.8.1系列，Version字符串4.8.09221）；WebView2 156.0.4314.58。

当前未找到WindowsSandbox.exe、Hyper-V vmms或已配置的vmrun/VBoxManage入口，也没有提供可使用的干净虚拟机。Windows Home本身不支持官方Windows Sandbox，不擅自升级系统、安装虚拟化或卸载开发依赖。因此不得称已在干净Windows运行。

## 实际首次启动与来源预览（开发机）

将原ZIP完整解压到源码外新临时目录，使用实际中文EXE，子进程PATH仅Windows/System32，无PYTHONHOME/PYTHONPATH，不启动Vite。成功创建空库，六游戏配置加载。

通过现有API对原神8552执行`check`、`max_pages=1`，最多2次HTTP预算（含重试）；实际1次请求，20条真实来源记录，20条新增候选，coverage=incomplete。未调用confirm，MOD总数前后均0，临时数据库SHA-256不变。**20是预览候选，不是实际写入数量。** 生产数据、已阅和关注未操作。

初次辅助脚本使用60秒自动关闭参数，而复用的等待函数只等待40秒，产生TimeoutExpired。追加等待35秒后仍未退出，不能仅归因于等待参数；本次自动smoke关闭路径未通过。随后发送正常WM_CLOSE并等待20秒仍未退出，提升权限的只读CIM复查确认同一测试进程及端口仍在运行。受限环境Get-Process未显示进程，不能据此判断已退出。

清理时严格核验PID、唯一临时EXE路径、`--smoke-seconds 60`命令及进程创建时间，只终止本轮未确认入库的闲置测试进程；清理后端口释放。这是测试清理，**不是正常退出通过**。结果单独记录于`Release-network-followup.json`，原始失败记录保留，无新增来源请求。现阶段无法确认卡住位置及根因；不将其归因于WebView2、CDN或缺少依赖，也不以F5旧测试通过覆盖新失败。本轮不修改关闭业务逻辑，须另行修复并复验后解除此项Release阻断。

退出异常的最后诊断/清理曾因自动审批服务额度不足未执行，用户要求继续后重新正常通过审批完成；未绕过审批。开发正式库及已知旧便携库的SHA-256复查与F4基线相同，未进行生产写入。

证据位于忽略的logs/content_ratings：Release-dependency-payload.json、Release-host-webview.json、Release-runtime-tests.txt、Release-first-launch-network.json、Release-network-followup.json。F5原有独立解压测试作为已有证据，不当作本轮干净系统测试。

## 必须补齐的干净系统实测

在两份干净Windows10/11 x64虚拟机或真实电脑快照中执行，不安装Python、Node、pnpm；保存winver、系统架构、Framework Release与WebView2版本。

1. 核对上述ZIP SHA-256，完整解压到本机可写目录，首次启动前确认无userdata。不要导入任何个人数据库。
2. 缺少WebView2的快照先运行，截取原生错误与官方URL，确认没有创建userdata；从官方页面安装Evergreen x64后重试。已有Runtime的系统不为测试冒险卸载，应使用独立快照。
3. 验证窗口、六游戏和空库；拒绝首次自动入库授权，选择手动。点击刷新，仅一个游戏一页，只预览，不执行自动或生产入库；记录HTTP结果、扫描量、错误及coverage。
4. 关闭检查所属进程和端口退出；重启确认userdata继续使用。已阅/关注持久化如要测试写入，只使用这份干净测试库，勿用生产数据。
5. 测试无网、403/429等失败提示；不绕过来源验证。测试完成记录PASS/PARTIAL/FAIL、截图及日志，不把无法联网误写为依赖缺失。
6. 两种系统实测完成后方能解除本轮环境BLOCK。系统重启或Runtime安装由操作者明确确认；本轮不执行。

模拟测试复验命令（开发环境）：

```powershell
$python = Join-Path $env:LOCALAPPDATA 'ErYouToolbox\venv\Scripts\python.exe'
& $python -m unittest discover -s tests -p test_release_environment.py
```

目标电脑仅运行EXE，无需上述Python命令。此报告不授权或宣告Release发布。
