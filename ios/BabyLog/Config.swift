import Foundation

/// The one registration both clients share (docs/config.js has the same client ID; the test
/// compares them). The redirect is the iOS/macOS platform entry of that registration,
/// `msauth.<bundle id>://auth`; guide/MAC.md says how to add it.
enum Config {
    static let clientId = "8abd1f7d-91c4-4622-94ee-546adfa9ec8b"
    static let bundleId = "com.rollingshuttle.babylog"
    static let callbackScheme = "msauth.com.rollingshuttle.babylog"
    static let redirectUri = "msauth.com.rollingshuttle.babylog://auth"
    static let authority = "https://login.microsoftonline.com/consumers"
    // The one scope (CLAUDE.md rule 7) plus what a refresh token and a display name need.
    static let scopes = "Files.ReadWrite.AppFolder offline_access openid profile"
}
