// 钢琴手套 · 单文件启动器（11-09 用户：单文件每次启动 10~16 秒太慢）
//
// 对外仍然只有一个 钢琴手套.exe。它 = 这个小启动器 + 末尾附带的程序压缩包。
// 第一次打开：把程序解到 %LOCALAPPDATA%\PianoGloveSoftware\runtime\<版本>\（显示进度窗口，只做一次）；
// 以后每次：直接启动解好的那份（约 1 秒）。换了新版本（版本号不同）就解一份新的，旧的顺手删掉。
// 解到一半断电/被杀：没写完成标记，下次重新解，不会用到半截文件。
//
// 文件尾格式：[zip 字节][8 字节 zip 长度，小端][8 字节魔数 "PGLPAYLD"]
using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Text;
using System.Threading;
using System.Windows.Forms;

static class PianoGloveLauncher
{
    const string Version = "@@VERSION@@";   // 打包时替换成程序包的 SHA-256 前 16 位
    const string Magic = "PGLPAYLD";
    const string AppExe = "PianoGloveSoftware.exe";

    [STAThread]
    static int Main(string[] args)
    {
        string local = Environment.GetEnvironmentVariable("LOCALAPPDATA");
        if (string.IsNullOrEmpty(local)) local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        string root = Path.Combine(local, "PianoGloveSoftware", "runtime");   // 先认环境变量：程序本身也这样找数据目录，隔离测试才真隔离
        string target = Path.Combine(root, Version);
        string marker = Path.Combine(target, ".ready");
        try
        {
            if (!File.Exists(marker) || !File.Exists(Path.Combine(target, AppExe)))
            {
                string error = ExtractWithProgress(root, target, marker);
                if (error != null)
                {
                    MessageBox.Show("钢琴手套没能准备好：" + error + "\n\n请确认 C 盘还有 1 GB 以上空间后再打开。", "钢琴手套", MessageBoxButtons.OK, MessageBoxIcon.Error);
                    return 2;
                }
                CleanOld(root);
            }
            var info = new ProcessStartInfo(Path.Combine(target, AppExe), Join(args)) { UseShellExecute = false, WorkingDirectory = target };
            info.EnvironmentVariables["PIANO_GLOVE_LAUNCHER"] = Application.ExecutablePath;
            using (var child = Process.Start(info))
            {
                child.WaitForExit();
                return child.ExitCode;
            }
        }
        catch (Exception e)
        {
            MessageBox.Show("钢琴手套打不开：" + e.Message, "钢琴手套", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }

    static string Join(string[] args)
    {
        var sb = new StringBuilder();
        foreach (var a in args)
        {
            if (sb.Length > 0) sb.Append(' ');
            sb.Append('"').Append(a.Replace("\"", "\\\"")).Append('"');
        }
        return sb.ToString();
    }

    static string ExtractWithProgress(string root, string target, string marker)
    {
        string error = null;
        var form = new Form
        {
            Text = "钢琴手套", Width = 440, Height = 170, FormBorderStyle = FormBorderStyle.FixedDialog,
            StartPosition = FormStartPosition.CenterScreen, MaximizeBox = false, MinimizeBox = false, BackColor = Color.FromArgb(245, 240, 232)
        };
        try { form.Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); } catch { }
        var label = new Label { Text = "第一次打开，正在准备（只需要一次）…", Left = 24, Top = 22, Width = 380, Font = new Font("Microsoft YaHei UI", 11f, FontStyle.Bold) };
        var bar = new ProgressBar { Left = 24, Top = 62, Width = 380, Height = 22, Minimum = 0, Maximum = 1000 };
        form.Controls.Add(label); form.Controls.Add(bar);
        bool silent = Environment.GetEnvironmentVariable("PIANO_GLOVE_SILENT_PREPARE") == "1";
        var worker = new Thread(() =>
        {
            try { Extract(root, target, marker, p => { try { form.BeginInvoke((Action)(() => bar.Value = Math.Min(1000, (int)(p * 1000)))); } catch { } }); }
            catch (Exception e) { error = e.Message; }
            try { form.BeginInvoke((Action)(() => form.Close())); } catch { }
        });
        form.Shown += (s, e) => worker.Start();
        if (silent) { form.Opacity = 0; form.ShowInTaskbar = false; }
        Application.Run(form);
        worker.Join();
        return error;
    }

    static void Extract(string root, string target, string marker, Action<double> progress)
    {
        string exe = Application.ExecutablePath;
        using (var file = new FileStream(exe, FileMode.Open, FileAccess.Read, FileShare.Read))
        {
            var tail = new byte[16];
            file.Seek(-16, SeekOrigin.End);
            file.Read(tail, 0, 16);
            if (Encoding.ASCII.GetString(tail, 8, 8) != Magic) throw new InvalidDataException("程序文件不完整（请重新下载钢琴手套.exe）");
            long length = BitConverter.ToInt64(tail, 0);
            long start = file.Length - 16 - length;
            if (length <= 0 || start < 0) throw new InvalidDataException("程序文件不完整（请重新下载钢琴手套.exe）");
            string temp = target + ".part";
            if (Directory.Exists(temp)) Directory.Delete(temp, true);
            if (Directory.Exists(target)) Directory.Delete(target, true);
            Directory.CreateDirectory(temp);
            using (var slice = new SubStream(file, start, length))
            using (var zip = new ZipArchive(slice, ZipArchiveMode.Read))
            {
                long total = 0, done = 0;
                foreach (var entry in zip.Entries) total += entry.Length;
                string tempFull = Path.GetFullPath(temp) + Path.DirectorySeparatorChar;
                foreach (var entry in zip.Entries)
                {
                    string path = Path.GetFullPath(Path.Combine(temp, entry.FullName));
                    if (!path.StartsWith(tempFull, StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("程序包内路径不正确");
                    if (entry.FullName.EndsWith("/")) { Directory.CreateDirectory(path); continue; }
                    Directory.CreateDirectory(Path.GetDirectoryName(path));
                    entry.ExtractToFile(path, true);
                    done += entry.Length;
                    if (total > 0) progress((double)done / total);
                }
            }
            Directory.Move(temp, target);
            File.WriteAllText(marker, Version);
        }
    }

    static void CleanOld(string root)
    {
        try
        {
            foreach (var dir in Directory.GetDirectories(root))
                if (!string.Equals(Path.GetFileName(dir), Version, StringComparison.OrdinalIgnoreCase))
                    try { Directory.Delete(dir, true); } catch { }   // 旧版本正在运行时删不掉，下次再删
        }
        catch { }
    }
}

// zip 不在文件开头，给 ZipArchive 一个从压缩包起点开始的“窗口”
sealed class SubStream : Stream
{
    readonly Stream inner; readonly long start, length; long position;
    public SubStream(Stream inner, long start, long length) { this.inner = inner; this.start = start; this.length = length; }
    public override bool CanRead { get { return true; } }
    public override bool CanSeek { get { return true; } }
    public override bool CanWrite { get { return false; } }
    public override long Length { get { return length; } }
    public override long Position { get { return position; } set { position = value; } }
    public override void Flush() { }
    public override int Read(byte[] buffer, int offset, int count)
    {
        long left = length - position; if (left <= 0) return 0;
        if (count > left) count = (int)left;
        inner.Seek(start + position, SeekOrigin.Begin);
        int n = inner.Read(buffer, offset, count); position += n; return n;
    }
    public override long Seek(long offset, SeekOrigin origin)
    {
        long p = origin == SeekOrigin.Begin ? offset : origin == SeekOrigin.Current ? position + offset : length + offset;
        if (p < 0) throw new IOException("seek"); position = p; return p;
    }
    public override void SetLength(long value) { throw new NotSupportedException(); }
    public override void Write(byte[] buffer, int offset, int count) { throw new NotSupportedException(); }
}
