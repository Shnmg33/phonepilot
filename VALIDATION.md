# 验证记录（手机原生桥接版 0.2.0）

验证日期：2026-10-19（Asia/Shanghai）。

## Android 构建与安装包

已成功执行 Android Gradle 构建与 lint：

```text
gradle --offline :app:assembleDebug :app:lintDebug
BUILD SUCCESSFUL
```

- 实际 Java 编译、资源处理、DEX 转换及 APK 打包完成。
- APK 签名通过 `apksigner verify --verbose --print-certs` 验证（v2 签名）。
- 通过 `zipalign -c 4` 和 ZIP 文件完整性检查。
- 包名 `com.phonepilot.bridge`，版本 0.2.0 / versionCode 2。
- 最低 Android 11（API 30），目标 Android 15（API 35）。
- JDK 17、Gradle 8.11.1、Android Gradle Plugin 8.9.2、Build Tools 35.0.0。
- Debug 测试签名，适合当前个人验收，尚非应用商店正式发布版本。
- Android lint 无错误；剩余非阻断提示及明细见完整包 `releases/android-lint.txt`，精确数量见 `releases/BUILD-INFO.json`。提示涉及同步保存配置、备份声明兼容性和状态文字国际化，不影响本次构建。

完整交付包 `releases/` 包含 APK、SHA-256、签名证书摘要及 lint 结果；没有签名私钥、服务器令牌或模型密钥。以前的 SDK 下载阻塞已在本轮通过受限联网授权解决。

## 服务器与源码检查

此前最新服务器版本的 `python -m unittest discover -s tests -v`：16 项测试通过，约 23 秒。本轮仅更改 Android 备份配置和文档，未修改服务器逻辑。

测试使用真实 FastAPI 路由与 SQLite，模拟手机桥接和模型返回，覆盖：执行、复盘、技能证据、审核/版本/复用、停止、鉴权、调度、时区、重启恢复，以及锁屏/息屏排队、原生输入能力传递、长轮询、按需截图协议和待确认命令保护。

网页 JavaScript、Python、云服务器构建脚本及 Android XML 的语法检查已通过。GitHub Actions 工作流和通用云服务器脚本尚未单独在用户环境执行；本轮使用安装在开发环境中的同版本 SDK / JDK / Gradle 完成真实构建。

## 尚待实测

- iQOO Z3 实机安装、无障碍授权、手势、截图、中文输入、后台稳定性及重启恢复。
- 真实 DeepSeek / OpenAI 或其他厂商模型账号调用。
- Docker 构建、用户生产服务器部署、域名与 HTTPS。
- 浏览器视觉验收与真实触控操作。

没有使用用户密钥、调用真实付费模型或操作真实手机。构建通过不等于所有手机界面均可自动操作；实机验收步骤见 `android/README.md`。
