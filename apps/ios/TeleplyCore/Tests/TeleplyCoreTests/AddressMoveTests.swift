import Foundation
import Synchronization
import Testing
@testable import TeleplyDemo
import TeleplyModel
@testable import TeleplyState

/// A keychain that cannot be read or written until [unlock] (KeychainVault.Locked: not unlocked since the phone started).
final class LockableVault: CookieVault, Sendable {
    struct Locked: Error {}

    let kept = MemoryCookieVault()
    private let locked = Mutex(true)

    func unlock() {
        locked.withLock { $0 = false }
    }

    func read(_ key: String) throws -> SessionCookie? {
        if locked.withLock({ $0 }) { throw Locked() }
        return try kept.read(key)
    }

    func write(_ key: String, _ cookie: SessionCookie?) throws {
        if locked.withLock({ $0 }) { throw Locked() }
        try kept.write(key, cookie)
    }
}

/// Teleply's own service moved from its IP to its domain (AppModel.moveToDomain): once per phone, signed in, with the
/// place, drafts and records kept; an address set by hand afterwards stays.
@MainActor
struct AddressMoveTests {
    let a = DemoData.computerA
    let ip = ServiceOrigin.formerDefault
    let signIn = SessionCookie(value: "synthetic", expires: nil)

    func app(_ store: LocalStore, _ vault: any CookieVault, _ transport: any RelayTransport) -> AppModel {
        AppModel(services: AppServices(store: store, vault: vault, transport: transport, demo: { DemoTransport() },
                                       pacer: IdlePacer(), newScope: { "scope-new" }))
    }

    /// The relay with this phone's sign-in still good (it does not tie a sign-in to an address).
    func signedInWorld() -> DemoWorld {
        let world = DemoWorld()
        world.state.withLock { $0.signedIn = true }
        return world
    }

    @Test func aPhoneOnTheIPMovesToTheDomainSignedInAndWhereItWas() async throws {
        let store = LocalStore(folder: temporaryFolder()), vault = MemoryCookieVault()
        var place = Place()
        place.origin = "https://8.166.15.235"
        place.scope = "scope-1"
        place.device = a
        place.chat = "demo"
        place.title = "原生阅读示例"
        await store.savePlace(place)
        let key = ChatKey(scope: "scope-1", device: a, app: "codex", chat: "demo")
        await store.setDraft(key, "还没发的话")
        try vault.write(ip.key, signIn)
        let transport = WatchedTransport(world: signedInWorld())
        let model = app(store, vault, transport)
        model.start()
        await model.settle()
        #expect(model.origin == .default && model.screen == .reading && model.chat?.id == "demo" && model.scope == "scope-1")
        #expect(try vault.read(ServiceOrigin.default.key) == signIn && vault.read(ip.key) == nil)
        let saved = await store.place()
        #expect(saved.origin.isEmpty && saved.movedToDomain && saved.scope == "scope-1" && saved.device == a && saved.chat == "demo")
        #expect(await store.draft(key) == "还没发的话")
        // Every request went to the domain, with the sign-in, and each POST with the domain's Origin.
        let sent = await transport.log.items
        #expect(!sent.isEmpty && sent.allSatisfy { $0.url.host == "app.pocketagentdesk.com" })
        #expect(sent.first { $0.url.path == "/account/state" }?.headers["Cookie"] == "__Host-ar_account=synthetic")
        #expect(sent.contains { $0.method == .post })
        #expect(sent.filter { $0.method == .post }.allSatisfy { $0.headers["Origin"] == "https://app.pocketagentdesk.com" })
    }

    /// Nothing saved meant the default of the time, the IP.
    @Test func nothingSavedMeantTheIPAndMovesToo() async throws {
        let store = LocalStore(folder: temporaryFolder()), vault = MemoryCookieVault()
        try vault.write(ip.key, signIn)
        let model = app(store, vault, WatchedTransport(world: signedInWorld()))
        model.start()
        await model.settle()
        #expect(model.origin == .default && model.screen == .devices && model.account != nil)
        #expect(try vault.read(ServiceOrigin.default.key) == signIn && vault.read(ip.key) == nil)
        let saved = await store.place()
        #expect(saved.origin.isEmpty && saved.movedToDomain)
    }

    @Test func onceMovedTheIPSetByHandStays() async throws {
        let store = LocalStore(folder: temporaryFolder()), vault = MemoryCookieVault()
        let world = signedInWorld()
        let first = app(store, vault, WatchedTransport(world: world))
        first.start()
        await first.settle()
        #expect(first.origin == .default)
        first.connect("https://8.166.15.235")
        await first.settle()
        #expect(first.origin == ip)
        let again = app(store, vault, WatchedTransport(world: world))
        again.start()
        await again.settle()
        #expect(again.origin == ip)
        #expect(await store.place().origin == "https://8.166.15.235")
        // A sign-in made there by hand stays there.
        try vault.write(ip.key, signIn)
        let third = app(store, vault, WatchedTransport(world: world))
        third.start()
        await third.settle()
        #expect(try third.origin == ip && vault.read(ip.key) == signIn && vault.read(ServiceOrigin.default.key) == nil)
    }

    @Test func anotherServiceAndItsSignInAreLeftAsTheyAre() async throws {
        let store = LocalStore(folder: temporaryFolder()), vault = MemoryCookieVault()
        let own = try ServiceOrigin("https://relay.example.invalid")
        var place = Place()
        place.origin = own.header
        place.scope = "scope-1"
        await store.savePlace(place)
        try vault.write(own.key, SessionCookie(value: "own", expires: nil))
        try vault.write(ip.key, signIn)
        let model = app(store, vault, WatchedTransport(world: signedInWorld()))
        model.start()
        await model.settle()
        #expect(model.origin == own)
        #expect(try vault.read(own.key)?.value == "own" && vault.read(ip.key) == signIn && vault.read(ServiceOrigin.default.key) == nil)
        let saved = await store.place()
        #expect(saved.origin == own.header && saved.scope == "scope-1" && saved.movedToDomain)
    }

    /// A sign-in made on the domain by hand before the move is the newer one; the IP's goes.
    @Test func aSignInTheDomainHasAlreadyIsKept() async throws {
        let store = LocalStore(folder: temporaryFolder()), vault = MemoryCookieVault()
        try vault.write(ip.key, signIn)
        try vault.write(ServiceOrigin.default.key, SessionCookie(value: "newer", expires: nil))
        let model = app(store, vault, WatchedTransport(world: signedInWorld()))
        model.start()
        await model.settle()
        #expect(try vault.read(ServiceOrigin.default.key)?.value == "newer" && vault.read(ip.key) == nil)
    }

    @Test func aLockedKeychainLeavesTheMoveForTheNextLaunch() async throws {
        let store = LocalStore(folder: temporaryFolder()), vault = LockableVault()
        try vault.kept.write(ip.key, signIn)
        var place = Place()
        place.origin = "https://8.166.15.235"
        await store.savePlace(place)
        let world = signedInWorld()
        let first = app(store, vault, WatchedTransport(world: world))
        first.start()
        await first.settle()
        let moved = await store.place().movedToDomain
        #expect(first.origin == ip && !moved)
        vault.unlock()
        let again = app(store, vault, WatchedTransport(world: world))
        again.start()
        await again.settle()
        #expect(again.origin == .default && again.screen == .devices)
        #expect(try vault.read(ServiceOrigin.default.key) == signIn && vault.read(ip.key) == nil)
        #expect(await store.place().movedToDomain)
    }
}
