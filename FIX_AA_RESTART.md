# Fix for Android Auto Restart Issue

## Problem Description

When using the GUI restart function for Android Auto service:
- System restart works correctly
- Android Auto service restart does NOT work properly
- OpenAuto (autoapp) starts but hangs
- Phone keeps trying to connect but cannot establish connection
- Only a full M910Q restart helps

## Root Cause Analysis

The issue was in the `restart()` method of `OpenAutoController` in `src/multimedia/openauto.py`.

When a manual restart was requested:

1. **Insufficient cleanup**: The `stop()` method only sent SIGTERM to autoapp and waited up to 5 seconds, but:
   - The Bluetooth btservice (internal to autoapp) might not have released its sockets/ports
   - The Xvfb display might not have been fully cleaned up
   - Orphaned processes might still be running

2. **Port conflict**: autoapp's internal btservice uses port 5000 for Bluetooth communication. If the old instance doesn't release it quickly enough, the new instance cannot bind to it, causing it to hang.

3. **Bluetooth state**: The Bluetooth adapter might be in a bad state from the previous connection attempt, preventing the new autoapp instance from properly initializing its btservice.

4. **Insufficient wait time**: The original code only waited 2 seconds after `stop()` before calling `start()`. This was not enough for all resources to be released.

## Solution Implemented

The fix enhances the `restart()` method and related cleanup functions:

### 1. Enhanced `stop()` method
- Added additional wait after killing the process to ensure cleanup
- Ensures the process is fully terminated before returning

### 2. Enhanced `restart()` method
- Now explicitly calls `_kill_stale()` to clean up any remaining processes
- Increased wait time to 3 seconds (from 2) for resource release
- Added Bluetooth adapter reset via `_reset_bt_adapter()`
- Better logging to track the restart process

### 3. Enhanced `_kill_stale()` method
- Now kills both autoapp AND btservice processes
- Uses SIGTERM first, then SIGKILL for any remaining processes
- Added cleanup of processes using port 5000 (btservice default port)
- Added new helper method `_kill_processes_on_port()` to handle port cleanup

### 4. New `_reset_bt_adapter()` method
- Resets the Bluetooth adapter using both hciconfig and bluetoothctl
- Power cycles the adapter to ensure clean state
- Handles errors gracefully if tools are not available

### 5. New `_kill_processes_on_port()` method
- Uses fuser or ss to find processes using specific ports
- Kills any processes found on the specified port
- Falls back to alternative methods if fuser is not available

## Files Modified

- `src/multimedia/openauto.py`: Main fix implementation

## Testing Recommendations

After applying this fix:

1. Test manual restart from GUI
2. Verify that:
   - OpenAuto stops cleanly
   - All related processes are killed
   - Bluetooth adapter is reset
   - New OpenAuto instance starts successfully
   - Phone can reconnect without issues

3. Check logs for:
   - `[AA] Manual restart requested`
   - `[AA] Waiting for resources to be released before restart...`
   - `[AA] Resetting Bluetooth adapter <MAC>`
   - `[AA] Bluetooth adapter reset complete`
   - OpenAuto launched (PID X)

## Technical Details

### Port Cleanup
The btservice in autoapp uses port 5000 for Bluetooth bootstrap. The fix explicitly cleans up this port to prevent conflicts.

### Bluetooth Reset
The fix resets the Bluetooth adapter by:
1. Bringing the adapter down (hciconfig <mac> down)
2. Waiting 1 second
3. Bringing the adapter up (hciconfig <mac> up)
4. Also power cycling via bluetoothctl as fallback

### Process Cleanup
The fix ensures all related processes are killed:
1. autoapp processes (SIGTERM then SIGKILL)
2. btservice processes (SIGTERM then SIGKILL)
3. Any processes using port 5000

### Wait Times
- stop(): 2 seconds after killing process
- _kill_stale(): 2 seconds after SIGTERM, 1 second after cleanup
- restart(): 3 seconds for resource release
- Total: ~7-8 seconds for full cleanup and restart

This should be sufficient for all resources to be released in a test environment.

## Notes

In production, if the issue persists, consider:
1. Increasing wait times further
2. Adding explicit cleanup of /tmp/.X11-unix/X99 socket files
3. Checking for and killing any orphaned Xvfb processes
4. Verifying that the Bluetooth adapter is properly supported by hciconfig
