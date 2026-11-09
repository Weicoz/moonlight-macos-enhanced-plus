"""Run production polling and USB shutdown methods against Foundation adapters."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
discovery = (root / "Limelight/Network/DiscoveryWorker.m").read_text()
usb = (root / "Limelight/Network/RemoteUSBForwardingSession.m").read_text()

polling = discovery[discovery.index("@implementation DiscoveryWorker {"):
                    discovery.index("static const float POLL_RATE")]
polling += "static const float POLL_RATE = 2.0f;\n"
polling += discovery[discovery.index("- (id) initWithHost:"):
                     discovery.index("- (NSArray*) getHostAddressList")]
polling += r'''
- (void)discoverHost {
    assert(liveTokens == 0 && "Previous discovery cycle retained autoreleased objects");
    [[[Token alloc] init] autorelease];
    rounds++;
    if (rounds == 1 && firstPoll) dispatch_semaphore_signal(firstPoll);
    if (stopDuringPoll) [self cancel];
}
@end
int main(void) { @autoreleasepool {
    DiscoveryWorker *worker = [[DiscoveryWorker alloc] initWithHost:nil uniqueId:nil];
    worker->stopDuringPoll = YES;
    [worker main];
    assert(liveTokens == 0 && "Completed poll must drain its autorelease pool");
    assert(worker->rounds == 1);
    [worker release];

    worker = [[DiscoveryWorker alloc] initWithHost:nil uniqueId:nil];
    worker->firstPoll = dispatch_semaphore_create(0);
    dispatch_semaphore_t done = dispatch_semaphore_create(0);
    dispatch_async(dispatch_get_global_queue(0, 0), ^{
        @autoreleasepool { [worker main]; }
        dispatch_semaphore_signal(done);
    });
    assert(dispatch_semaphore_wait(worker->firstPoll, dispatch_time(DISPATCH_TIME_NOW, NSEC_PER_SEC)) == 0);
    [worker cancel];
    assert(dispatch_semaphore_wait(done, dispatch_time(DISPATCH_TIME_NOW, NSEC_PER_SEC / 2)) == 0);
    assert(liveTokens == 0);
    [worker release];
    worker = [[DiscoveryWorker alloc] initWithHost:nil uniqueId:nil];
    [worker cancel]; [worker main];
    assert(worker->rounds == 0);
    [worker release];
    puts("PASS: production discovery drains each poll, cancels during sleep and skips pre-cancelled work");
} }
'''
poll_fixture = r'''
#import <Foundation/Foundation.h>
#include <assert.h>
static int liveTokens;
@interface Token : NSObject @end
@implementation Token
- (id)init { self = [super init]; if (self) liveTokens++; return self; }
- (void)dealloc { liveTokens--; [super dealloc]; }
@end
@interface TemporaryHost : NSObject @end
@implementation TemporaryHost @end
@interface DiscoveryWorker : NSOperation {
@public
    int rounds;
    BOOL stopDuringPoll;
    dispatch_semaphore_t firstPoll;
}
- (id)initWithHost:(TemporaryHost *)host uniqueId:(NSString *)uniqueId;
- (void)discoverHost;
@end
'''

shutdown = usb[usb.index("- (void)stop {", usb.index("- (void)startForwardingForDevice:")):
               usb.rindex("@end")]
usb_fixture = r'''
#import <Foundation/Foundation.h>
#include <assert.h>
enum { MLRemoteUSBForwardingStateIdle, MLRemoteUSBForwardingStateStopping };
@interface Tunnel : NSObject
@property int stops;
- (void)stop;
@end
@implementation Tunnel
- (void)stop { self.stops++; }
@end
@interface MLRemoteUSBForwardingSession : NSObject
@property dispatch_queue_t workerQueue;
@property int state;
@property int exporterStops;
@property Tunnel *tunnel;
- (void)stop;
- (void)stopExporterLocked;
@end
@implementation MLRemoteUSBForwardingSession
- (void)stopExporterLocked { self.exporterStops++; }
'''
usb_checks = r'''
@end
int main(void) { @autoreleasepool {
    MLRemoteUSBForwardingSession *session = [MLRemoteUSBForwardingSession new];
    session.workerQueue = dispatch_queue_create("test.usb", DISPATCH_QUEUE_SERIAL);
    Tunnel *tunnel = [Tunnel new]; session.tunnel = tunnel;
    dispatch_semaphore_t busy = dispatch_semaphore_create(0);
    dispatch_semaphore_t entered = dispatch_semaphore_create(0);
    dispatch_semaphore_t done = dispatch_semaphore_create(0);
    dispatch_async(session.workerQueue, ^{
        dispatch_semaphore_signal(entered);
        dispatch_semaphore_wait(busy, DISPATCH_TIME_FOREVER);
    });
    dispatch_semaphore_wait(entered, DISPATCH_TIME_FOREVER);
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, NSEC_PER_SEC / 3), dispatch_get_global_queue(0, 0), ^{
        dispatch_semaphore_signal(busy);
    });
    CFAbsoluteTime start = CFAbsoluteTimeGetCurrent();
    [session stop];
    assert(CFAbsoluteTimeGetCurrent() - start < 0.15 && "USB worker blocked the UI caller");
    dispatch_async(session.workerQueue, ^{
        assert(session.state == MLRemoteUSBForwardingStateIdle);
        assert(session.tunnel == nil && tunnel.stops == 1 && session.exporterStops == 1);
        // Shutdown is also legal from a callback running on the worker queue.
        [session stop];
        dispatch_async(session.workerQueue, ^{ dispatch_semaphore_signal(done); });
    });
    assert(dispatch_semaphore_wait(done, dispatch_time(DISPATCH_TIME_NOW, 2 * NSEC_PER_SEC)) == 0);
    assert(session.exporterStops == 2);
    puts("PASS: production USB stop returns while worker is busy, preserves order and allows worker callbacks");
} }
'''

with tempfile.TemporaryDirectory(prefix="moonlight-resource-test-") as tmp:
    for name, source, arc in (
        ("discovery", poll_fixture + polling, False),
        ("usb", usb_fixture + shutdown + usb_checks, True),
    ):
        path = Path(tmp) / (name + ".m")
        path.write_text(source)
        binary = Path(tmp) / name
        subprocess.run(["clang", "-fobjc-arc" if arc else "-fno-objc-arc", "-fblocks",
                        "-framework", "Foundation", str(path), "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True, timeout=8)
