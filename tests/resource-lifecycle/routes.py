"""Verify production route selection preserves working routes and manual choices."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / "Limelight/Network/DiscoveryWorker.m").read_text()
start = source.index("        if (autoConnectionMode && !isStreamingThisHost) {")
end = source.index('        Log(LOG_D, @"Received response from:', start)
selection = source[start:end]
fixture = r'''
#import <Foundation/Foundation.h>
#include <assert.h>
@interface Host : NSObject
@property NSString *activeAddress;
@end
@implementation Host @end
static NSString *selectRoute(NSString *active, NSDictionary *states, NSString *firstOnlineAddress,
                             NSString *bestAddress, BOOL autoConnectionMode, BOOL isStreamingThisHost,
                             NSString *selectedConnectionMethod) {
    Host *_host = [Host new]; _host.activeAddress = active;
'''
checks = r'''
    return _host.activeAddress;
}
int main(void) { @autoreleasepool {
    NSDictionary *both = @{ @"working": @1, @"first": @1, @"fastest": @1 };
    assert([selectRoute(@"working", both, @"first", @"fastest", YES, NO, nil) isEqual:@"working"]);
    assert([selectRoute(@"offline", both, @"first", @"fastest", YES, NO, nil) isEqual:@"fastest"]);
    assert([selectRoute(nil, both, @"first", @"fastest", YES, NO, nil) isEqual:@"fastest"]);
    assert([selectRoute(@"offline", both, @"first", nil, YES, NO, nil) isEqual:@"first"]);
    assert([selectRoute(@"offline", @{}, nil, nil, YES, NO, nil) isEqual:@"offline"]);
    assert([selectRoute(@"working", both, @"first", @"fastest", NO, NO, @"manual") isEqual:@"manual"]);
    assert([selectRoute(@"working", both, @"first", @"fastest", YES, YES, nil) isEqual:@"working"]);
    assert([selectRoute(@"working", both, @"first", @"fastest", NO, YES, @"manual") isEqual:@"working"]);
    puts("PASS: production discovery preserves a working route, recovers offline routes and respects manual/streaming choices");
} }
'''
with tempfile.TemporaryDirectory(prefix="moonlight-route-test-") as tmp:
    path = Path(tmp) / "test.m"
    path.write_text(fixture + selection + checks)
    binary = Path(tmp) / "test"
    subprocess.run(["clang", "-fobjc-arc", "-fblocks", "-framework", "Foundation",
                    str(path), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True, timeout=5)
