<div align="center">

# Orange Cloud 自编译指南 / Self-Build Guide

完整、可照做的「自己编译未签名 IPA 并登录 Cloudflare」全流程。

English follows the Chinese section.

</div>

---

## 中文

> 目标：**完全靠自己编译出一个未签名 IPA，并在手机上安装、登录自己的 Cloudflare 账号**。整个流程不依赖 `o-c.do` 官方回调中转，也不依赖官方 Client ID。
>
> 适用：GitHub Actions 云端编译（无需本地 Mac），或本地 Xcode 编译（macOS + Xcode 26）。

### 第 0 步：理解要配的三样东西

编译出的 App 要能登录 Cloudflare，需要三个环节**一一对应、逐字符一致**：

```
App(Info.plist 值)  --登录-->  Cloudflare OAuth Client(redirect URL)  --回调-->  你的 Worker(https)  --302-->  orangecloud:// 回 App
```

| 环节 | 需要什么 |
|---|---|
| Cloudflare OAuth Client | 在 Cloudflare 账户里创建一个 OAuth 客户端，拿到 **Client ID** |
| 回调 Worker | 一个可公开访问的 **https 端点**，把授权码 302 转回 App（Cloudflare 只接受 https 回调） |
| App 构建注入 | 把 `Client ID` 和那个 https 回调地址，注入到 App 的 `Info.plist` |

`OPENSOURCE_UNLOCKED` 编译条件只影响**功能是否解锁**，和登录是两回事；登录成功与否取决于上面三样是否配对。

### 第 1 步：在 Cloudflare 创建 OAuth Client

1. 登录 [dash.cloudflare.com](https://dash.cloudflare.com)
2. 进入 **Manage Account（管理账户）→ OAuth clients → Create client**（地址形如 `https://dash.cloudflare.com/?to=/:account/oauth-clients`；需要 Super Admin / Admin / `OAuth Client Write` 权限）
3. 填表：
   - **Client name**：随便，如 `Orange Cloud (self)`
   - **Response type**：`Code`
   - **Grant type**：`Authorization Code` + `Refresh Token`（都要，否则 token 到期无法续期）
   - **Token authentication method**：选 PKCE / `none`（**不要**选需要 secret 的方式，App 端不发送 client_secret）
   - **Redirect URLs**：填你要部署的回调点，例如 `https://你的worker名.你的子域.workers.dev/oauth/callback`（**必须是 https**）
4. **Continue** → 在 **Scopes** 页面勾选需要用到的权限。建议把 App 会用到的都勾上（对照 `apps/ios/Orange Cloud/Orange Cloud/Models/PermissionModels.swift` 里出现的 scope，如 `zone.*`、`dns.*`、`workers-*`、`r2.*`、`d1.*`、`logpush`、`analytics.*`、`account-rule-lists.*`、`page.*`、`query-cache.*`、`notifications.*` 等），保持默认 Required
5. **Create client**，保存页面上给的 **Client ID**（PKCE 流程用不到 Client Secret）

> 可见性说明：
> - **Private**（默认）：只有你账户的成员能用——**自用选这个**，无需域名所有权验证。
> - **Public**：任何 Cloudflare 用户都能用它登录自己的账号——**要分发给别人用才需要**，且**改成 Public 不可逆**，并要求完成 Client URL 的域名所有权验证（DNS TXT）。

### 第 2 步：部署回调 Worker

Cloudflare OAuth 只允许 **https** 回调，所以需要一个 HTTPS 端点把 `code`/`state` 302 转回 App 的自定义 scheme（`orangecloud://`）。两种方式任选：

**方式 A（推荐）：普通 Worker + workers.dev 子域**——自带有效证书，零 DNS/SSL 配置。
在 Cloudflare **Workers & Pages → Create** 新建 Worker，粘贴如下脚本并部署，记下你的地址 `https://<worker>.<子域>.workers.dev/oauth/callback`：

```js
export default {
  async fetch(request) {
    const url = new URL(request.url);
    const code  = url.searchParams.get("code");
    const state = url.searchParams.get("state");
    const error = url.searchParams.get("error");
    const app = new URL("orangecloud://oauth/callback");
    if (error) {
      app.searchParams.set("error", url.searchParams.get("error_description") ?? error);
    } else if (code && state) {
      app.searchParams.set("code", code);
      app.searchParams.set("state", state);
    } else {
      app.searchParams.set("error", "invalid_response");
    }
    return Response.redirect(app.toString(), 302);
  }
}
```

**方式 B：自定义域名**。在 Cloudflare 上绑定你的域名子域到该 Worker（DNS 记录要开 **proxy（橙色云朵）**，并保证该子域 **Universal SSL** 已启用）。这种方式需要更多证书/路由排查，非必要不建议。

> 证书注意：iOS 登录用的是 `ASWebAuthenticationSession`，它不提供"忽略证书错误"的入口，所以回调点**必须提供有效 HTTPS 证书**。自建域名证书有问题时，直接用 workers.dev 子域最省事。

### 第 3 步（仅 GitHub Actions 编译时）：配置仓库 Secrets

如果你用仓库自带的 `Build iOS IPA` workflow 编译，需要在 **Settings → Secrets and variables → Actions** 新增两个变量（workflow 会把它们写进 `Info.plist`，源码里只保留占位符）：

| Secret | 值 |
|---|---|
| `CLOUDFLARE_CLIENT_ID` | 第 1 步拿到的 Client ID |
| `CLOUDFLARE_REDIRECT_URI` | 第 2 步的实际回调地址，形如 `https://<worker>.<子域>.workers.dev/oauth/callback` |

> **一致性**：`CLOUDFLARE_REDIRECT_URI`、OAuth Client 里的 `Redirect URLs`、Worker 实际可达的完整 https 路径，**三处必须逐字符相同**（连结尾斜杠都要一致）。

### 第 4 步：编译未签名 IPA

**方式 A：GitHub Actions（推荐，无需本地 Mac）**
1. 本仓库 → **Actions** → `Build iOS IPA` → **Run workflow**
2. `signing_mode` 选 `unsigned`（`signed` 需另外配置证书 Secrets）
3. 构建完成后，IPA 会作为 artifact 上传；若已启用 Release 步骤，也会发布到 **`OPENSOURCE_UNLOCKED`** 这个 Release 标签下

**方式 B：本地 Xcode**
1. 用 Xcode 26 打开 `apps/ios/Orange Cloud/Orange Cloud.xcodeproj`
2. 在 `Orange Cloud` target 的 **Build Settings → SWIFT_ACTIVE_COMPILATION_CONDITIONS** 里，追加 `OPENSOURCE_UNLOCKED`
3. 用 `plutil` 或 Xcode 工程变量，把 `OAuthClientID` / `OAuthRedirectURI` 填成真实值
4. 命令行 archive（不签名）：

   ```bash
   xcodebuild archive \
     -project "Orange Cloud/Orange Cloud.xcodeproj" \
     -scheme "Orange Cloud" \
     -configuration Release \
     -archivePath OrangeCloud.xcarchive \
     -destination "generic/platform=iOS" \
     CODE_SIGNING_ALLOWED=NO \
     SWIFT_ACTIVE_COMPILATION_CONDITIONS="OPENSOURCE_UNLOCKED"
   ```

5. 从 archive 取出 `Products/Applications/Orange Cloud.app`，放入 `Payload/` 后压缩成 `.ipa`

> 提醒：编译前把 **Bundle ID、App Group、签名团队**改成你自己的（与第三方构建不冲突）。

### 第 5 步：在 iPhone 上安装

未经签名的 IPA 无法直接安装，需要侧载工具：

- **AltStore / SideStore**：用**免费 Apple ID** 签名安装，有效期 **7 天**，到期需重签/刷新
- **TrollStore**：**永久免签**，但需要你的设备支持（TrollStore 兼容机型 + iOS 版本）
- **开发者/企业签名**：有开发者账号可自签，效期更长

### 第 6 步：登录 Cloudflare

打开 App → 登录 → 弹出系统授权窗口 → 在浏览器里**登录你自己的 Cloudflare 账号**并同意授权 → 授权码经你的 Worker 转回 App，完成登录（多账号时用"重新授权"补齐缺失权限）。

### 常见问题排查

| 现象 | 原因与处理 |
|---|---|
| 登录报 `scope ... is invalid/not allowed` | OAuth Client 里**没勾全** App 请求的 scope。去 `Manage Account → OAuth clients` 补勾所需 scope，无需重设；建议在 Scopes 里一次性勾齐全 |
| 回调页提示"连接非私人连接/证书无效" | 回调域名**没有有效 HTTPS 证书**，iOS 的登录流程没有"跳过"入口。改用 workers.dev 子域或修好该子域证书 |
| Actions 报 `Unable to resolve action ...@v3` | action 引用了**不存在的 tag**。改用维护者实际发布的版本号（如 `@v3.4.3`） |
| 编译报 `compiler is unable to type-check this expression in reasonable time` | 个别复杂 SwiftUI `body` 表达式类型检查超时。换更强的 runner 也可能偶发；根治是把对应 `body` 拆成子表达式 |
| `OPENSOURCE_UNLOCKED` 已加但功能没解锁 | 确认该编译条件是否真的传进了 `SWIFT_ACTIVE_COMPILATION_CONDITIONS`（Actions 里通过变量注入时检查日志） |

### 上游更新同步（fork 用户）

若你 fork 了本项目，建议把上游设为远程并定期合并：

```bash
git remote add upstream https://github.com/chen2he/orange-cloud
git fetch upstream
git merge upstream/main
git push origin main
```

你独有的改动（如 self-build 的 workflow / 指南）尽量放在独立新文件里，可降低合并冲突。

---

## English

> Goal: **build an unsigned IPA entirely by yourself, install it, and sign in to your own Cloudflare account** — without depending on the official `o-c.do` callback relay or the official Client ID.
>
> Covers: GitHub Actions cloud build (no Mac needed), or a local Xcode build (macOS + Xcode 26).

### Step 0 — The three pieces that must line up

For the build to sign in to Cloudflare, three pieces must match **character-for-character**:

```
App (Info.plist values) --login--> Cloudflare OAuth Client (redirect URL) --callback--> your Worker (https) --302--> orangecloud:// back to App
```

| Piece | What it needs |
|---|---|
| Cloudflare OAuth Client | Create an OAuth client in your Cloudflare account, get its **Client ID** |
| Callback Worker | A public **https** endpoint that 302-redirects the authorization code back to the app (Cloudflare only accepts https callbacks) |
| App build injection | Put the `Client ID` + that https callback URL into the app's `Info.plist` |

`OPENSOURCE_UNLOCKED` only controls **feature unlock**; it is unrelated to login. Login works only when the three pieces above are paired correctly.

### Step 1 — Create the Cloudflare OAuth Client

1. Sign in to [dash.cloudflare.com](https://dash.cloudflare.com)
2. Go to **Manage Account → OAuth clients → Create client** (roughly `https://dash.cloudflare.com/?to=/:account/oauth-clients`; requires Super Admin / Admin / `OAuth Client Write` role)
3. Fill in the form:
   - **Client name**: anything, e.g. `Orange Cloud (self)`
   - **Response type**: `Code`
   - **Grant type**: `Authorization Code` **and** `Refresh Token` (both — otherwise tokens can't be refreshed)
   - **Token authentication method**: PKCE / `none` (do **not** pick a secret-based method; the app never sends a client_secret)
   - **Redirect URLs**: your callback endpoint, e.g. `https://<your-worker>.<subdomain>.workers.dev/oauth/callback` (**must be https**)
4. Click **Continue**, then on the **Scopes** page check the permissions you need. Prefer to check all the scopes the app uses (cross-check the scope IDs in `apps/ios/Orange Cloud/Orange Cloud/Models/PermissionModels.swift`, e.g. `zone.*`, `dns.*`, `workers-*`, `r2.*`, `d1.*`, `logpush`, `analytics.*`, `account-rule-lists.*`, `page.*`, `query-cache.*`, `notifications.*`), keep the default "Required".
5. **Create client**, then save the **Client ID** shown (PKCE doesn't need the Client Secret).

> Visibility:
> - **Private** (default): only members of your account can use it — **choose this for personal use**; no domain verification needed.
> - **Public**: any Cloudflare user can sign in with their own account via it — needed only if you **distribute to others**; switching to Public is **irreversible** and requires completing Client URL domain-ownership verification (DNS TXT).

### Step 2 — Deploy the callback Worker

Cloudflare OAuth only allows **https** callbacks, so you need an https endpoint that 302-redirects `code`/`state` to the app's custom scheme (`orangecloud://`). Two options:

**Option A (recommended): plain Worker on a workers.dev subdomain** — automatic valid certificate, zero DNS/SSL setup.
In Cloudflare **Workers & Pages → Create**, create a Worker, paste the script below, deploy it, and note your URL `https://<worker>.<subdomain>.workers.dev/oauth/callback`:

```js
export default {
  async fetch(request) {
    const url = new URL(request.url);
    const code  = url.searchParams.get("code");
    const state = url.searchParams.get("state");
    const error = url.searchParams.get("error");
    const app = new URL("orangecloud://oauth/callback");
    if (error) {
      app.searchParams.set("error", url.searchParams.get("error_description") ?? error);
    } else if (code && state) {
      app.searchParams.set("code", code);
      app.searchParams.set("state", state);
    } else {
      app.searchParams.set("error", "invalid_response");
    }
    return Response.redirect(app.toString(), 302);
  }
}
```

**Option B: custom domain.** Bind a subdomain of a domain you control on Cloudflare to the Worker (the DNS record must be **proxied** (orange cloud)), and make sure that subdomain has **Universal SSL** enabled. This needs more cert/routing debugging; avoid unless necessary.

> Certificate note: iOS uses `ASWebAuthenticationSession`, which has **no "ignore certificate error"** path — the callback endpoint **must serve a valid https certificate**. If your custom domain's cert is troublesome, use a workers.dev subdomain instead.

### Step 3 — (GitHub Actions only) Configure repo secrets

If you build with the repo's `Build iOS IPA` workflow, add two variables under **Settings → Secrets and variables → Actions** (the workflow writes them into `Info.plist`; the source only keeps placeholders):

| Secret | Value |
|---|---|
| `CLOUDFLARE_CLIENT_ID` | the Client ID from Step 1 |
| `CLOUDFLARE_REDIRECT_URI` | the actual callback URL from Step 2, e.g. `https://<worker>.<subdomain>.workers.dev/oauth/callback` |

> **Consistency**: `CLOUDFLARE_REDIRECT_URI`, the OAuth Client's `Redirect URLs`, and the Worker's actual reachable full https path must match **character-for-character** (including a trailing slash).

### Step 4 — Build an unsigned IPA

**Option A: GitHub Actions (recommended, no local Mac)**
1. Repo → **Actions** → `Build iOS IPA` → **Run workflow**
2. Set `signing_mode` to `unsigned` (`signed` needs extra certificate secrets)
3. After it finishes, the IPA is uploaded as an artifact; if the Release step is enabled, it is also published under the **`OPENSOURCE_UNLOCKED`** release tag

**Option B: local Xcode**
1. Open `apps/ios/Orange Cloud/Orange Cloud.xcodeproj` with Xcode 26
2. Add `OPENSOURCE_UNLOCKED` to the `Orange Cloud` target's **Build Settings → SWIFT_ACTIVE_COMPILATION_CONDITIONS**
3. Fill real values for `OAuthClientID` / `OAuthRedirectURI` via `plutil` or Xcode build variables
4. Archive without signing:

   ```bash
   xcodebuild archive \
     -project "Orange Cloud/Orange Cloud.xcodeproj" \
     -scheme "Orange Cloud" \
     -configuration Release \
     -archivePath OrangeCloud.xcarchive \
     -destination "generic/platform=iOS" \
     CODE_SIGNING_ALLOWED=NO \
     SWIFT_ACTIVE_COMPILATION_CONDITIONS="OPENSOURCE_UNLOCKED"
   ```

5. Take `Products/Applications/Orange Cloud.app` out of the archive, put it in a `Payload/` folder, and zip it into a `.ipa`

> Tip: change the **Bundle ID, App Groups, and signing team** to yours before building (so builds don't clash with third-party ones).

### Step 5 — Install on iPhone

An unsigned IPA can't be installed directly; use a sideloading tool:

- **AltStore / SideStore**: sign with a **free Apple ID**; valid **7 days**, re-sign/refresh on expiry
- **TrollStore**: **permanently unsigned**, but your device must be supported (compatible iPhone/iPad model + iOS version)
- **Developer/enterprise signing**: with a dev account you can self-sign for a longer validity

### Step 6 — Sign in to Cloudflare

Open the app → Sign in → the system auth window pops up → in the browser **sign in to your own Cloudflare account** and approve → the code returns through your Worker → done (use "re-authorize" to top up missing scopes for multiple accounts).

### Troubleshooting

| Symptom | Cause & fix |
|---|---|
| Login error `scope ... is invalid/not allowed` | The OAuth Client **didn't have all** the scopes the app requests. Re-check `Manage Account → OAuth clients` and check the missing scope; no rebuild needed. Better to check them all at once |
| Callback page says "not a private connection / certificate invalid" | The callback domain **has no valid https certificate**, and iOS login has no "skip" path. Switch to a workers.dev subdomain or fix the subdomain cert |
| Actions error `Unable to resolve action ...@v3` | The workflow referenced a **non-existent tag**. Use the tag actually published by the maintainer (e.g. `@v3.4.3`) |
| Build error `compiler is unable to type-check this expression in reasonable time` | Some complex SwiftUI `body` expression times out the type checker. A stronger runner may help intermittently; the real fix is to break that `body` into sub-expressions |
| `OPENSOURCE_UNLOCKED` added but features locked | Confirm the condition is actually passed to `SWIFT_ACTIVE_COMPILATION_CONDITIONS` (in Actions, check the logs of the injection step) |

### Keeping a fork in sync with upstream

If you forked the project, add upstream as a remote and merge periodically:

```bash
git remote add upstream https://github.com/chen2he/orange-cloud
git fetch upstream
git merge upstream/main
git push origin main
```

Keep your own changes (like a self-build workflow or this guide) in separate new files to reduce merge conflicts.