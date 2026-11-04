' Screensaver entry point. Roku prohibits Main() and RunUserInterface() in a
' screensaver, so this is the only one.
sub RunScreenSaver()
    screen = CreateObject("roSGScreen")
    port = CreateObject("roMessagePort")
    screen.setMessagePort(port)
    screen.CreateScene("AquariumScene")
    screen.show()

    ' Required for certification (since October 1, 2026): subscribe to memory
    ' warnings (they arrive at 80/85/90/95% of the app's memory limit) and use
    ' the memory limit and availability APIs.
    deviceInfo = CreateObject("roDeviceInfo")
    ' GetChannelAvailableMemory needs Roku OS 12.5 and GetChannelMemoryLimit
    ' 13.0; calling a missing method would crash, so older devices skip them.
    hasMemoryApis = Val(deviceInfo.GetOSVersion().major) >= 13
    memoryMonitor = CreateObject("roAppMemoryMonitor")
    if memoryMonitor <> invalid
        memoryMonitor.setMessagePort(port)
        enabled = memoryMonitor.EnableMemoryWarningEvent(true)
        if not enabled
            ' Older devices: fall back to the general low-memory event.
            deviceInfo.setMessagePort(port)
            deviceInfo.EnableLowGeneralMemoryEvent(true)
        end if
        if hasMemoryApis
            print "AquariumTV: memory limits "; FormatJson(memoryMonitor.GetChannelMemoryLimit())
        end if
    end if

    while true
        msg = wait(0, port)
        msgType = type(msg)
        if msgType = "roSGScreenEvent"
            if msg.isScreenClosed() then return
        else if msgType = "roAppMemoryNotificationEvent"
            ' The scene uses a fixed set of textures and never grows, so there is
            ' nothing to release; log it for the debug console.
            print "AquariumTV: memory at "; memoryMonitor.GetMemoryLimitPercent(); "% of limit"
            if hasMemoryApis
                print "AquariumTV: "; memoryMonitor.GetChannelAvailableMemory(); " KB available"
            end if
        else if msgType = "roDeviceInfoEvent"
            print "AquariumTV: low general memory event"
        end if
    end while
end sub
