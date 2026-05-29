import AVFoundation

// Plays a silent looping buffer to keep the app process alive in background
// so the /ws/live + /ws/steps WebSockets and HealthKit writes survive when
// the user switches apps. Requires the "Audio, AirPlay, and Picture in Picture"
// background mode capability.
final class BackgroundAudioKeeper {
    private let engine = AVAudioEngine()
    private let player = AVAudioPlayerNode()

    func start() {
        let session = AVAudioSession.sharedInstance()
        do {
            try session.setCategory(.playback, mode: .default, options: [.mixWithOthers])
            try session.setActive(true)
        } catch {
            return
        }

        guard let format = AVAudioFormat(standardFormatWithSampleRate: 44100, channels: 1) else {
            return
        }
        let frames: AVAudioFrameCount = 44100
        guard let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: frames) else {
            return
        }
        buffer.frameLength = frames

        engine.attach(player)
        engine.connect(player, to: engine.mainMixerNode, format: format)
        do {
            try engine.start()
        } catch {
            return
        }
        player.scheduleBuffer(buffer, at: nil, options: .loops, completionHandler: nil)
        player.play()
    }
}
