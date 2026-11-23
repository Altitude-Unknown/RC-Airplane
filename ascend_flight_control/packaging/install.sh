#!/bin/sh
# Install ASCEND Flight Control on a Raspberry Pi (64-bit Raspberry Pi OS) for this user:
# copies the app to ~/.local/bin and adds it to the Programming menu.
set -e
cd "$(dirname "$0")"
mkdir -p "$HOME/.local/bin" "$HOME/.local/share/applications" "$HOME/.local/share/icons"
cp "ASCEND Flight Control" "$HOME/.local/bin/ascend-flight-control"
chmod +x "$HOME/.local/bin/ascend-flight-control"
cp ascend-flight-control.png "$HOME/.local/share/icons/ascend-flight-control.png"
cat > "$HOME/.local/share/applications/ascend-flight-control.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=ASCEND Flight Control
Comment=Ground station for the ASCEND flight controller
Exec=$HOME/.local/bin/ascend-flight-control
Icon=$HOME/.local/share/icons/ascend-flight-control.png
Categories=Development;Education;
Terminal=false
DESKTOP
echo "Installed. Open it from the menu (Programming), or run: ~/.local/bin/ascend-flight-control"
if ! id -nG | grep -qw dialout; then
    echo "To use USB serial ports, add yourself to the dialout group, then log out and back in:"
    echo "    sudo usermod -aG dialout $USER"
fi
