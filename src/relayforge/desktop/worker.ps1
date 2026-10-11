# RelayForge desktop worker. Reads one JSON request from stdin and writes one JSON line.
# Closed operation set; it never evaluates code received in the request.
$ErrorActionPreference = 'Stop'

function Write-Result($value) {
    [Console]::Out.WriteLine(($value | ConvertTo-Json -Compress -Depth 12))
}

function Fail([string]$code) {
    Write-Result @{ ok = $false; error = $code }
    exit 0
}

if ([IntPtr]::Size -ne 8) { Fail 'unsupported_architecture' }

Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes, System.Drawing
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;
public static class RfNative {
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll")] public static extern bool IsWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern IntPtr OpenInputDesktop(uint flags, bool inherit, uint access);
    [DllImport("user32.dll")] public static extern bool CloseDesktop(IntPtr h);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern bool GetUserObjectInformation(IntPtr h, int index, StringBuilder info, int len, out int needed);
    [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint flags);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint msg, IntPtr w, IntPtr l);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern IntPtr SendMessage(IntPtr h, uint msg, IntPtr w, string l);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
    [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
    [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr h);
    [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint from, uint to, bool attach);
    [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
    [DllImport("user32.dll")] public static extern IntPtr GetMenu(IntPtr h);
    [DllImport("user32.dll")] public static extern int GetMenuItemCount(IntPtr m);
    [DllImport("user32.dll")] public static extern IntPtr GetSubMenu(IntPtr m, int pos);
    [DllImport("user32.dll")] public static extern uint GetMenuItemID(IntPtr m, int pos);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern int GetMenuString(IntPtr m, uint item, StringBuilder s, int max, uint flag);
    [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr h, uint msg, IntPtr w, IntPtr l);
    public static string MenuText(IntPtr m, int pos) {
        StringBuilder text = new StringBuilder(256);
        GetMenuString(m, (uint)pos, text, 256, 0x400);
        return text.ToString().Split('	')[0].Replace("&", "").Trim();
    }
    [DllImport("user32.dll", SetLastError = true)] public static extern uint SendInput(uint n, INPUT[] inputs, int size);
    [DllImport("kernel32.dll")] public static extern IntPtr OpenProcess(uint access, bool inherit, uint pid);
    [DllImport("kernel32.dll")] public static extern bool CloseHandle(IntPtr h);
    [DllImport("advapi32.dll", SetLastError = true)] public static extern bool OpenProcessToken(IntPtr p, uint access, out IntPtr token);
    [DllImport("advapi32.dll", SetLastError = true)]
    public static extern bool GetTokenInformation(IntPtr t, int cls, out int info, int len, out int ret);
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
    [StructLayout(LayoutKind.Explicit, Size = 40)]
    public struct INPUT {
        [FieldOffset(0)] public uint type;
        [FieldOffset(8)] public ushort wVk;
        [FieldOffset(10)] public ushort wScan;
        [FieldOffset(12)] public uint dwFlags;
        [FieldOffset(16)] public uint time;
        [FieldOffset(24)] public IntPtr extra;
    }
    public static string InputDesktopName() {
        IntPtr d = OpenInputDesktop(0, false, 0x0001);
        if (d == IntPtr.Zero) return null;
        try {
            StringBuilder name = new StringBuilder(256);
            int needed;
            return GetUserObjectInformation(d, 2, name, 512, out needed) ? name.ToString() : null;
        } finally { CloseDesktop(d); }
    }
    public static bool IsElevated(uint pid) {
        IntPtr p = OpenProcess(0x1000, false, pid);
        if (p == IntPtr.Zero) return true;
        try {
            IntPtr t;
            if (!OpenProcessToken(p, 0x8, out t)) return true;
            try {
                int elevated; int ret;
                if (!GetTokenInformation(t, 20, out elevated, 4, out ret)) return true;
                return elevated != 0;
            } finally { CloseHandle(t); }
        } finally { CloseHandle(p); }
    }
    public static uint Send(INPUT[] inputs) { return SendInput((uint)inputs.Length, inputs, 40); }
}
'@

$A = [System.Windows.Automation.AutomationElement]
$Scope = [System.Windows.Automation.TreeScope]
$Epoch = [DateTime]::new(1970, 1, 1, 0, 0, 0, [DateTimeKind]::Utc)

function Get-CreateTime([int]$processId) {
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if ($null -eq $process) { return $null }
    return ($process.StartTime.ToUniversalTime() - $Epoch).TotalSeconds
}

function Get-Probe {
    $name = [RfNative]::InputDesktopName()
    return @{
        ok = $true
        interactive = [Environment]::UserInteractive
        session_id = (Get-Process -Id $PID).SessionId
        input_desktop = $name
        locked = ($name -ne 'Default')
        elevated = [RfNative]::IsElevated([uint32]$PID)
    }
}

function Assert-Desktop {
    $probe = Get-Probe
    if (-not $probe.interactive -or $probe.locked) { Fail 'desktop_unavailable' }
}

function Resolve-Target($target) {
    if ($null -eq $target) { Fail 'target_changed' }
    $hwnd = [IntPtr][long]$target.hwnd
    if (-not [RfNative]::IsWindow($hwnd)) { Fail 'target_changed' }
    [uint32]$owner = 0
    [void][RfNative]::GetWindowThreadProcessId($hwnd, [ref]$owner)
    if ($owner -ne [uint32]$target.pid) { Fail 'target_changed' }
    $created = Get-CreateTime ([int]$target.pid)
    if ($null -eq $created -or [Math]::Abs($created - [double]$target.create_time) -gt 0.01) { Fail 'target_changed' }
    if ([RfNative]::IsElevated([uint32]$target.pid)) { Fail 'target_elevated' }
    return $A::FromHandle($hwnd)
}

function Describe($element) {
    $current = $element.Current
    $patterns = @($element.GetSupportedPatterns() | ForEach-Object { $_.ProgrammaticName -replace 'PatternIdentifiers.Pattern', '' })
    return [ordered]@{
        automation_id = $current.AutomationId
        name = $current.Name
        class = $current.ClassName
        control_type = ($current.ControlType.ProgrammaticName -replace '^ControlType\.', '')
        patterns = $patterns
        enabled = $current.IsEnabled
    }
}

function Build-Tree($element, [int]$depth, [ref]$budget) {
    $node = Describe $element
    if ($depth -gt 0 -and $budget.Value -gt 0) {
        $children = @()
        $walker = [System.Windows.Automation.TreeWalker]::ControlViewWalker
        $child = $walker.GetFirstChild($element)
        while ($null -ne $child -and $budget.Value -gt 0) {
            $budget.Value--
            $children += ,(Build-Tree $child ($depth - 1) $budget)
            $child = $walker.GetNextSibling($child)
        }
        $node.children = $children
    }
    return $node
}

function Get-TargetWindows($window) {
    # The main window plus top-level windows of the same verified process (dialogs).
    $processId = $window.Current.ProcessId
    $condition = New-Object System.Windows.Automation.PropertyCondition($A::ProcessIdProperty, $processId)
    $windows = @($window)
    foreach ($other in $A::RootElement.FindAll($Scope::Children, $condition)) {
        if ($other.Current.NativeWindowHandle -ne $window.Current.NativeWindowHandle) { $windows += $other }
    }
    return $windows
}

function Get-MenuTree([IntPtr]$menu, [int]$depth) {
    $items = @()
    if ($menu -eq [IntPtr]::Zero -or $depth -gt 2) { return $items }
    for ($index = 0; $index -lt [RfNative]::GetMenuItemCount($menu); $index++) {
        $text = [RfNative]::MenuText($menu, $index)
        if (-not $text) { continue }
        $sub = [RfNative]::GetSubMenu($menu, $index)
        $item = [ordered]@{ text = $text }
        if ($sub -ne [IntPtr]::Zero) { $item.items = @(Get-MenuTree $sub ($depth + 1)) }
        $items += ,$item
    }
    return $items
}

function Invoke-MenuPath($target, $path) {
    $menu = [RfNative]::GetMenu([IntPtr][long]$target.hwnd)
    if ($menu -eq [IntPtr]::Zero) { Fail 'menu_not_found' }
    $parts = @($path)
    for ($level = 0; $level -lt $parts.Count; $level++) {
        $match = -1
        for ($index = 0; $index -lt [RfNative]::GetMenuItemCount($menu); $index++) {
            if ([RfNative]::MenuText($menu, $index) -ieq ([string]$parts[$level]).Replace('&', '').Trim()) {
                if ($match -ge 0) { Fail 'menu_ambiguous' }
                $match = $index
            }
        }
        if ($match -lt 0) { Fail 'menu_not_found' }
        if ($level -lt $parts.Count - 1) {
            $menu = [RfNative]::GetSubMenu($menu, $match)
            if ($menu -eq [IntPtr]::Zero) { Fail 'menu_not_found' }
        } else {
            $command = [RfNative]::GetMenuItemID($menu, $match)
            if ($command -eq 0 -or $command -eq [uint32]::MaxValue) { Fail 'menu_not_command' }
            [void][RfNative]::PostMessage([IntPtr][long]$target.hwnd, 0x111, [IntPtr][long]$command, [IntPtr]::Zero)
            return $command
        }
    }
}

function Find-Control($window, $control) {
    if ($null -eq $control) { Fail 'control_not_found' }
    $conditions = @()
    if ($control.automation_id) {
        $conditions += New-Object System.Windows.Automation.PropertyCondition($A::AutomationIdProperty, [string]$control.automation_id)
    }
    if ($control.name) {
        $conditions += New-Object System.Windows.Automation.PropertyCondition($A::NameProperty, [string]$control.name)
    }
    if ($conditions.Count -eq 0 -and -not $control.control_type) { Fail 'control_not_found' }
    $condition = if ($conditions.Count -eq 0) { [System.Windows.Automation.Condition]::TrueCondition }
        elseif ($conditions.Count -eq 1) { $conditions[0] }
        else { New-Object System.Windows.Automation.AndCondition($conditions) }
    $found = @(Get-TargetWindows $window | ForEach-Object { $_.FindAll($Scope::Descendants, $condition) } | Where-Object {
        -not $control.control_type -or ($_.Current.ControlType.ProgrammaticName -eq ('ControlType.' + [string]$control.control_type))
    } | Sort-Object { $_.Current.NativeWindowHandle } -Unique)
    if ($found.Count -eq 0) { Fail 'control_not_found' }
    if ($found.Count -gt 1) { Fail 'control_ambiguous' }
    return $found[0]
}

function Test-Foreground($target) {
    [uint32]$owner = 0
    [void][RfNative]::GetWindowThreadProcessId([RfNative]::GetForegroundWindow(), [ref]$owner)
    return $owner -eq [uint32]$target.pid
}

function Focus-Target($target, $element) {
    # A background worker cannot take the foreground directly; attaching to the
    # current foreground thread's input queue lets SetForegroundWindow succeed.
    $hwnd = [IntPtr][long]$target.hwnd
    if ([RfNative]::IsIconic($hwnd)) { [void][RfNative]::ShowWindow($hwnd, 9) }
    $current = [RfNative]::GetCurrentThreadId()
    for ($attempt = 0; $attempt -lt 3 -and -not (Test-Foreground $target); $attempt++) {
        [uint32]$ignored = 0
        $foreground = [RfNative]::GetWindowThreadProcessId([RfNative]::GetForegroundWindow(), [ref]$ignored)
        $attached = $foreground -ne 0 -and $foreground -ne $current -and [RfNative]::AttachThreadInput($current, $foreground, $true)
        try {
            [void][RfNative]::BringWindowToTop($hwnd)
            [void][RfNative]::SetForegroundWindow($hwnd)
        } finally {
            if ($attached) { [void][RfNative]::AttachThreadInput($current, $foreground, $false) }
        }
        Start-Sleep -Milliseconds 120
    }
    if (-not (Test-Foreground $target)) { Fail 'foreground_denied' }
    if ($null -ne $element) { $element.SetFocus() }
}

function Insert-NativeText($element, [string]$text) {
    # Classic edit controls accept text directly, without focus or synthetic keys.
    if ($null -eq $element) { return $false }
    $class = [string]$element.Current.ClassName
    $handle = [IntPtr][long]$element.Current.NativeWindowHandle
    if ($handle -eq [IntPtr]::Zero -or -not ($class -eq 'Edit' -or $class -like 'RichEdit*')) { return $false }
    [void][RfNative]::SendMessage($handle, 0xC2, [IntPtr]1, $text)
    return $true
}

function Find-DefaultEdit($window) {
    # Classic editors expose their text box with varying control types (Pane, Document,
    # Edit); the native class name is the stable signal.
    $found = @($window.FindAll($Scope::Children, [System.Windows.Automation.Condition]::TrueCondition) | Where-Object {
        $class = [string]$_.Current.ClassName
        ($class -eq 'Edit' -or $class -like 'RichEdit*') -and $_.Current.NativeWindowHandle -ne 0
    })
    if ($found.Count -eq 1) { return $found[0] }
    return $null
}

function New-Key([uint16]$vk, [uint16]$scan, [uint32]$flags) {
    $item = New-Object RfNative+INPUT
    $item.type = 1
    $item.wVk = $vk
    $item.wScan = $scan
    $item.dwFlags = $flags
    return $item
}

function Send-Text([string]$text) {
    $inputs = New-Object System.Collections.Generic.List[RfNative+INPUT]
    foreach ($char in $text.ToCharArray()) {
        $inputs.Add((New-Key 0 ([uint16]$char) 0x4))
        $inputs.Add((New-Key 0 ([uint16]$char) 0x6))
    }
    if ($inputs.Count -gt 0 -and [RfNative]::Send($inputs.ToArray()) -ne $inputs.Count) { Fail 'input_rejected' }
}

$Chords = @{
    'ctrl+s' = @(0x11, 0x53); 'ctrl+a' = @(0x11, 0x41); 'enter' = @(0x0D); 'tab' = @(0x09)
    'escape' = @(0x1B); 'alt+f4' = @(0x12, 0x73)
}

function Send-Chord([string]$chord) {
    if (-not $Chords.ContainsKey($chord)) { Fail 'chord_not_allowed' }
    $keys = $Chords[$chord]
    $inputs = @()
    foreach ($vk in $keys) { $inputs += New-Key ([uint16]$vk) 0 0 }
    [array]::Reverse($keys)
    foreach ($vk in $keys) { $inputs += New-Key ([uint16]$vk) 0 0x2 }
    if ([RfNative]::Send([RfNative+INPUT[]]$inputs) -ne $inputs.Count) { Fail 'input_rejected' }
}

try {
    $request = [Console]::In.ReadToEnd() | ConvertFrom-Json
    switch ([string]$request.op) {
        'probe' { Write-Result (Get-Probe) }
        'launch' {
            Assert-Desktop
            # An elevated runtime would create elevated targets; RelayForge must run unelevated.
            if ([RfNative]::IsElevated([uint32]$PID)) { Fail 'runtime_elevated' }
            $process = Start-Process -FilePath ([string]$request.exe) -PassThru
            $deadline = (Get-Date).AddSeconds(15)
            while ((Get-Date) -lt $deadline) {
                $process.Refresh()
                if ($process.MainWindowHandle -ne [IntPtr]::Zero) { break }
                Start-Sleep -Milliseconds 200
            }
            if ($process.MainWindowHandle -eq [IntPtr]::Zero) { Fail 'window_not_found' }
            Write-Result @{
                ok = $true; pid = $process.Id; create_time = (Get-CreateTime $process.Id)
                hwnd = [long]$process.MainWindowHandle; title = $process.MainWindowTitle
            }
        }
        'inspect' {
            $window = Resolve-Target $request.target
            $budget = [int]$request.limit
            $dialogs = @(Get-TargetWindows $window | Select-Object -Skip 1 | ForEach-Object { Build-Tree $_ ([int]$request.depth) ([ref]$budget) })
            $menu = @(Get-MenuTree ([RfNative]::GetMenu([IntPtr][long]$request.target.hwnd)) 0)
            Write-Result @{ ok = $true; tree = (Build-Tree $window ([int]$request.depth) ([ref]$budget)); dialogs = $dialogs; menu = $menu }
        }
        'invoke' {
            Assert-Desktop
            $element = Find-Control (Resolve-Target $request.target) $request.control
            $pattern = $null
            if ($element.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern, [ref]$pattern)) {
                $pattern.Invoke()
            } elseif ($element.Current.ClassName -eq 'Button' -and $element.Current.NativeWindowHandle -ne 0) {
                [void][RfNative]::PostMessage([IntPtr][long]$element.Current.NativeWindowHandle, 0x00F5, [IntPtr]::Zero, [IntPtr]::Zero)
            } else { Fail 'pattern_unsupported' }
            Write-Result @{ ok = $true; control = (Describe $element) }
        }
        'menu' {
            Assert-Desktop
            [void](Resolve-Target $request.target)
            $command = Invoke-MenuPath $request.target $request.path
            Write-Result @{ ok = $true; menu_path = @($request.path); command_id = $command }
        }
        'set_value' {
            Assert-Desktop
            $element = Find-Control (Resolve-Target $request.target) $request.control
            $pattern = $null
            if ($element.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern, [ref]$pattern)) {
                $pattern.SetValue([string]$request.value)
            } elseif ([string]$element.Current.ClassName -eq 'Edit' -and $element.Current.NativeWindowHandle -ne 0) {
                [void][RfNative]::SendMessage([IntPtr][long]$element.Current.NativeWindowHandle, 0x000C, [IntPtr]::Zero, [string]$request.value)
            } else { Fail 'pattern_unsupported' }
            Write-Result @{ ok = $true; control = (Describe $element) }
        }
        'type_text' {
            Assert-Desktop
            $window = Resolve-Target $request.target
            $element = if ($request.control) { Find-Control $window $request.control } else { Find-DefaultEdit $window }
            $method = 'edit_message'
            if (-not (Insert-NativeText $element ([string]$request.text))) {
                Focus-Target $request.target $element
                Send-Text ([string]$request.text)
                $method = 'keyboard'
            }
            Write-Result @{ ok = $true; typed_chars = ([string]$request.text).Length; method = $method }
        }
        'keys' {
            Assert-Desktop
            [void](Resolve-Target $request.target)
            Focus-Target $request.target $null
            Send-Chord ([string]$request.chord)
            Write-Result @{ ok = $true; chord = [string]$request.chord }
        }
        'capture' {
            Assert-Desktop
            [void](Resolve-Target $request.target)
            $hwnd = [IntPtr][long]$request.target.hwnd
            $rect = New-Object RfNative+RECT
            [void][RfNative]::GetWindowRect($hwnd, [ref]$rect)
            $width = [Math]::Max(1, $rect.Right - $rect.Left)
            $height = [Math]::Max(1, $rect.Bottom - $rect.Top)
            $bitmap = New-Object System.Drawing.Bitmap($width, $height)
            $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
            $hdc = $graphics.GetHdc()
            try { $printed = [RfNative]::PrintWindow($hwnd, $hdc, 2) } finally { $graphics.ReleaseHdc($hdc); $graphics.Dispose() }
            if (-not $printed) { $bitmap.Dispose(); Fail 'capture_failed' }
            $stream = New-Object System.IO.MemoryStream
            $bitmap.Save($stream, [System.Drawing.Imaging.ImageFormat]::Png)
            $bitmap.Dispose()
            Write-Result @{ ok = $true; png_base64 = [Convert]::ToBase64String($stream.ToArray()); width = $width; height = $height }
        }
        'close' {
            [void](Resolve-Target $request.target)
            [void][RfNative]::PostMessage([IntPtr][long]$request.target.hwnd, 0x10, [IntPtr]::Zero, [IntPtr]::Zero)
            Write-Result @{ ok = $true }
        }
        default { Fail 'operation_not_allowed' }
    }
} catch {
    $detail = ($_.Exception.Message -replace '\s+', ' ')
    Write-Result @{ ok = $false; error = 'worker_error'; detail = $detail.Substring(0, [Math]::Min(200, $detail.Length)) }
}
