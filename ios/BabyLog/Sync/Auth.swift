import Foundation
import AuthenticationServices
import CryptoKit
import Security
import UIKit

struct TokenSet: Codable {
    var accessToken: String
    var refreshToken: String
    var expiresAt: Date
    var account: String
}

enum AuthError: Error, LocalizedError {
    case cancelled
    case signedOut
    case invalidGrant
    case message(String)

    var errorDescription: String? {
        switch self {
        case .cancelled: return "sign-in cancelled"
        case .signedOut: return "signed out"
        case .invalidGrant: return "sign-in expired"
        case .message(let m): return m
        }
    }
}

/// Sign-in by the authorization-code + PKCE flow of a public client, straight against the
/// /consumers endpoint: no SDK, so the first build on the Mac resolves no packages. The refresh
/// token (90 days for a native client, against the web app's 24 hours) lives in the keychain,
/// where MSAL would keep it too.
@MainActor
final class Auth: NSObject, ASWebAuthenticationPresentationContextProviding {
    static let shared = Auth()
    private var tokens: TokenSet? = Keychain.load()
    private var session: ASWebAuthenticationSession?

    var account: String? { tokens?.account }
    var isSignedIn: Bool { tokens != nil }

    nonisolated func presentationAnchor(for session: ASWebAuthenticationSession) -> ASPresentationAnchor {
        MainActor.assumeIsolated { () -> ASPresentationAnchor in
            let windows = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.flatMap { $0.windows }
            return windows.first { $0.isKeyWindow } ?? windows.first ?? ASPresentationAnchor()
        }
    }

    func signIn() async throws {
        let verifier = Auth.base64url(Auth.randomBytes(32))
        let challenge = Auth.base64url(Data(SHA256.hash(data: Data(verifier.utf8))))
        var parts = URLComponents(string: Config.authority + "/oauth2/v2.0/authorize")!
        parts.queryItems = [
            URLQueryItem(name: "client_id", value: Config.clientId),
            URLQueryItem(name: "response_type", value: "code"),
            URLQueryItem(name: "redirect_uri", value: Config.redirectUri),
            URLQueryItem(name: "scope", value: Config.scopes),
            URLQueryItem(name: "code_challenge", value: challenge),
            URLQueryItem(name: "code_challenge_method", value: "S256"),
            URLQueryItem(name: "prompt", value: "select_account"),
        ]
        let url = parts.url!
        let callback: URL = try await withCheckedThrowingContinuation { cont in
            let s = ASWebAuthenticationSession(url: url, callbackURLScheme: Config.callbackScheme) { url, error in
                if let url = url {
                    cont.resume(returning: url)
                } else {
                    cont.resume(throwing: error ?? AuthError.cancelled)
                }
            }
            s.presentationContextProvider = self
            s.prefersEphemeralWebBrowserSession = false
            self.session = s
            s.start()
        }
        let query = URLComponents(url: callback, resolvingAgainstBaseURL: false)?.queryItems ?? []
        guard let code = query.first(where: { $0.name == "code" })?.value else {
            throw AuthError.message(query.first(where: { $0.name == "error_description" })?.value ?? "no code in the redirect")
        }
        let set = try await Auth.exchange(["grant_type": "authorization_code", "code": code,
                                           "redirect_uri": Config.redirectUri, "code_verifier": verifier],
                                          previous: nil)
        tokens = set
        Keychain.save(set)
    }

    func signOut() {
        tokens = nil
        Keychain.clear()
    }

    /// A valid access token, refreshed when within two minutes of expiry; signs out when the
    /// service no longer accepts the refresh token.
    func accessToken() async throws -> String {
        guard let held = tokens else { throw AuthError.signedOut }
        if held.expiresAt > Date() { return held.accessToken }
        do {
            let fresh = try await Auth.exchange(["grant_type": "refresh_token", "refresh_token": held.refreshToken],
                                                previous: held)
            tokens = fresh
            Keychain.save(fresh)
            return fresh.accessToken
        } catch AuthError.invalidGrant {
            signOut()
            throw AuthError.signedOut
        }
    }

    private static func exchange(_ params: [String: String], previous: TokenSet?) async throws -> TokenSet {
        var form = params
        form["client_id"] = Config.clientId
        form["scope"] = Config.scopes
        var req = URLRequest(url: URL(string: Config.authority + "/oauth2/v2.0/token")!)
        req.httpMethod = "POST"
        req.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")
        req.httpBody = formEncode(form).data(using: .utf8)
        let (data, resp) = try await URLSession.shared.data(for: req)
        let obj = ((try? JSONSerialization.jsonObject(with: data)) as? [String: Any]) ?? [:]
        let status = (resp as? HTTPURLResponse)?.statusCode ?? 0
        guard status == 200, let access = obj["access_token"] as? String else {
            if (obj["error"] as? String) == "invalid_grant" { throw AuthError.invalidGrant }
            let detail = (obj["error_description"] as? String) ?? (obj["error"] as? String) ?? "token request failed (\(status))"
            throw AuthError.message(detail)
        }
        let expires = (obj["expires_in"] as? Double) ?? 3600
        let refresh = (obj["refresh_token"] as? String) ?? previous?.refreshToken ?? ""
        let account = accountName(idToken: obj["id_token"] as? String) ?? previous?.account ?? ""
        return TokenSet(accessToken: access, refreshToken: refresh,
                        expiresAt: Date().addingTimeInterval(max(expires - 120, 60)), account: account)
    }

    /// The signed-in name from the id_token payload (base64url JSON), for the Settings card.
    private static func accountName(idToken: String?) -> String? {
        guard let token = idToken else { return nil }
        let parts = token.split(separator: ".")
        guard parts.count >= 2 else { return nil }
        var s = String(parts[1]).replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
        while s.count % 4 != 0 { s += "=" }
        guard let data = Data(base64Encoded: s),
              let obj = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else { return nil }
        return (obj["preferred_username"] as? String) ?? (obj["email"] as? String) ?? (obj["name"] as? String)
    }
    private static func randomBytes(_ n: Int) -> Data {
        Data((0..<n).map { _ in UInt8.random(in: 0...255) })
    }
    private static func base64url(_ data: Data) -> String {
        data.base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }
    private static func formEncode(_ form: [String: String]) -> String {
        let allowed = CharacterSet.alphanumerics.union(CharacterSet(charactersIn: "-._~"))
        return form.map { "\($0.key)=\($0.value.addingPercentEncoding(withAllowedCharacters: allowed) ?? "")" }
            .joined(separator: "&")
    }
}

/// The token set as one generic-password item; nothing else of the user's is stored.
enum Keychain {
    private static var query: [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: Config.bundleId,
         kSecAttrAccount as String: "microsoft"]
    }
    static func save(_ set: TokenSet) {
        guard let data = try? JSONEncoder().encode(set) else { return }
        var add = query
        add[kSecValueData as String] = data
        add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        SecItemDelete(query as CFDictionary)
        SecItemAdd(add as CFDictionary, nil)
    }
    static func load() -> TokenSet? {
        var q = query
        q[kSecReturnData as String] = true
        q[kSecMatchLimit as String] = kSecMatchLimitOne
        var item: CFTypeRef?
        guard SecItemCopyMatching(q as CFDictionary, &item) == errSecSuccess, let data = item as? Data else {
            return nil
        }
        return try? JSONDecoder().decode(TokenSet.self, from: data)
    }
    static func clear() {
        SecItemDelete(query as CFDictionary)
    }
}
