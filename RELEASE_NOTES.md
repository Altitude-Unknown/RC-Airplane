All configurator tabs now have vertical and horizontal scrollbars so controls
remain reachable in smaller windows and with enlarged display text. Models,
Instructor / Student, and Firmware Update share the same scrolling behavior.

- Mouse wheel scrolls vertically; Shift+wheel scrolls horizontally.
- Keyboard navigation brings focused controls into view.
- The serial connection row also scrolls in narrow windows.
- Startup window dimensions adapt to the screen, with a smaller minimum size.

Install the updated configurator app. No transmitter or receiver firmware
update is needed for this change. Firmware sources are unchanged from
2026.09.22; firmware assets remain included for the existing updater.

Validation: 20 tests passed, including live macOS Tk layout checks down to
480×320 and enlarged-text/scaling checks. The Windows package is built by CI;
interactive Windows display-scaling validation remains outstanding.

Includes macOS ARM64, Windows x64, and Raspberry Pi ARM64 apps, plus the
existing firmware and SHA-256 manifest. The previous receiver smoothness
improvement is retained. Optional CH5/CH6 button assignments still await
dedicated hardware validation; see BUTTON_CHANNELS.md.
