// Trackpad pinch for Tk on macOS (ASCEND Flight Control).
//
// Tk 8.6 ignores magnify (pinch) gestures. This watches for them with an
// NSEvent local monitor and turns each one into a Tk virtual event,
//     <<AscendPinch>> -data <magnification>
// queued on the target widget. Python handles it like any other Tk event, so
// no Python code runs inside the AppKit callback (that would fight Tkinter
// over the interpreter lock and crash).
//
// Build: tools/build_mac_pinch.sh  (universal arm64 + x86_64 dylib)

#import <AppKit/AppKit.h>
#include <dlfcn.h>
#include <stdio.h>
#include <string.h>

typedef int (*TclEvalEx)(void *interp, const char *script, int length, int flags);
#define TCL_EVAL_GLOBAL 0x020000

static id g_monitor = nil;
static void *g_interp = NULL;
static TclEvalEx g_eval = NULL;
static char g_widget[256];

int ascend_pinch_install(void *interp, const char *widget_path) {
    if (g_monitor != nil) return 1;
    if (interp == NULL || widget_path == NULL || strlen(widget_path) >= sizeof(g_widget)) return 0;
    // Tcl is already loaded by Tkinter; find it at run time instead of linking against it.
    g_eval = (TclEvalEx)dlsym(RTLD_DEFAULT, "Tcl_EvalEx");
    if (g_eval == NULL) return 0;
    g_interp = interp;
    strncpy(g_widget, widget_path, sizeof(g_widget) - 1);

    g_monitor = [NSEvent addLocalMonitorForEventsMatchingMask:NSEventMaskMagnify
                                                      handler:^NSEvent *(NSEvent *event) {
        char script[512];
        snprintf(script, sizeof(script),
                 "if {[winfo exists %s]} {event generate %s <<AscendPinch>> -data %.5f -when tail}",
                 g_widget, g_widget, (double)event.magnification);
        g_eval(g_interp, script, -1, TCL_EVAL_GLOBAL);
        return event;
    }];
    return g_monitor != nil;
}

void ascend_pinch_remove(void) {
    if (g_monitor != nil) {
        [NSEvent removeMonitor:g_monitor];
        g_monitor = nil;
    }
    g_interp = NULL;
}
