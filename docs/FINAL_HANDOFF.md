# 妙妙二玩箱最终候选交接 · CLOSE-2

日期：2026-11-04。**状态PARTIAL：冻结包、JSON与状态持久化通过；界面交互和干净系统尚待人工验收。** 功能维护冻结，本轮未创建tag、commit、push或Release。

## 指定交付（仅此包）

- `dist/desktop-0.5.0-rc3-CLOSE2-candidate/ErYouToolbox-0.5.0-rc3-CLOSE2-win-x64.zip`
- 大小：21,429,915字节，约20.44MiB。
- SHA-256：`0eb1a01e968b259947338aeb8ff382e3d4eef8e3707c7678f14103700057a8e2`。
- Windows x64 onedir，`ErYouToolbox/妙妙二玩箱.exe`与`_internal`需完整保留。
- 基线Git：`7d5cacb9ffd8e3958909c2979cf33870181504b5`，**dirty=true**，构建标识CLOSE-2；不是仅由该提交能复现的干净Release。81个运行源码输入的散列在包内SOURCE_INPUTS.json，其SHA-256为`a42119b4ae63bcce2222de3a867f16c97dc1cea9abb4ce8218e313d0c4856694`，BUILD_INFO记录工具版本与资源清单。

同目录不含CLOSE2后缀的ZIP是本轮构建中间包，不作为交付；旧rc3与历史包未移动删除。指定ZIP由本轮全新PyInstaller载荷整理，不复用旧rc3冒充。

## 架构、构建与用户数据

React/TypeScript生产静态资源由Python本地HTTP服务同源提供，pywebview/WinForms/WebView2显示窗口，SQLite保存作品与个人状态。只绑定127.0.0.1动态端口。EXE内含Python3.15.1、pywebview6.2.1、pythonnet3.2.1、PyInstaller6.22.3构建依赖；无需用户预装Python/Node/pnpm。系统仍需WebView2 Evergreen与.NET Framework（建议4.8/4.8.1）。并非纯粹无外部系统依赖。

程序资源只读；首次在EXE旁userdata创建空库和运行状态，绝不自动读取开发库。关闭所有写入后独立备份完整userdata再更新，程序文件更新不能覆盖userdata。不得只复制活动SQLite主文件、删除WAL/SHM或用新空库替换个人库。项目跨E/F盘采用自身路径，实物跨设备仍待人工测试。

开发构建方式（本轮已执行前端构建及以下PyInstaller流程，未安装新依赖）：

```powershell
$python = Join-Path $env:LOCALAPPDATA 'ErYouToolbox\venv\Scripts\python.exe'
& $python scripts/build_desktop.py --output dist/desktop-NEW-UNUSED-DIRECTORY
```

构建脚本使用本机既有packaging-venv，不覆盖开发或全局Python。输出目录必须全新，以免覆盖历史包；前端先用`pnpm.cmd --dir frontend build`生成dist。最终说明及源码指纹是在新载荷上整理后重新ZIP，故指定交付的SHA与初始中间ZIP不同。

## 本轮最小修复及实际测试

本轮新增/修改9个项目文件：scripts/build_desktop.py、src/eryoutoolbox/app_resources.py、tests/test_app_resources.py、.gitignore、README.md、PROJECT_STATUS.md、docs/RELEASE_CHECKLIST.md、docs/FINAL_HANDOFF.md、docs/FINAL_RELEASE_NOTES.md。此前OB7源码改动继续保留，未覆盖或提交。诊断脚本、截图与报告只放入已忽略logs。

仅第一轮发布阻断修复：显式收集src/eryoutoolbox/character_aliases.json至`_internal/eryoutoolbox/character_aliases.json`，同时纳入RESOURCE_MANIFEST。games.json、品牌ICO/PNG、React资源和依赖继续使用原白名单流程。资源测试覆盖JSON缺失、非法格式及散列不符，构建/启动不应接受篡改资源。

- 相关资源测试9项、角色查询7项，共16项本轮通过；未重跑完整518项。CLOSE-1的518项/前端17项/TypeScript构建仅作为前置历史证据，不伪装成CLOSE-2新成绩。
- 指定最终ZIP完整解压至源码外中文/空格临时目录，实际EXE首次空库启动、正常退出、重启通过，六游戏API返回6项。
- 临时SQLite只存英文Hu Tao/Furina标题及英文子分类，中文原词直接匹配数为0；实际冻结API搜索胡桃、芙宁娜、Hu Tao、ID900000001均1条，限定错误游戏返回0。证明包内JSON实际生效，不是源码路径检查或中文标题碰巧命中。
- 临时已阅与作者关注经EXE关闭/重启后保留；integrity_check=ok、foreign_key_check无违规，进程正常结束且端口释放。没有生产入库，GameBanana实际请求0次。
- GUI CDP驱动50秒超时，导航点击、正常MOD图片/画廊、详情返回滚动位置不能标通过；不无限重试或以API通过替代GUI。截取实际候选自身窗口作为[本地证据](../logs/content_ratings/CLOSE2-window-actual.png)，没有截取其他窗口或桌面。

截图中都是明确标注的模拟作品，品牌PNG为用户确认可分发素材；临时图片服务关闭后截图中出现失败占位，是故意模拟失效，不能据此判断GameBanana CDN。截图可见品牌、六游戏缩写、缺失/失败占位，但不证明点击和完整返回流程通过。不会用拼接页面或合成图冒充实际软件。

证据：logs/content_ratings/CLOSE2-resource-tests.txt、CLOSE2-final-probe.json、CLOSE2-artifact.json、CLOSE2-build.txt。第一次原始探测及GUI错误记录保留，不把失败改成成功。

## 内容安全与来源

包内审计无userdata、个人SQLite/备份、日志、测试profile、原始reference资料包、token、个人项目身份或开发node_modules。依赖许可证随THIRD_PARTY_NOTICES.json，品牌权利声明沿用用户明确授权；不虚构MOD作者授权。原始reference文件保留在本地并加入Git忽略，不暂存。姓名事实索引269个中文键来自已有第三方快照及旧词条，不是官方完整角色表，未获统一官方背书；未扩词。详见CHARACTER_SEARCH_INDEX.md。

暂存区为空，现有源码/文档未提交成果保留。后续只能明确白名单暂存，勿git add .；发布前要另确认dirty源码归档与分发范围。本轮不代用户公开发行。

## 人工验收清单

1. 核对上述SHA，完整解压到新可写目录，启动中文EXE；先用临时空库，不清理旧userdata。
2. 六游戏依次点击，检查选中、分类清理及窗口缩放；确认顶部旧下拉/Streamlit入口已移除。
3. 收录少量用户确认的测试记录后验证胡桃/芙宁娜/英文/ID，测试从Jane Doe分类进行全局搜索，检查已阅/图片筛选的结果说明。
4. 正常封面与高清图、无图/失效占位及重试；进入详情后返回页码/筛选/滚动位置。
5. 只在测试库设置已阅、关注，关闭重开确认；确认端口释放、原userdata保留。
6. 干净Windows10/11（无开发Python/Node）、缺WebView2提示及官方安装、真实E/F跨设备尚未验收。完成并明确授权后才能考虑最终tag/Release。

本轮结档为本地候选与资料准备，不自动进入下一OB、不承诺发布就绪。
