#!/bin/bash

# Bluetooth Speaker Connection and Test Script
# MAC Address: 50:5E:5C:8F:74:59

MAC="50:5E:5C:8F:74:59"
SINK="bluez_sink.50_5E_5C_8F_74_59.a2dp_sink"
SOURCE="bluez_sink.50_5E_5C_8F_74_59.a2dp_sink.monitor"

echo "=== Bluetooth Speaker Connection & Test Script ==="
echo "Device MAC: $MAC"
echo

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Function to wait for user input
wait_for_user() {
    echo "Press Enter to continue..."
    read -r
}

# Check prerequisites
echo "1. Checking prerequisites..."
if ! command_exists bluetoothctl; then
    echo "❌ bluetoothctl not found. Please install bluez."
    exit 1
fi

if ! command_exists pactl; then
    echo "❌ PulseAudio not found. Installing..."
    sudo apt update
    sudo apt install -y pulseaudio pulseaudio-module-bluetooth
fi

echo "✅ Prerequisites OK"
echo

# Start Bluetooth and PulseAudio services
echo "2. Starting services..."
sudo systemctl start bluetooth
pulseaudio --start 2>/dev/null
echo "✅ Services started"
echo

# Connect to Bluetooth device
echo "3. Connecting to Bluetooth speaker..."
echo "Make sure your speaker is in pairing mode if not already paired."
wait_for_user

bluetoothctl << EOF
power on
agent on
default-agent
connect $MAC
exit
EOF

# Check connection status
echo
echo "4. Checking connection status..."
CONNECTION_STATUS=$(bluetoothctl info $MAC | grep "Connected: yes")
if [ -n "$CONNECTION_STATUS" ]; then
    echo "✅ Device connected successfully"
else
    echo "❌ Device connection failed"
    echo "Attempting to pair and connect..."
    bluetoothctl << EOF
power on
scan on
EOF
    sleep 3
    bluetoothctl << EOF
scan off
pair $MAC
trust $MAC
connect $MAC
exit
EOF
fi
echo

# Wait for audio services to recognize the device
echo "5. Waiting for audio services to detect device..."
sleep 5

# List available sinks and sources
echo "6. Available audio devices:"
echo "--- Audio Outputs (Sinks) ---"
pactl list short sinks
echo
echo "--- Audio Inputs (Sources) ---"
pactl list short sources
echo

# Set Bluetooth speaker as default output
echo "7. Setting Bluetooth speaker as default output..."
if pactl list short sinks | grep -q "$SINK"; then
    pactl set-default-sink "$SINK"
    echo "✅ Default audio output set to Bluetooth speaker"
else
    echo "❌ Bluetooth sink not found. Available sinks:"
    pactl list short sinks
    echo
fi

# Set monitor as default input (for apps that need input)
echo "8. Setting monitor as default input..."
if pactl list short sources | grep -q "$SOURCE"; then
    pactl set-default-source "$SOURCE"
    echo "✅ Default audio input set to monitor"
else
    echo "⚠️  Monitor source not found. Available sources:"
    pactl list short sources
    echo
fi

# Test audio output
echo "9. Testing audio output..."
echo "You should hear test sounds from your Bluetooth speaker."
wait_for_user

echo "Playing test sound (2 seconds)..."
speaker-test -t wav -c 2 -l 1 2>/dev/null &
TEST_PID=$!
sleep 2
kill $TEST_PID 2>/dev/null
echo "✅ Audio output test complete"
echo

# Test microphone input (if available)
echo "10. Testing microphone input..."
MIC_SOURCE=$(pactl list short sources | grep "bluez.*input" | head -n1 | awk '{print $2}')

if [ -n "$MIC_SOURCE" ]; then
    echo "Found microphone source: $MIC_SOURCE"
    echo "Recording 3 seconds of audio from microphone..."
    wait_for_user
    
    arecord -f cd -t wav -d 3 -D pulse mic_test.wav 2>/dev/null
    echo "Playing back recorded audio..."
    aplay mic_test.wav 2>/dev/null
    rm -f mic_test.wav
    echo "✅ Microphone test complete"
else
    echo "⚠️  No Bluetooth microphone detected"
    echo "This is normal for speakers that only support A2DP profile"
fi
echo

# Display current audio configuration
echo "11. Current audio configuration:"
echo "--- Default Sink ---"
pactl info | grep "Default Sink"
echo "--- Default Source ---"
pactl info | grep "Default Source"
echo

# Volume controls
echo "12. Volume controls:"
echo "Current speaker volume:"
pactl list sinks | grep -A 15 "$SINK" | grep "Volume:" | head -n1
echo
echo "To adjust volume later, use:"
echo "  pactl set-sink-volume $SINK 50%   # Set to 50%"
echo "  pactl set-sink-volume $SINK +10%  # Increase by 10%"
echo "  pactl set-sink-volume $SINK -10%  # Decrease by 10%"
echo

# Connection management
echo "13. Connection management:"
echo "To disconnect: bluetoothctl disconnect $MAC"
echo "To reconnect:  bluetoothctl connect $MAC"
echo "To remove device: bluetoothctl remove $MAC"
echo

# Troubleshooting info
echo "14. Troubleshooting:"
echo "If audio stops working:"
echo "  pulseaudio -k && pulseaudio --start"
echo "  sudo systemctl restart bluetooth"
echo
echo "If connection drops:"
echo "  bluetoothctl connect $MAC"
echo

echo "=== Script completed successfully! ==="
echo "Your Bluetooth speaker should now be connected and working."
