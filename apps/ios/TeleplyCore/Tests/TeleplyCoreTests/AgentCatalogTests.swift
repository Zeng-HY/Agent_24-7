import Foundation
import Testing
@testable import TeleplyDemo
import TeleplyModel
@testable import TeleplyState

/// The computer's assistant list (GET /api/agents) and the catalog built from it (handoff 3.2; Android
/// AgentCatalogTest). The three old assistants must look exactly as before; a new one is drawn generically.
struct AgentCatalogTests {
    let device = String(repeating: "a", count: 32)

    static let antigravity = #"{"id":"antigravity","name":{"zh":"Antigravity","en":"Antigravity"},"order":40,"color":"#4285F4","color_dark":"#8AB4F8","icon":{"kind":"builtin","key":"generic"},"legacy":false,"min_protocol":2,"schema":1,"capabilities":{"list":true,"read":true,"search":true,"open":false,"stop":true,"queue":false,"steer":false,"approve":true,"answer":false,"new":true,"new_projectless":false,"new_permission":false,"archive":false,"restore":false,"delete":false,"usage":false,"waiting":true,"attachments":true,"slash_commands":false,"settings":[],"send_modes":["send"],"statuses":["running","waiting","idle","unknown"]},"params":{"state_timeout_s":40,"send_timeout_s":60,"open_timeout_s":45,"new_timeout_s":140,"refresh_ms":2500,"max_images":5,"max_image_bytes":20971520,"max_text":20000},"ui":{"card_layout":"generic.v1","waiting_text":"等待你处理"}}"#

    static func agents(_ entries: String...) -> [AgentInfo] {
        parseAgentsResponse(DemoData.parse(#"{"schema":1,"protocol":2,"agents":[\#(entries.joined(separator: ","))]}"#))
    }

    @Test func aManifestIsReadWhole() throws {
        let parsed = Self.agents(Self.antigravity)
        let agent = try #require(parsed.first)
        #expect(agent.id == "antigravity")
        #expect(agent.name.zh == "Antigravity" && agent.name.en == "Antigravity")
        #expect(agent.displayName("zh-Hans") == "Antigravity" && agent.displayName("en") == "Antigravity")
        #expect(agent.order == 40 && !agent.legacy && agent.minProtocol == 2)
        #expect(agent.color == "#4285F4" && agent.colorDark == "#8AB4F8")
        #expect(agent.icon.kind == "builtin" && agent.icon.key == "generic")
        #expect(agent.caps.list && agent.caps.read && agent.caps.stop && agent.caps.approve && agent.caps.new)
        #expect(!agent.caps.open && !agent.caps.queue && !agent.caps.steer && !agent.caps.answer)
        #expect(!agent.caps.archive && !agent.caps.usage && !agent.caps.slashCommands && !agent.caps.delete)
        #expect(agent.caps.sendModes == ["send"] && agent.caps.settings.isEmpty)
        #expect(agent.caps.skills == nil)  // the manifest does not say: the caller keeps its own old rule
        #expect(agent.caps.statuses == ["running", "waiting", "idle", "unknown"])
        #expect(agent.params.newTimeoutS == 140 && agent.params.refreshMs == 2_500 && agent.params.maxImageBytes == 20_971_520)
        #expect(agent.ui.cardLayout == "generic.v1" && agent.ui.waitingText == "等待你处理")
    }

    @Test func aBrokenEntryIsDroppedAlone() {
        let parsed = Self.agents(
            #"{"id":"Mail!","name":"坏掉的助手"}"#,                       // not a legal id
            #"{"name":{"zh":"没有编号"}}"#,                                // no id at all
            #"{"id":"testing","name":{"zh":"测试助手","en":"Test Helper"},"order":99}"#,
            #"{"id":"testing","name":{"zh":"重复的"}}"#)                   // the same id twice: the first one stands
        #expect(parsed.map(\.id) == ["testing"])
        #expect(parsed.first?.name.zh == "测试助手")
        // A manifest that says almost nothing still works: list and read by default, everything else off.
        let bare = Self.agents(#"{"id":"bare"}"#)
        #expect(bare.first?.caps.list == true && bare.first?.caps.read == true)
        #expect(bare.first?.caps.archive == false && bare.first?.caps.sendModes.isEmpty == true)
        #expect(bare.first?.ui.cardLayout == "generic.v1")
    }

    @Test func theThreeKeepTheAppsOwnNameColourAndMark() throws {
        // The computer may say anything about the three: name, colours, mark and the old-route flags are always the
        // app's own (handoff 3.2: 三家外观永远用 App 自己的，只用它的顺序和能力位).
        let parsed = Self.agents(
            #"{"id":"codex","name":{"zh":"别家的名字","en":"Someone else"},"order":10,"color":"#000000","color_dark":"#111111","icon":{"kind":"builtin","key":"generic"},"legacy":false,"min_protocol":9,"capabilities":{"archive":true}}"#)
        let catalog = AgentCatalogSnapshot.fromServer(parsed)
        let codex = try #require(catalog.agents.first { $0.id == "codex" })
        #expect(codex.name.zh == "Codex" && codex.name.en == "Codex")
        #expect(codex.color == "#1E222A" && codex.colorDark == "#EEEEEE")
        #expect(codex.icon.key == "codex" && codex.badgeColor == "#111111")
        #expect(codex.legacy && codex.minProtocol == 1)
        #expect(codex.caps.archive)  // the capabilities are the computer's
        #expect(catalog.order == ["codex", "claude", "deepseek"])
        #expect(catalog.isLegacy("codex") && catalog.isLegacy("claude") && catalog.isLegacy("deepseek"))
    }

    @Test func theThreeAreAlwaysThereEvenWhenTheComputerOmitsThem() {
        let catalog = AgentCatalogSnapshot.fromServer(Self.agents(Self.antigravity))
        #expect(catalog.order == ["codex", "claude", "deepseek", "antigravity"])
        #expect(catalog.fromServer)
        #expect(AgentCatalogSnapshot.builtin.order == ["codex", "claude", "deepseek"])
        #expect(!AgentCatalogSnapshot.builtin.isLegacy("antigravity"))
    }

    @Test func anUnknownAssistantIsDrawnGenericallyAndOnlyRead() {
        let builtin = AgentCatalogSnapshot.builtin
        #expect(builtin.name("other") == "other")
        #expect(builtin.color("other") == "#6B7280" && builtin.color("other", dark: true) == "#9CA3AF")
        #expect(builtin.badgeColor("other") == "#6B7280")
        let generic = builtin.info("other")
        #expect(generic.caps.list && generic.caps.read)
        #expect(!generic.caps.archive && !generic.caps.stop && !generic.caps.open)
        #expect(!builtin.isLegacy("other"))
        #expect(generic.displayName("zh-Hans") == "other")
    }

    @Test func aColourThatIsNotOneFallsBackToNeutralGrey() {
        let catalog = AgentCatalogSnapshot.fromServer(Self.agents(
            #"{"id":"broken-color","name":"颜色坏了","color":"blue","color_dark":"#12"}"#))
        #expect(catalog.color("broken-color") == "#6B7280")
        #expect(catalog.color("broken-color", dark: true) == "#9CA3AF")
        #expect(agentColorValue("#4285F4") == 0x4285F4)
        #expect(agentColorValue("#FF4285F4") == 0xFF4285F4)
        #expect(agentColorValue("4285F4") == 0x4285F4)
        #expect(agentColorValue("#4285F") == nil && agentColorValue("##4285F4") == nil)
    }

    @Test func aNameInOneLanguageOnlyShowsInBoth() {
        let catalog = AgentCatalogSnapshot.fromServer(Self.agents(#"{"id":"english-only","name":{"en":"English Only"}}"#))
        #expect(catalog.name("english-only", language: "zh-Hans") == "English Only")
        #expect(catalog.name("english-only", language: "en") == "English Only")
        let nameless = AgentCatalogSnapshot.fromServer(Self.agents(#"{"id":"nameless"}"#))
        #expect(nameless.name("nameless") == "nameless")
        #expect(Labels.sourceName("codex", catalog: .builtin) == "Codex")
        #expect(Labels.sourceName("nobody", catalog: .builtin) == "nobody")
    }

    @Test func idsAreCheckedLikeTheComputerChecksThem() {
        #expect(isValidAgentId("codex") && isValidAgentId("antigravity") && isValidAgentId("a_b-c9"))
        #expect(!isValidAgentId("") && !isValidAgentId("Codex") && !isValidAgentId("9codex"))
        #expect(!isValidAgentId("codex!") && !isValidAgentId("-codex"))
        #expect(!isValidAgentId(String(repeating: "a", count: 33)))
    }

    @Test func oneCatalogPerComputerAndOnlyItsOwnVersionAsksAgain() {
        let cache = AgentCatalog()
        #expect(cache.needsFetch(device))
        #expect(cache.snapshot(for: device).order == ["codex", "claude", "deepseek"])

        let stored = cache.store(Self.agents(Self.antigravity), for: device, version: "1.0")
        #expect(stored.order == ["codex", "claude", "deepseek", "antigravity"] && stored.fromServer)
        #expect(!cache.needsFetch(device) && cache.version(for: device) == "1.0")
        #expect(cache.snapshot(for: device).info("antigravity").caps.approve)

        // Another computer keeps its own answer (and the built-ins until asked).
        let other = String(repeating: "b", count: 32)
        #expect(cache.needsFetch(other))
        #expect(cache.snapshot(for: other).order == ["codex", "claude", "deepseek"])

        // The same version changes nothing; a new one says the manifest list must be fetched again.
        #expect(!cache.updateVersion("1.0", for: device))
        #expect(cache.updateVersion("1.1", for: device))
        #expect(cache.version(for: device) == "1.1")

        // An older computer (404): the three built-ins, remembered so it is not asked again on every screen.
        let builtinOnly = cache.store(nil, for: other, version: "0.8.0")
        #expect(!builtinOnly.fromServer && builtinOnly.order == ["codex", "claude", "deepseek"])
        #expect(!cache.needsFetch(other))

        cache.forget(device)
        #expect(cache.needsFetch(device))
        #expect(cache.snapshot(for: other).order == ["codex", "claude", "deepseek"])
        cache.forget()
        #expect(cache.needsFetch(other))
    }

    @Test func theTreesAppsKeepEveryLegalIdInCatalogOrder() throws {
        let tree = try JSONValue.parse(Data(#"{"apps":[{"app":"other"},{"app":"deepseek"},{"app":"codex"},{"app":"Not legal"},{"app":"codex"}]}"#.utf8))
        #expect(treeApps(tree) == ["codex", "deepseek", "other"])
        let catalog = AgentCatalogSnapshot.fromServer(Self.agents(Self.antigravity))
        let withAntigravity = try JSONValue.parse(Data(#"{"apps":[{"app":"antigravity"},{"app":"other"},{"app":"codex"}]}"#.utf8))
        #expect(treeApps(withAntigravity, catalog: catalog) == ["codex", "antigravity", "other"])
    }
}
