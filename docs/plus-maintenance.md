# Plus 维护记录

## 来源和范围

- 上游：`https://github.com/skyhua0224/moonlight-macos-enhanced.git`。
- 基线：`c4dd84da`，1.3.9 RC7。
- 本分支：`https://github.com/Weicoz/moonlight-macos-enhanced-plus`。
- 当前版本：`1.3.9-plus.1`。这是基于 RC7 的补丁版，不代表上游已发布 1.3.9 最终版。
- 保留上游视频渲染、编码、配对协议和授权。系统代理、路由、AWDL 配置及主机配置不属于本次修改范围。

## 修复和验证

### 轮询资源和取消

`Limelight/Network/DiscoveryWorker.m` 的 NSOperation 长期运行。原循环只在单次 HTTP 请求内释放临时对象，整个发现周期创建的对象等待外层 pool 结束。每轮独立的 autorelease pool 现在及时释放这些对象。

原来每 0.1 秒检查取消，2 秒内最多唤醒 20 次。现在通过 semaphore 等待下次轮询，取消时主动唤醒；轮询间隔保持 2 秒。这只减少等待期间的唤醒，不代表应用总 CPU 下降 95%。

实际界面测试还发现重复的自动切换地址提示。原发现逻辑在每轮把可用的当前地址重置为地址列表首项，绕过后面的 30 秒切换冷却期。现在保留仍在线的当前地址，失效时选可用的最佳地址；低延迟切换继续使用原有阈值和冷却期。手动地址和正在串流的地址保持原有规则，系统网络配置未变。

### USB 停止和退出

`Limelight/Network/RemoteUSBForwardingSession.m` 原先同步等待串行 worker。该队列包含设备枚举、辅助进程输出和退出等待；界面调用 stop 时会一起阻塞。现在异步排队，保留停止与后续启动的顺序，并消除从 worker 回调 stop 时同步等待自身的死锁。

dealloc 直接释放已有资源，不再重新排队捕获正在析构的对象。后台 USB 驱动或辅助进程本身是否无限阻塞，仍需物理设备专项验证。

### 更新来源

Sparkle appcast、GitHub 版本查询、源码和下载链接均指向本 fork。移除上游签名公钥和上游镜像回退，避免后续自动更新覆盖 Plus 补丁。未配置本 fork 的签名公钥时，保留手动下载和版本查询，禁用自动安装。

不复用上游私钥。未来启用 Sparkle 时，将本 fork 的公钥设置为仓库的 `SPARKLE_ED_PUBLIC_KEY` secret，并用对应私钥签署最终归档。发布脚本拒绝其他仓库的下载前缀。

### 文件提供器打包

上游扩展的构建号固定为 1，且未设置营销版本。扩展现在与主应用共用 Version.xcconfig 和相同营销版本。签名脚本拒绝版本不一致的扩展，防止把错误版本带进安装包。

## 检查命令

```sh
python3 tests/resource-lifecycle/run.py
python3 tests/window-cleanup/run.py
python3 tests/startup-endpoint/run.py
python3 tests/capslock/run.py
bash tests/iec61937/run.sh
```

资源回归检查执行生产方法：原代码分别因轮询对象未释放和 USB 队列拖住调用者而失败，修复后通过。窗口、端点、键盘及音频检查使用上游现有测试。CI 对两个架构构建和 Universal 合并之前运行前四项检查；音频码流检查需要本机 FFmpeg。

这些隔离检查不等于真实断网恢复、物理 USB、全屏、菜单退出或长时间串流验收。实机结果单独记录，不将构建成功等同于全部性能问题解决。

## 构建

使用 Xcode 27。依照 `.github/workflows/build.yml` 下载 XCFramework、构建 dav1d，并安装 USB helper 所需 CMake。构建命令：

```sh
xcodebuild -project Moonlight.xcodeproj -scheme 'Moonlight for macOS' \
  -configuration Release -derivedDataPath build \
  -destination 'platform=macOS,arch=arm64' -jobs 2 \
  ARCHS=arm64 ONLY_ACTIVE_ARCH=YES CODE_SIGN_IDENTITY=- \
  CODE_SIGNING_REQUIRED=NO CODE_SIGNING_ALLOWED=NO \
  BUILD_NUMBER=7001 UPDATE_DISPLAY_VERSION=1.3.9-plus.1 build
python3 scripts/sign_app_bundle.py build/Build/Products/Release/MoonlightEnhanced.app \
  --entitlements Moonlight.entitlements \
  --extension-entitlements FileProviderExtension/FileProvider.entitlements
```

Intel 将目标和 ARCHS 改为 x86_64。CI 沿用上游 Universal 合并与签名校验。应用未经 Apple 公证；ad-hoc 签名校验不能代表 Apple 公证。

## 同步上游

先核对 `git remote get-url upstream`。更新上游后，在维护分支合并 `upstream/master`，解决冲突，运行上述检查并完成三个构建，再推送本 fork 的 master。不得使用 `gh repo sync --force` 覆盖 Plus 提交。上游重构作为单独迁移评估，避免直接覆盖本地可用版本。

构建和同步上游由维护操作触发。本仓库不自动合并未审查的上游提交，也不自动发布安装包。
