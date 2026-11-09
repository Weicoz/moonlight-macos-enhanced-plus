"""Execute production automatic switching with deterministic latency and time."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
s = (root / "Limelight/Network/DiscoveryWorker.m").read_text()
a = s.index("    // Auto-switch to a significantly lower-latency address")
b = s.index("    // Persist state changes", a)
switch = s[a:b]
fixture = r'''
#import <Foundation/Foundation.h>
#include <assert.h>
#define LOG_I 1
#define Log(...) ((void)0)
static double testNow = 100;
#define CFAbsoluteTimeGetCurrent() testNow
static const double AUTO_SWITCH_PING_IMPROVEMENT_MS = 20;
static const double AUTO_SWITCH_COOLDOWN_SEC = 30;
static const NSUInteger AUTO_SWITCH_CONFIRMATIONS = 3;
static NSMutableDictionary *gAutoSwitchCooldownByHost;
static NSObject *gAutoSwitchCooldownLock;
static dispatch_once_t gAutoSwitchCooldownOnceToken;
@interface Host : NSObject
@property NSString *uuid, *name, *activeAddress;
@end
@implementation Host @end
@interface Worker : NSObject {
    Host *_host;
    NSString *_preferredAddressCandidate;
    NSUInteger _preferredAddressObservations;
}
- (id)initWithHost:(Host *)host;
- (void)poll:(NSString *)bestAddress latencies:(NSDictionary *)latencies automatic:(BOOL)autoConnectionMode
     received:(BOOL)receivedResponse streaming:(BOOL)isStreamingThisHost;
@end
@implementation Worker
- (id)initWithHost:(Host *)host { self = [super init]; _host = host; return self; }
- (void)poll:(NSString *)bestAddress latencies:(NSDictionary *)latencies automatic:(BOOL)autoConnectionMode
     received:(BOOL)receivedResponse streaming:(BOOL)isStreamingThisHost {
'''
checks = r'''
}
@end
int main(void) { @autoreleasepool {
    __block int notices = 0;
    id observer = [[NSNotificationCenter defaultCenter] addObserverForName:@"HostAutoAddressSwitched"
        object:nil queue:nil usingBlock:^(NSNotification *note) { notices++; }];
    Host *host = [Host new]; host.uuid = @"test-host"; host.name = @"test"; host.activeAddress = @"ip";
    Worker *w = [[Worker alloc] initWithHost:host];
    NSDictionary *fast = @{ @"ip": @27, @"dns": @4, @"other": @3 };
    [w poll:@"dns" latencies:fast automatic:YES received:YES streaming:NO];
    assert([host.activeAddress isEqual:@"ip"] && "A single fast sample must not switch routes");
    [w poll:@"other" latencies:fast automatic:YES received:YES streaming:NO];
    [w poll:@"dns" latencies:fast automatic:YES received:YES streaming:NO];
    assert([host.activeAddress isEqual:@"ip"]);
    [w poll:@"dns" latencies:fast automatic:YES received:YES streaming:NO];
    assert([host.activeAddress isEqual:@"ip"]);
    [w poll:@"dns" latencies:fast automatic:YES received:YES streaming:NO];
    assert([host.activeAddress isEqual:@"dns"]);
    // A stable reverse candidate cannot bypass the per-host cooldown.
    NSDictionary *reverse = @{ @"ip": @3, @"dns": @30 };
    for (int i = 0; i < 3; i++) [w poll:@"ip" latencies:reverse automatic:YES received:YES streaming:NO];
    assert([host.activeAddress isEqual:@"dns"]);
    testNow += 31;
    [w poll:@"ip" latencies:reverse automatic:YES received:YES streaming:NO];
    assert([host.activeAddress isEqual:@"ip"]);
    // Gaps, manual selection, streaming and small improvements reset confirmation.
    for (int mode = 0; mode < 4; mode++) {
        testNow += 31;
        [w poll:@"dns" latencies:fast automatic:YES received:YES streaming:NO];
        [w poll:@"dns" latencies:fast automatic:mode != 0 received:mode != 1 streaming:mode == 2];
        if (mode == 3) {
            [w poll:@"dns" latencies:@{@"ip": @5, @"dns": @4} automatic:YES received:YES streaming:NO];
        }
        [w poll:@"dns" latencies:fast automatic:YES received:YES streaming:NO];
        assert([host.activeAddress isEqual:@"ip"]);
        [w poll:nil latencies:@{} automatic:YES received:NO streaming:NO];
    }
    [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.02]];
    assert(notices == 0 && "Background route optimization must not enqueue modal notices");
    [[NSNotificationCenter defaultCenter] removeObserver:observer];
    puts("PASS: production auto-switch confirms three stable samples, honors cooldown and resets on gaps/manual/streaming/jitter");
    puts("PASS: production route changes enqueue no modal address-switch notices");
} }
'''
with tempfile.TemporaryDirectory(prefix="moonlight-stability-test-") as tmp:
    path = Path(tmp) / "test.m"
    path.write_text(fixture + switch + checks)
    binary = Path(tmp) / "test"
    subprocess.run(["clang", "-fobjc-arc", "-fblocks", "-framework", "Foundation",
                    str(path), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True, timeout=5)
