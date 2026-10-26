import Testing
import TeleplyDemo
import TeleplyModel
import TeleplyState

@MainActor
struct LaunchModelTests {
    @Test func showsTheServiceVersion() async {
        let model = LaunchModel(client: RelayClient(origin: .default, transport: DemoTransport()))
        #expect(model.phase == .checking)
        await model.check()
        #expect(model.phase == .reachable(version: "fixture"))
    }

    @Test func saysWhenTheServiceCannotBeReached() async {
        let model = LaunchModel(client: RelayClient(origin: .default, transport: UnreachableTransport()))
        await model.check()
        #expect(model.phase == .unreachable(message: "连不上服务器，请检查网络后重试。"))
    }

    @Test func theDemoCanPlayAnUnreachableService() async {
        let model = LaunchModel(client: RelayClient(origin: .default, transport: DemoTransport(unreachable: true)))
        await model.check()
        #expect(model.phase == .unreachable(message: "连不上服务器，请检查网络后重试。"))
    }
}
