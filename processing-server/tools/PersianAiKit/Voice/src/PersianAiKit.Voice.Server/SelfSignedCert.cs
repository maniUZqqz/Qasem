using System.Net;
using System.Net.NetworkInformation;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;

namespace PersianAiKit.Server;

/// <summary>
/// گواهیِ خودامضای https برای شبکهٔ داخلی. چرا: مرورگرِ گوشی میکروفون و دوربین را فقط در «محیطِ امن» می‌دهد (https یا localhost).
/// همهٔ IPهای این کامپیوتر + نامش در گواهی‌اند؛ IP عوض شود ⇒ گواهیِ تازه. هر گوشی بارِ اول یک هشدار می‌بیند («ادامه/Proceed»).
/// </summary>
public static class SelfSignedCert
{
    public static X509Certificate2 LoadOrCreate(string pfxPath)
    {
        var (machine, ips) = HostNames();
        try
        {
            if (File.Exists(pfxPath))
            {
                var old = Load(File.ReadAllBytes(pfxPath));
                var san = old.Extensions.OfType<X509SubjectAlternativeNameExtension>().FirstOrDefault();
                var have = san?.EnumerateIPAddresses().Select(a => a.ToString()).ToHashSet() ?? new HashSet<string>();
                if (old.NotAfter > DateTime.Now.AddDays(30) && ips.All(have.Contains)) return old;
            }
        }
        catch
        {
            // فایلِ خراب ⇒ از نو
        }

        using var rsa = RSA.Create(2048);
        var req = new CertificateRequest($"CN={machine}", rsa, HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1);
        var sb = new SubjectAlternativeNameBuilder();
        sb.AddDnsName("localhost");
        sb.AddDnsName(machine);
        foreach (var ip in ips) sb.AddIpAddress(IPAddress.Parse(ip));
        req.CertificateExtensions.Add(sb.Build());
        req.CertificateExtensions.Add(new X509BasicConstraintsExtension(false, false, 0, true));
        req.CertificateExtensions.Add(new X509KeyUsageExtension(X509KeyUsageFlags.DigitalSignature | X509KeyUsageFlags.KeyEncipherment, true));
        req.CertificateExtensions.Add(new X509EnhancedKeyUsageExtension(new OidCollection { new Oid("1.3.6.1.5.5.7.3.1") }, false));
        using var fresh = req.CreateSelfSigned(DateTimeOffset.Now.AddDays(-1), DateTimeOffset.Now.AddDays(825));
        var pfx = fresh.Export(X509ContentType.Pfx);
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(pfxPath)!);
            File.WriteAllBytes(pfxPath, pfx);
        }
        catch
        {
            // ذخیره نشد ⇒ هر اجرا گواهیِ تازه، ولی کار می‌کند
        }
        // ⚠ روی ویندوز SslStream با کلیدِ موقتِ CreateSelfSigned کار نمی‌کند ⇒ از PFX دوباره بار شود
        return Load(pfx);
    }

    private static X509Certificate2 Load(byte[] pfx) =>
#if NET9_0_OR_GREATER
        X509CertificateLoader.LoadPkcs12(pfx, null);
#else
        new(pfx, (string?)null, X509KeyStorageFlags.Exportable);
#endif

    /// <summary>IPv4های فعالِ این کامپیوتر (بی loopback).</summary>
    public static List<string> LanIps()
    {
        try
        {
            return NetworkInterface.GetAllNetworkInterfaces()
                .Where(n => n.OperationalStatus == OperationalStatus.Up && n.NetworkInterfaceType != NetworkInterfaceType.Loopback)
                .SelectMany(n => n.GetIPProperties().UnicastAddresses)
                .Where(a => a.Address.AddressFamily == AddressFamily.InterNetwork && !IPAddress.IsLoopback(a.Address))
                .Select(a => a.Address.ToString()).Distinct().ToList();
        }
        catch { return new List<string>(); }
    }

    private static (string Machine, List<string> Ips) HostNames()
    {
        var ips = new List<string> { "127.0.0.1" };
        ips.AddRange(LanIps());
        return (Environment.MachineName, ips.Distinct().ToList());
    }
}
