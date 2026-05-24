import os

content = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.alta.viralscout</string>
    <key>ProgramArguments</key>
    <array>
        <string>/opt/homebrew/bin/python3</string>
        <string>/Users/glebnazemnov/Downloads/alta_viral_scanner/main.py</string>
    </array>
    <key>WorkingDirectory</key><string>/Users/glebnazemnov/Downloads/alta_viral_scanner</string>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key><string>/Users/glebnazemnov/Downloads/alta_viral_scanner/alta_scanner.log</string>
    <key>StandardErrorPath</key><string>/Users/glebnazemnov/Downloads/alta_viral_scanner/alta_scanner.log</string>
</dict>
</plist>"""

path = os.path.expanduser("~/Library/LaunchAgents/com.alta.viralscout.plist")
os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, "w") as f:
    f.write(content)
print(f"Создан: {path}")
