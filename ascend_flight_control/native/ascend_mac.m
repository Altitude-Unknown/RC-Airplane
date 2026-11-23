// macOS helpers for ASCEND Flight Control: trackpad pinch and the computer's location.
//
// Tk 8.6 ignores magnify (pinch) gestures, and Python cannot safely receive
// AppKit or Core Location callbacks inside Tkinter's event loop (Tkinter
// releases the interpreter lock while it waits for events; a Python callback
// arriving then crashes the process). So this library handles both natively
// and hands the results to Tk as ordinary virtual events, which Python then
// receives through Tkinter's normal event path:
//
//     <<AscendPinch>>     -data <magnification>
//     <<AscendLocation>>  -data "ok <lat> <lon> <accuracy_m>" | "denied" | "off" | "error <code>"
//
// Location needs NSLocationUsageDescription in the app's Info.plist and, for
// the signed app (hardened runtime), the com.apple.security.personal-information.location
// entitlement. Run from source, Python.app has neither, so macOS reports "denied".
//
// Build: tools/build_mac_native.sh  (universal arm64 + x86_64 dylib)

#import <AppKit/AppKit.h>
#import <CoreLocation/CoreLocation.h>
#include <dlfcn.h>
#include <stdio.h>
#include <string.h>

typedef int (*TclEvalEx)(void *interp, const char *script, int length, int flags);
#define TCL_EVAL_GLOBAL 0x020000

static void *g_interp = NULL;
static TclEvalEx g_eval = NULL;

static int ensure_tcl(void *interp) {
    if (interp == NULL) return 0;
    if (g_eval == NULL) {
        // Tcl is already loaded by Tkinter; find it at run time instead of linking against it.
        g_eval = (TclEvalEx)dlsym(RTLD_DEFAULT, "Tcl_EvalEx");
    }
    g_interp = interp;
    return g_eval != NULL;
}

static void post_event(const char *widget, const char *event, const char *data) {
    if (g_eval == NULL || g_interp == NULL) return;
    char script[640];
    snprintf(script, sizeof(script),
             "if {[winfo exists %s]} {event generate %s %s -data {%s} -when tail}",
             widget, widget, event, data);
    g_eval(g_interp, script, -1, TCL_EVAL_GLOBAL);
}

// --------------------------------------------------------------------------
// Pinch
// --------------------------------------------------------------------------

static id g_pinch_monitor = nil;
static char g_pinch_widget[256];

int ascend_pinch_install(void *interp, const char *widget_path) {
    if (g_pinch_monitor != nil) return 1;
    if (widget_path == NULL || strlen(widget_path) >= sizeof(g_pinch_widget) || !ensure_tcl(interp)) return 0;
    strncpy(g_pinch_widget, widget_path, sizeof(g_pinch_widget) - 1);
    g_pinch_monitor = [NSEvent addLocalMonitorForEventsMatchingMask:NSEventMaskMagnify
                                                            handler:^NSEvent *(NSEvent *event) {
        char data[32];
        snprintf(data, sizeof(data), "%.5f", (double)event.magnification);
        post_event(g_pinch_widget, "<<AscendPinch>>", data);
        return event;
    }];
    return g_pinch_monitor != nil;
}

void ascend_pinch_remove(void) {
    if (g_pinch_monitor != nil) {
        [NSEvent removeMonitor:g_pinch_monitor];
        g_pinch_monitor = nil;
    }
}

// --------------------------------------------------------------------------
// Location
// --------------------------------------------------------------------------

static char g_location_widget[256];

@interface AscendLocation : NSObject <CLLocationManagerDelegate>
@property(strong) CLLocationManager *manager;
@property BOOL waiting;
@end

@implementation AscendLocation

- (void)finish:(const char *)data {
    if (!self.waiting) return;
    self.waiting = NO;
    post_event(g_location_widget, "<<AscendLocation>>", data);
}

- (void)askForLocation {
    CLAuthorizationStatus status = self.manager.authorizationStatus;
    if (status == kCLAuthorizationStatusNotDetermined) {
        [self.manager requestWhenInUseAuthorization];  // answer arrives in locationManagerDidChangeAuthorization
    } else if (status == kCLAuthorizationStatusDenied || status == kCLAuthorizationStatusRestricted) {
        [self finish:"denied"];
    } else {
        [self.manager requestLocation];
    }
}

- (void)locationManagerDidChangeAuthorization:(CLLocationManager *)manager {
    if (self.waiting && manager.authorizationStatus != kCLAuthorizationStatusNotDetermined) {
        [self askForLocation];
    }
}

- (void)locationManager:(CLLocationManager *)manager didUpdateLocations:(NSArray<CLLocation *> *)locations {
    CLLocation *loc = locations.lastObject;
    if (loc == nil) return;
    char data[96];
    snprintf(data, sizeof(data), "ok %.7f %.7f %.0f", loc.coordinate.latitude, loc.coordinate.longitude,
             loc.horizontalAccuracy);
    [self finish:data];
}

- (void)locationManager:(CLLocationManager *)manager didFailWithError:(NSError *)error {
    if (error.code == kCLErrorLocationUnknown) return;  // Core Location keeps trying
    char data[48];
    snprintf(data, sizeof(data), error.code == kCLErrorDenied ? "denied" : "error %ld", (long)error.code);
    [self finish:data];
}

@end

static AscendLocation *g_location = nil;

// Ask macOS for the computer's location once; the answer arrives as <<AscendLocation>>.
int ascend_location_request(void *interp, const char *widget_path) {
    if (widget_path == NULL || strlen(widget_path) >= sizeof(g_location_widget) || !ensure_tcl(interp)) return 0;
    strncpy(g_location_widget, widget_path, sizeof(g_location_widget) - 1);
    if (g_location == nil) {
        g_location = [AscendLocation new];
        g_location.manager = [CLLocationManager new];
        g_location.manager.delegate = g_location;
        g_location.manager.desiredAccuracy = kCLLocationAccuracyHundredMeters;
    }
    g_location.waiting = YES;
    if (![CLLocationManager locationServicesEnabled]) {
        [g_location finish:"off"];
        return 1;
    }
    [g_location askForLocation];
    return 1;
}
