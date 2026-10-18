using System.Runtime.InteropServices;

namespace PersianAiKit.Photo.Ai;

/// <summary>حافظهٔ آزادِ دستگاه — پیش از اجرای مدلِ سنگین وارسی می‌شود تا کامپیوتر قفل نکند.</summary>
public static class SystemMemory
{
    /// <summary>حافظهٔ فیزیکیِ آزاد (MB)؛ نامعلوم ⇒ null.</summary>
    public static long? AvailableMB()
    {
        try
        {
            if (OperatingSystem.IsWindows())
            {
                var m = new MemoryStatusEx { Length = (uint)Marshal.SizeOf<MemoryStatusEx>() };
                return GlobalMemoryStatusEx(ref m) ? (long)(m.AvailPhys / 1048576) : null;
            }
            if (OperatingSystem.IsLinux() && File.Exists("/proc/meminfo"))
            {
                var line = File.ReadLines("/proc/meminfo").FirstOrDefault(l => l.StartsWith("MemAvailable:"));
                var kb = line?.Split(' ', StringSplitOptions.RemoveEmptyEntries)[1];
                return kb is null ? null : long.Parse(kb) / 1024;
            }
        }
        catch (Exception e) when (e is IOException or FormatException or DllNotFoundException) { }
        return null;
    }

    /// <summary>کلِ حافظهٔ فیزیکی (MB).</summary>
    public static long TotalMB() => GC.GetGCMemoryInfo().TotalAvailableMemoryBytes / 1048576;

    [StructLayout(LayoutKind.Sequential)]
    private struct MemoryStatusEx
    {
        public uint Length, MemoryLoad;
        public ulong TotalPhys, AvailPhys, TotalPageFile, AvailPageFile, TotalVirtual, AvailVirtual, AvailExtendedVirtual;
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool GlobalMemoryStatusEx(ref MemoryStatusEx m);
}
