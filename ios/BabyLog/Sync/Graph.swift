import Foundation

enum GraphError: Error, LocalizedError {
    case http(Int, String)
    case throttled(Int)
    case badResponse

    var errorDescription: String? {
        switch self {
        case .http(let code, let what): return "HTTP \(code) \(what)"
        case .throttled(let s): return "throttled for \(s) s"
        case .badResponse: return "bad response"
        }
    }
}

struct GraphItem {
    let id: String
    let name: String
    let relative: String?      // "events/<day>/<name>" or "children/<name>" when inside the journal
    let isFolder: Bool
    let deleted: Bool
    let size: Int
    let downloadUrl: String?
}

struct DeltaPage {
    let items: [GraphItem]
    let nextLink: String?
    let deltaLink: String?
}

/// The Graph client: a delta walk over the app folder (every change since the last sync, in a
/// few pages, instead of listing day folders one by one), downloads through the pre-authorised
/// download URL in parallel (off Graph's throttling budget), and simple uploads that refuse to
/// overwrite. 429 and 503 become GraphError.throttled with the Retry-After seconds.
struct Graph {
    static let base = "https://graph.microsoft.com/v1.0"
    let token: () async throws -> String

    private func request(_ method: String, _ url: URL, body: Data? = nil,
                         contentType: String? = nil) async throws -> (Data, HTTPURLResponse) {
        let bearer = try await token()
        var req = URLRequest(url: url)
        req.httpMethod = method
        req.setValue("Bearer " + bearer, forHTTPHeaderField: "Authorization")
        if let ct = contentType { req.setValue(ct, forHTTPHeaderField: "Content-Type") }
        req.httpBody = body
        let (data, resp) = try await URLSession.shared.data(for: req)
        guard let http = resp as? HTTPURLResponse else { throw GraphError.badResponse }
        if http.statusCode == 429 || http.statusCode == 503 {
            throw GraphError.throttled(Int(http.value(forHTTPHeaderField: "Retry-After") ?? "") ?? 30)
        }
        if http.statusCode == 401 { throw AuthError.signedOut }
        return (data, http)
    }
    private func json(_ data: Data) -> [String: Any] {
        ((try? JSONSerialization.jsonObject(with: data)) as? [String: Any]) ?? [:]
    }
    private func enc(_ path: String) -> String {
        path.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? path
    }

    func approotId() async throws -> String {
        let (data, http) = try await request("GET", URL(string: Graph.base + "/me/drive/special/approot")!)
        guard http.statusCode == 200, let id = json(data)["id"] as? String else {
            throw GraphError.http(http.statusCode, "approot")
        }
        return id
    }

    /// One page of the delta walk; `link` is the previous page's nextLink or the stored
    /// deltaLink, nil for a walk from the beginning.
    func delta(folderId: String, link: String?) async throws -> DeltaPage {
        let url = URL(string: link ?? (Graph.base + "/me/drive/items/" + folderId + "/delta"))!
        let (data, http) = try await request("GET", url)
        guard http.statusCode == 200 else { throw GraphError.http(http.statusCode, "delta") }
        let obj = json(data)
        let items = ((obj["value"] as? [[String: Any]]) ?? []).map { item -> GraphItem in
            let name = (item["name"] as? String) ?? ""
            let parent = (item["parentReference"] as? [String: Any])?["path"] as? String
            return GraphItem(id: (item["id"] as? String) ?? "", name: name,
                             relative: Graph.relativePath(parent: parent, name: name),
                             isFolder: item["folder"] != nil, deleted: item["deleted"] != nil,
                             size: (item["size"] as? Int) ?? 0,
                             downloadUrl: item["@microsoft.graph.downloadUrl"] as? String)
        }
        return DeltaPage(items: items, nextLink: obj["@odata.nextLink"] as? String,
                         deltaLink: obj["@odata.deltaLink"] as? String)
    }
    /// "events/<day>/<name>" or "children/<name>" for an item inside the journal, else nil.
    static func relativePath(parent: String?, name: String) -> String? {
        guard let p = parent else { return nil }
        if p.hasSuffix("/children") { return "children/" + name }
        if let r = p.range(of: "/events/", options: .backwards) {
            let day = String(p[r.upperBound...])
            if day.count == 10 && !day.contains("/") { return "events/" + day + "/" + name }
        }
        return nil
    }

    func download(_ item: GraphItem) async throws -> Data {
        if let u = item.downloadUrl, let url = URL(string: u) {
            let (data, resp) = try await URLSession.shared.data(from: url)
            if (resp as? HTTPURLResponse)?.statusCode == 200 { return data }
        }
        // The listing's URL is missing or has expired: ask for the item again and use its fresh one.
        let (meta, http) = try await request("GET", URL(string: Graph.base + "/me/drive/items/" + item.id)!)
        guard http.statusCode == 200, let u = json(meta)["@microsoft.graph.downloadUrl"] as? String,
              let url = URL(string: u) else {
            throw GraphError.http(http.statusCode, "download " + item.name)
        }
        let (data, resp) = try await URLSession.shared.data(from: url)
        guard (resp as? HTTPURLResponse)?.statusCode == 200 else {
            throw GraphError.http((resp as? HTTPURLResponse)?.statusCode ?? 0, "download " + item.name)
        }
        return data
    }

    /// Simple upload; a 409 means the same name is already there, i.e. this file landed on an
    /// earlier attempt (names are unique per write, so nothing else can own one).
    func upload(relative: String, data: Data) async throws {
        let url = URL(string: Graph.base + "/me/drive/special/approot:/" + enc(relative)
                      + ":/content?%40microsoft.graph.conflictBehavior=fail")!
        let (body, http) = try await request("PUT", url, body: data, contentType: "application/json")
        switch http.statusCode {
        case 200, 201, 409: return
        default: throw GraphError.http(http.statusCode, String(data: body, encoding: .utf8) ?? "upload")
        }
    }

    /// Create a folder (and its parents) under the app folder; existing ones are left alone.
    func ensureFolder(_ path: String) async throws {
        let parts = path.split(separator: "/").map(String.init)
        guard let name = parts.last else { return }
        let parent = parts.dropLast().joined(separator: "/")
        let url = parent.isEmpty ? Graph.base + "/me/drive/special/approot/children"
                                 : Graph.base + "/me/drive/special/approot:/" + enc(parent) + ":/children"
        let payload: [String: Any] = ["name": name, "folder": [String: Any](),
                                      "@microsoft.graph.conflictBehavior": "fail"]
        let body = try JSONSerialization.data(withJSONObject: payload)
        let (_, http) = try await request("POST", URL(string: url)!, body: body, contentType: "application/json")
        if http.statusCode == 404 && !parent.isEmpty {
            try await ensureFolder(parent)
            try await ensureFolder(path)
            return
        }
        guard [200, 201, 409].contains(http.statusCode) else {
            throw GraphError.http(http.statusCode, "folder " + path)
        }
    }
}
