//
//  OAuthConfig.swift
//  Orange Cloud
//
//  在 Cloudflare Dashboard 创建 OAuth Client 后，填入真实 clientID。
//  redirect_uri 必须与 Dashboard 中注册的完全一致。
//

import Foundation

nonisolated enum OAuthConfig {
    // 从 Info.plist 读取真实值（见工程内 Info.plist 的 OAuthClientID / OAuthRedirectURI）。
    // 源码与仓库里只保留占位符，CI 构建时用 GitHub Actions Secrets 经 plutil 注入真实值，
    // 从而避免把个人 OAuth Client ID / 回调地址写入公开仓库。
    // 注意：Client Secret 不需要填进 App——本工程用 PKCE，token 交换在 App 端完成。

    /// 你自己的 Cloudflare OAuth Client（Cloudflare Dashboard → My Profile → OAuth apps）
    static var clientID: String {
        Bundle.main.object(forInfoDictionaryKey: "OAuthClientID") as? String ?? ""
    }

    /// 自定义 scheme，供 Web 后端 302 跳回 App（对应 Info.plist 里注册的 CFBundleURLSchemes）
    static let callbackScheme = "orangecloud"

    /// 你自己部署的回调中转地址（https，Cloudflare OAuth 只接受 https redirect_uri）
    static var redirectURI: String {
        Bundle.main.object(forInfoDictionaryKey: "OAuthRedirectURI") as? String ?? ""
    }

    // Cloudflare OAuth 端点
    static let authorizationURL = URL(string: "https://dash.cloudflare.com/oauth2/auth")!
    static let tokenURL         = URL(string: "https://dash.cloudflare.com/oauth2/token")!
    static let revokeURL        = URL(string: "https://dash.cloudflare.com/oauth2/revoke")!
    static let userInfoURL      = URL(string: "https://dash.cloudflare.com/oauth2/userinfo")!
}
