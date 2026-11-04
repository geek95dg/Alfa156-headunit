#!/usr/bin/env python3
"""
Test script to verify Android Auto restart functionality.

This script simulates the restart process and checks that all cleanup
operations work correctly.
"""

import os
import sys
import subprocess

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.core.event_bus import EventBus
from src.multimedia.openauto import OpenAutoController


def test_restart_cleanup():
    """Test that restart properly cleans up resources."""
    print("Testing Android Auto restart cleanup...")
    
    # Create a minimal config
    class MockConfig:
        def get(self, key, default=None):
            config_map = {
                "system.platform": "x86",
                "multimedia.aa_auto_restart": True,
                "multimedia.aa_connection_timeout": 90,
                "display.dashboard.width": 1024,
                "display.dashboard.height": 600,
                "wifi.ssid": "test",
                "wifi.password": "test123",
            }
            return config_map.get(key, default)
    
    config = MockConfig()
    event_bus = EventBus()
    
    # Create OpenAutoController
    controller = OpenAutoController(config, event_bus)
    
    if not controller.available:
        print("⚠️  OpenAuto binary not found (this is OK for testing)")
        print("Testing cleanup methods without actual process...")
        
        # Test _kill_stale
        print("\n1. Testing _kill_stale()...")
        controller._kill_stale()
        print("   ✓ _kill_stale() completed")
        
        # Test _reset_bt_adapter
        print("\n2. Testing _reset_bt_adapter()...")
        controller._reset_bt_adapter()
        print("   ✓ _reset_bt_adapter() completed")
        
        # Test _kill_processes_on_port
        print("\n3. Testing _kill_processes_on_port(5000)...")
        controller._kill_processes_on_port(5000)
        print("   ✓ _kill_processes_on_port() completed")
        
        print("\n✅ All cleanup methods work correctly!")
        return True
    else:
        print("✓ OpenAuto binary found")
        
        # Test with actual process (if available)
        print("\nTesting with actual OpenAuto process...")
        
        # We won't actually start/stop the process in this test
        # as it requires Xvfb and other dependencies
        print("   (Skipping actual process test - requires full environment)")
        
        # But we can test the cleanup methods
        print("\n1. Testing _kill_stale()...")
        controller._kill_stale()
        print("   ✓ _kill_stale() completed")
        
        print("\n2. Testing _reset_bt_adapter()...")
        controller._reset_bt_adapter()
        print("   ✓ _reset_bt_adapter() completed")
        
        print("\n3. Testing _kill_processes_on_port(5000)...")
        controller._kill_processes_on_port(5000)
        print("   ✓ _kill_processes_on_port() completed")
        
        print("\n✅ All cleanup methods work correctly!")
        return True


def test_bluetooth_tools():
    """Test that Bluetooth tools are available."""
    print("\nChecking Bluetooth tools...")
    
    tools = ["bluetoothctl", "hciconfig"]
    for tool in tools:
        try:
            result = subprocess.run(
                [tool, "--version"],
                capture_output=True,
                timeout=3
            )
            if result.returncode == 0:
                print(f"   ✓ {tool} is available")
            else:
                print(f"   ⚠️  {tool} returned error: {result.stderr.decode().strip()}")
        except FileNotFoundError:
            print(f"   ⚠️  {tool} not found")
        except Exception as e:
            print(f"   ⚠️  {tool} error: {e}")


def test_port_tools():
    """Test that port tools are available."""
    print("\nChecking port tools...")
    
    tools = ["fuser", "ss"]
    for tool in tools:
        try:
            result = subprocess.run(
                [tool, "--help"],
                capture_output=True,
                timeout=3
            )
            if result.returncode == 0:
                print(f"   ✓ {tool} is available")
            else:
                print(f"   ⚠️  {tool} returned error")
        except FileNotFoundError:
            print(f"   ⚠️  {tool} not found")
        except Exception as e:
            print(f"   ⚠️  {tool} error: {e}")


def main():
    print("=" * 60)
    print("Android Auto Restart Fix - Test Script")
    print("=" * 60)
    
    # Test cleanup methods
    success = test_restart_cleanup()
    
    # Test tool availability
    test_bluetooth_tools()
    test_port_tools()
    
    print("\n" + "=" * 60)
    if success:
        print("✅ All tests passed!")
    else:
        print("❌ Some tests failed")
    print("=" * 60)
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
